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

from app.models.database_models import SenegalAdminBoundary
from app.models.api_models import AdminBoundaryOut
from app.core.exceptions import AppError, NotFoundError

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
            
            return [AdminBoundaryOut.model_validate(b) for b in boundaries]
            
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
    
    @with_network_retry
    def refresh_offer_counts(self, db: Session, level: str) -> Dict[str, Any]:
        """
        Recalcule les compteurs d'offres par intersection géospatiale.
        Opération longue => timeout élevé.
        
        Returns:
            dict avec statut et nb de lignes mises à jour
        """
        self.postgis_manager.ensure_postgis(db)
        
        try:
            # Transaction avec lock progressif
            with db.begin():
                # Désactive les indexes temporairement pour perf
                db.execute(text("UPDATE senegal_admin_boundaries SET offer_count = 0 WHERE level = :level"), {"level": level})
                
                # Requête d'intersection (peut être très lente)
                sql = """
                WITH counts AS (
                    SELECT 
                        ab.id,
                        COUNT(o.id) AS nb_offres
                    FROM senegal_admin_boundaries ab
                    JOIN offre_emploi_brute o ON ST_Contains(
                        ST_SetSRID(ST_GeomFromGeoJSON(ab.geojson->>'geometry'), 4326),
                        ST_SetSRID(ST_MakePoint(o.lng, o.lat), 4326)
                    )
                    WHERE ab.level = :level
                    GROUP BY ab.id
                )
                UPDATE senegal_admin_boundaries ab
                SET 
                    offer_count = COALESCE(c.nb_offres, 0),
                    updated_at = NOW()
                FROM counts c
                WHERE c.id = ab.id;
                """
                
                result = db.execute(text(sql), {"level": level})
                db.commit()
                
                updated = result.rowcount
                logger.info(f"✅ {updated} limites mises à jour pour level='{level}'")
                
                return {"status": "success", "updated_rows": updated, "level": level}
                
        except OperationalError as e:
            db.rollback()
            logger.error(f"❌ Timeout ou erreur réseau lors du refresh : {e}")
            raise AppError(
                message="Le recalcul a échoué (timeout réseau)",
                context={"operation": "refresh_offer_counts", "network_error": True},
                status_code=503,
            ) from e
        
        except Exception as e:
            db.rollback()
            logger.exception("❌ Erreur inattendue lors du refresh")
            raise AppError(
                message="Échec du recalcul des compteurs",
                context={"error_type": type(e).__name__, "level": level},
                status_code=500,
            ) from e
    
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
        
        return AdminBoundaryOut.model_validate(boundary)