"""
Module de vérification et d'installation automatique de PostGIS.
S'intègre dans le lifespan de l'application.
"""

import logging
import time
from typing import Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, ProgrammingError, DBAPIError
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)


class PostGISManager:
    """
    Gère l'initialisation de PostGIS avec retry intelligent.
    Optimisé pour Neon Tech et autres cloud DB.
    """
    
    def __init__(self, max_retries: int = 3, retry_delay: float = 2.0):
        self.max_retries = max_retries
        self.retry_delay = retry_delay
    
    def ensure_postgis(self, db: Session) -> bool:
        """
        Vérifie et active PostGIS. Retourne True si succès.
        Loggue clairement chaque étape pour le débogage.
        """
        logger.info("🔍 Vérification de PostGIS...")
        
        for attempt in range(1, self.max_retries + 1):
            try:
                # Vérifie si l'extension existe déjà
                result = db.execute(
                    text("SELECT extname FROM pg_extension WHERE extname = 'postgis'")
                ).scalar()
                
                if result == "postgis":
                    # Récupère la version pour les logs
                    version = db.execute(text("SELECT postgis_version()")).scalar()
                    logger.info(f"✅ PostGIS déjà installé (v{version})")
                    return True
                
                # Tentative d'installation
                logger.warning(f"⚠️ PostGIS absent, tentative d'installation (#{attempt})...")
                db.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
                db.commit()
                
                # Vérifie après installation
                version = db.execute(text("SELECT postgis_version()")).scalar()
                logger.info(f"✅ PostGIS installé avec succès (v{version})")
                return True
                
            except ProgrammingError as e:
                # Erreur de permission (cloud restreint)
                db.rollback()
                logger.warning(
                    f"🚫 Permission refusée pour installer PostGIS (tentative {attempt}/{self.max_retries})"
                )
                
                if attempt == self.max_retries:
                    logger.error("❌ Impossible d'installer PostGIS après tous les essais")
                    logger.error("💡 Solution : exécutez manuellement : CREATE EXTENSION postgis;")
                    raise AppError(
                        message="PostGIS requis mais non installable automatiquement",
                        context={
                            "solution": "CREATE EXTENSION postgis; (nécessite superuser)",
                            "cloud_provider": "Neon Tech (probable)",
                        },
                        status_code=500,
                    ) from e
                
                time.sleep(self.retry_delay * attempt)  # Backoff exponentiel
                
            except OperationalError as e:
                # Problème réseau (typique avec Neon)
                db.rollback()
                logger.warning(
                    f"🌐 Problème réseau lors de la vérif PostGIS (tentative {attempt}/{self.max_retries})"
                )
                
                if attempt == self.max_retries:
                    logger.error("❌ Erreur réseau persistante")
                    raise AppError(
                        message="Impossible de joindre la base de données (network)",
                        context={"network_error": True, "attempts": attempt},
                        status_code=503,
                    ) from e
                
                time.sleep(self.retry_delay * attempt)
                
            except Exception as e:
                # Erreur inattendue
                db.rollback()
                logger.exception(f"❌ Erreur inattendue lors de l'init PostGIS (tentative {attempt})")
                
                if attempt == self.max_retries:
                    raise AppError(
                        message="Échec de l'initialisation de PostGIS",
                        context={"error_type": type(e).__name__},
                        status_code=500,
                    ) from e
                
                time.sleep(self.retry_delay)
        
        return False  # Ne devrait jamais arriver ici à cause des raise
    
    def check_postgis_availability(self, db: Session) -> bool:
        """
        Vériﬁcation rapide sans tentative d'installation.
        Utile pour les environnements où on n'a pas les droits.
        """
        try:
            version = db.execute(text("SELECT postgis_version()")).scalar()
            logger.info(f"✅ PostGIS disponible (v{version})")
            return True
        except Exception as e:
            logger.warning(f"⚠️ PostGIS non disponible : {e}")
            return False