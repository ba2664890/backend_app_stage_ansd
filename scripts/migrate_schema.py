import sys
import os
from sqlalchemy import text

# Ajouter le chemin du projet
sys.path.append(os.getcwd())

from app.database import engine

def migrate():
    print("🚀 Démarrage de la migration de la base de données...")
    
    commands = [
        # Ajouter la colonne à user_profiles
        "ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS admin_boundary_id INTEGER;",
        "ALTER TABLE user_profiles ADD CONSTRAINT fk_user_profiles_admin_boundary FOREIGN KEY (admin_boundary_id) REFERENCES senegal_admin_boundaries(id);",
        "CREATE INDEX IF NOT EXISTS idx_user_profiles_admin_boundary_id ON user_profiles(admin_boundary_id);",
        
        # Ajouter la colonne à companies
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS admin_boundary_id INTEGER;",
        "ALTER TABLE companies ADD CONSTRAINT fk_companies_admin_boundary FOREIGN KEY (admin_boundary_id) REFERENCES senegal_admin_boundaries(id);",
        "CREATE INDEX IF NOT EXISTS idx_companies_admin_boundary_id ON companies(admin_boundary_id);"
    ]
    
    with engine.connect() as conn:
        for cmd in commands:
            try:
                print(f"Executing: {cmd}")
                conn.execute(text(cmd))
                conn.commit()
                print("✅ Succès")
            except Exception as e:
                print(f"⚠️ Erreur ou déjà existant : {e}")
                conn.rollback()

    print("🎉 Migration terminée !")

if __name__ == "__main__":
    migrate()
