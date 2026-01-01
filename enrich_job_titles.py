#!/usr/bin/env python3
"""
Script pour enrichir les titres de poste des offres d'emploi existantes.
"""

import sys
import os
sys.path.append('/home/cardan/Documents/Stage_ansd_emploi/backend_app_stage_ansd')

from app.database import SessionLocal
from app.services.job_service import JobService
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    """Enrichit les titres de poste pour toutes les offres."""
    db = SessionLocal()
    try:
        job_service = JobService()
        enriched_count = job_service.enrich_all_jobs_titles(db)
        logger.info(f"✅ Enrichissement terminé : {enriched_count} offres traitées")
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'enrichissement : {e}")
    finally:
        db.close()

if __name__ == "__main__":
    main()