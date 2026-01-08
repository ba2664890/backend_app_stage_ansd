import sys
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ajouter le chemin du projet
sys.path.append(os.getcwd())

from app.services.admin_boundary_importer import AdminBoundaryImporterService
from app.database import SessionLocal

def run_matching():
    db = SessionLocal()
    try:
        importer = AdminBoundaryImporterService()
        
        print("🚀 Démarrage du matching généralisé...")
        
        # 1. Matcher les talents
        stats_talents = importer.match_talents_to_boundaries(db)
        print(f"✅ Talents : {stats_talents['matched']} matchés sur {stats_talents['total_processed']}")
        
        # 2. Matcher les entreprises
        stats_companies = importer.match_companies_to_boundaries(db)
        print(f"✅ Entreprises : {stats_companies['matched']} matchées sur {stats_companies['total_processed']}")
        
        # 3. Matcher les offres (au cas où)
        stats_offers = importer.match_offers_to_boundaries(db)
        print(f"✅ Offres : {stats_offers['matched']} matchées sur {stats_offers['total_processed']}")
        
        print("🎉 Matching terminé avec succès !")
        
    except Exception as e:
        print(f"❌ Erreur lors du matching : {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    run_matching()
