# backend/app/services/admin_boundary.py

import logging
import time
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from sqlalchemy.exc import OperationalError, DBAPIError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from app.core.constants import AdminLevel
from app.db.init_postgis import PostGISManager
from app.models.database_models import SenegalAdminBoundary, OffreEmploiBrute
from app.models.api_models import AdminBoundaryOut
from app.core.exceptions import AppError, NotFoundError, ValidationError

logger = logging.getLogger(__name__)


class AdminBoundaryService:
    """
    Service pour gérer les limites administratives avec :
    - Retry automatique sur erreurs réseau
    - Timeout sur les requêtes longues
    - Gestion fine des erreurs PostGIS
    """
    
    def __init__(self):
        self.postgis_manager = PostGISManager()
    
    # ============================================================
    # DECORATOR : Retry sur erreurs réseau (Neon)
    # ============================================================
    @staticmethod
    def with_network_retry(func):
        """Décorateur pour retry sur OperationalError (problèmes réseau)."""
        return retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type(OperationalError),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )(func)
    
    # ============================================================
    # METHODES PRINCIPALES
    # ============================================================
    
    @with_network_retry
    def get_boundaries(self, db: Session, level: str) -> List[AdminBoundaryOut]:
        """
        Récupère les limites administratives avec vérification PostGIS.
        
        Args:
            db: Session SQLAlchemy
            level: Niveau admin ('quartier', 'commune', etc.)
        
        Returns:
            Liste des limites avec leurs métadonnées
        
        Raises:
            AppError: Si PostGIS manque ou erreur réseau persistante
            ValidationError: Si level invalide
        """
        # Validation du level
        valid_levels = {"region", "departement", "commune", "arrondissement", "quartier"}
        if level not in valid_levels:
            raise ValidationError(
                field="level",
                reason=f"Valeur '{level}' non autorisée",
                context={"valid_values": list(valid_levels)},
            )
        
        # Vérifie PostGIS (une fois par session)
        self.postgis_manager.ensure_postgis(db)
        
        try:
            # Requête principale avec timeout
            query = db.query(SenegalAdminBoundary).filter_by(level=level)
            
            # Timeout de 30s pour éviter blocages (Neon peut être lent)
            boundaries = query.execution_options(timeout=30).all()
            
            if not boundaries:
                logger.warning(f"Aucune limite trouvée pour level='{level}'")
            
            return [AdminBoundaryOut.from_orm(b) for b in boundaries]
            
        except OperationalError as e:
            # Erreur réseau même après retry
            logger.error(f"❌ Erreur réseau persistante : {e}")
            raise AppError(
                message="Impossible de se connecter à la base de données",
                context={"network_error": True, "level": level},
                status_code=503,
            ) from e
            
        except DBAPIError as e:
            # Erreur SQL (ex: PostGIS mal installé)
            logger.exception("❌ Erreur SQL lors de la récupération des limites")
            raise AppError(
                message="Erreur de requête géospatiale",
                context={"postgis_error": True, "sql_message": str(e.orig)},
                status_code=500,
            ) from e

    # ------------------------------------------------------------
    # Normalisation des noms
    # ------------------------------------------------------------
    def _normalize_name(self, name: Optional[str]) -> str:
        import unicodedata

        if not isinstance(name, str):
            return ""

        # Garder seulement avant la virgule → "Dakar, Sénégal" → "Dakar"
        if "," in name:
            name = name.split(",")[0]

        name = name.lower().strip()

        # Supprimer accents
        name = "".join(
            c for c in unicodedata.normalize("NFD", name)
            if unicodedata.category(c) != "Mn"
        )

        # Remplacer séparateurs
        name = name.replace("-", " ").replace("_", " ")

        # Compacter espaces
        return " ".join(name.split())


    from sqlalchemy import func
    from sqlalchemy.sql import expression
    from typing import Optional

    @with_network_retry
    def refresh_offer_counts(self, db: Session, level: str) -> Dict[str, Any]:
        """
        Recalcule les compteurs d'offres d'emploi pour un niveau administratif donné.
        Utilise la session fournie par FastAPI (pas de db.begin()).
        """

        self.postgis_manager.ensure_postgis(db)

        try:
            logger.info(f"🔄 Début du refresh des compteurs pour level={level}")

            boundaries = (
                db.query(SenegalAdminBoundary)
                .filter(SenegalAdminBoundary.level == level)
                .all()
            )

            if not boundaries:
                logger.warning(f"⚠️ Aucun boundary trouvé pour level='{level}'")
                return {
                    "status": "success",
                    "updated_rows": 0,
                    "level": level,
                    "total_boundaries": 0,
                }

            total_updated = 0

            for boundary in boundaries:

                # --- 🔥 Normalisation Python ---
                normalized_boundary_name = self._normalize_name(str(boundary.name))

                # --- 🔥 Normalisation SQL ÉQUIVALENTE ---
                sql_location_normalized = func.lower(
                    func.unaccent(
                        func.split_part(OffreEmploiBrute.location, ",", 1)  # -> avant virgule
                    )
                )

                sql_location_normalized = func.replace(sql_location_normalized, "-", " ")
                sql_location_normalized = func.replace(sql_location_normalized, "_", " ")

                # Nettoyage espaces multiples
                sql_location_normalized = func.regexp_replace(
                    sql_location_normalized, r"\s+", " ", "g"
                )

                # Trim
                sql_location_normalized = func.trim(sql_location_normalized)

                # ---- Calcul du count ----
                count = (
                    db.query(OffreEmploiBrute)
                    .filter(sql_location_normalized == normalized_boundary_name)
                    .count()
                )

                # ---- Mise à jour si différent ----
                if boundary.offer_count != count:
                    boundary.offer_count = count
                    total_updated += 1

            if total_updated > 0:
                db.commit()
                logger.info(f"✅ {total_updated} compteurs mis à jour pour level={level}")
            else:
                logger.info("ℹ️ Aucun changement")

            return {
                "status": "success",
                "updated_rows": total_updated,
                "level": level,
                "total_boundaries": len(boundaries),
            }

        except OperationalError as e:
            db.rollback()
            raise AppError(
                message="Timeout ou problème réseau.",
                context={"level": level},
                status_code=503,
            ) from e

        except Exception as e:
            db.rollback()
            raise AppError(
                message="Erreur inattendue.",
                context={"error": str(e), "level": level},
                status_code=500,
            ) from e


        
    @with_network_retry
    def get_boundary_by_name(self, db: Session, name: str, level: str) -> AdminBoundaryOut:
        """
        Récupère une limite spécifique par son nom.
        Utile pour les tests et le débugging.
        """
        self.postgis_manager.ensure_postgis(db)
        
        boundary = db.query(SenegalAdminBoundary).filter_by(
            name=name,
            level=level
        ).first()
        
        if not boundary:
            raise NotFoundError(
                resource="AdminBoundary",
                identifier=f"{level}/{name}",
                context={"search_params": {"name": name, "level": level}},
            )
        
        return AdminBoundaryOut.from_orm(boundary)
    
# backend/app/services/admin_boundary.py


from app.models.api_models import ChoroplethResponse, OfferGeoJSON

class CarteService:
    """Service dédié à la génération de données cartographiques."""
    
    def __init__(self, admin_service: AdminBoundaryService):
        self.admin_service = admin_service
    
    @AdminBoundaryService.with_network_retry
    def get_choropleth_data(
        self, 
        db: Session, 
        level: AdminLevel,
        min_offers: int = 1
    ) -> ChoroplethResponse:
        """
        Récupère les données formatées pour une carte choroplèthe.
        
        Args:
            db: Session SQLAlchemy
            level: Niveau administratif (enum)
            min_offers: Filtrer les entités avec moins de X offres
        
        Returns:
            FeatureCollection GeoJSON + métadonnées
        """
        # ✅ Validation stricte
        if not isinstance(level, AdminLevel):
            raise ValidationError(
                field="level",
                reason="Doit être une valeur AdminLevel enum",
                context={"valid_values": [l.value for l in AdminLevel]},
            )
        
        # ✅ Vérifie PostGIS
        self.admin_service.postgis_manager.ensure_postgis(db)
        
        try:
            # Récupère les limites avec compteurs à jour
            boundaries = db.query(SenegalAdminBoundary).filter_by(
                level=level.value
            ).filter(
                SenegalAdminBoundary.offer_count >= min_offers
            ).all()
            
            if not boundaries:
                logger.warning(f"Aucune limite avec {min_offers}+ offres pour {level.value}")
            
            # Construction du FeatureCollection
            features = []
            for b in boundaries:
                # geojson est stocké comme dict dans PostgreSQL (JSONB)
                geometry = b.geojson if isinstance(b.geojson, dict) else {}
                
                features.append({
                    "type": "Feature",
                    "properties": {
                        "name": b.name,
                        "level": b.level,
                        "offer_count": b.offer_count,
                        "centroid": b.centroid,  # Pour centroid clustering
                    },
                    "geometry": geometry,
                })
            
            # Récupère les offres (limité pour performance)
            offres = db.query(
                OffreEmploiBrute.id,
                OffreEmploiBrute.title,
                OffreEmploiBrute.location,
                OffreEmploiBrute.contract_type,
                SenegalAdminBoundary.name.label("boundary_name")
            ).join(
                SenegalAdminBoundary,
                OffreEmploiBrute.admin_boundary_id == SenegalAdminBoundary.id
            ).filter(
                SenegalAdminBoundary.level == level.value,
                SenegalAdminBoundary.offer_count >= min_offers
            ).limit(500).all()  # ⚠️ Limite pour éviter timeout
            
            return ChoroplethResponse(
                type="FeatureCollection",
                features=features,
                offers=[
                    OfferGeoJSON(
                        id=str(o.id),
                        title=o.title,
                        location=o.location,
                        contract=o.contract_type,
                        boundary=o.boundary_name,
                    ) for o in offres
                ],
                total_boundaries=len(boundaries),
                total_offers=sum(b.offer_count for b in boundaries),
            )
            
        except Exception as e:
            logger.exception(f"❌ Erreur génération carte {level.value}")
            raise AppError(
                message="Erreur de génération de la carte",
                context={"level": level.value, "error": str(e)},
                status_code=500,
            )