import sys
import os
import logging

# Configurer le logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ajouter le chemin du projet au PYTHONPATH
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from app.database import SessionLocal
    from app.models.database_models import OffreEmploiBrute, OffreEmploiEnrichie
    from app.utils.job_title_extraction import extract_job_title
except ImportError as e:
    logger.error(f"Erreur d'import : {e}")
    sys.exit(1)

def populate():
    db = SessionLocal()
    try:
        # Récupérer les offres qui n'ont pas encore de titre extrait
        query = db.query(OffreEmploiEnrichie).filter(
            OffreEmploiEnrichie.extracted_job_title.is_(None)
        )
        
        enrichies = query.all()
        total_to_process = len(enrichies)
        logger.info(f"Trouvé {total_to_process} enregistrements à traiter.")
        
        if total_to_process == 0:
            logger.info("Rien à traiter.")
            return

        count = 0
        for enrichie in enrichies:
            brute = enrichie.offre_brute
            if brute and brute.title:
                try:
                    job_title = extract_job_title(brute.title)
                    if job_title:
                        enrichie.extracted_job_title = job_title
                        count += 1
                except Exception as e:
                    logger.warning(f"Erreur d'extraction pour l'offre {enrichie.id}: {e}")
            
            # Commit par lots de 100
            if count % 100 == 0 and count > 0:
                db.commit()
                logger.info(f"Progression : {count}/{total_to_process} enregistrements mis à jour...")
        
        db.commit()
        logger.info(f"Succès : {count} titres de poste ont été populés.")
        
    except Exception as e:
        logger.error(f"Erreur lors de la population : {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    populate()
