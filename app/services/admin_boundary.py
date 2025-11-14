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
            # ✅ PAS de db.begin() - utilise la session existante
            logger.info(f"🔄 Refresh des compteurs pour level={level}")
            
            # Récupérer les limites
            boundaries = db.query(SenegalAdminBoundary).filter_by(level=level).all()
            
            if not boundaries:
                logger.warning(f"Aucune limite trouvée pour level='{level}'")
                return {"status": "success", "updated_rows": 0, "level": level}
            
            total_updated = 0
            for boundary in boundaries:
                # Compter les offres pour cette limite
                count = db.query(OffreEmploiBrute).filter(
                    OffreEmploiBrute.admin_boundary_id == boundary.id
                ).count()
                
                # Mettre à jour si nécessaire
                if boundary.offer_count != count:
                    boundary.offer_count = count
                    total_updated += 1
            
            # ✅ Commit explicite seulement si des changements ont été faits
            if total_updated > 0:
                db.commit()
                logger.info(f"✅ {total_updated} compteurs mis à jour pour level={level}")
            else:
                logger.info(f"ℹ️ Aucune mise à jour nécessaire pour level={level}")
                
            return {
                "status": "success", 
                "updated_rows": total_updated, 
                "level": level,
                "total_boundaries": len(boundaries)
            }
                
        except OperationalError as e:
            # ✅ Rollback en cas d'erreur
            db.rollback()
            logger.error(f"❌ Timeout ou erreur réseau lors du refresh : {e}")
            raise AppError(
                message="Le recalcul a échoué (timeout réseau)",
                context={"operation": "refresh_offer_counts", "network_error": True},
                status_code=503,
            ) from e
        
        except Exception as e:
            # ✅ Rollback en cas d'erreur
            db.rollback()
            logger.exception("❌ Erreur inattendue lors du refresh")
            raise AppError(
                message="Échec du recalcul des compteurs",
                context={"error_type": type(e).__name__, "level": level},
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