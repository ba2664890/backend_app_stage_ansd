import sqlalchemy
from sqlalchemy import create_engine, text
import os

# URL de la DB extraite de config.py
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://neondb_owner:npg_dMZCO35gNoeP@ep-long-resonance-a4y4jpe4-pooler.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require")

def migrate():
    print("Connecting to database...")
    try:
        engine = create_engine(DATABASE_URL)
        
        with engine.connect() as connection:
            # 1. Ajouter la colonne role si elle n'existe pas
            print("Checking if 'role' column exists in 'users' table...")
            try:
                # Tentative de lecture de la colonne
                connection.execute(text("SELECT role FROM users LIMIT 1"))
                print("'role' column already exists.")
            except Exception:
                print("Column 'role' missing or error reading it. Attempting to add it...")
                # Postgres spécifique pour rollback implicite en cas d'erreur dans la transaction
                trans = connection.begin() 
                try:
                    connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'candidate'"))
                    trans.commit()
                    print("Column 'role' added successfully.")
                except Exception as e:
                    trans.rollback()
                    print(f"Error adding column: {e}")
                    raise e

            # 2. Mettre à jour les utilisateurs existants
            print("Updating existing users roles...")
            trans = connection.begin()
            try:
                # Admins (Emails contenant 'admin')
                result_admin = connection.execute(text("UPDATE users SET role = 'admin' WHERE email LIKE '%admin%'"))
                print(f"Updated potential admins based on email.")
                
                # Recruteurs (Utilisateurs dans la table recruiters)
                # Vérifier d'abord si la table recruiters existe pour éviter erreur
                try:
                    connection.execute(text("SELECT 1 FROM recruiters LIMIT 1"))
                    result_recruiter = connection.execute(text("UPDATE users SET role = 'recruiter' WHERE id IN (SELECT user_id FROM recruiters)"))
                    print(f"Updated recruiters based on recruiters table.")
                except Exception:
                    print("Table 'recruiters' not found or empty, skipping recruiter update.")

                # RH (Emails contenant 'rh' ou 'hr')
                result_hr = connection.execute(text("UPDATE users SET role = 'hr_manager' WHERE (email LIKE '%hr%' OR email LIKE '%rh%') AND role != 'admin' AND role != 'recruiter'"))
                print(f"Updated potential HR managers based on email.")

                # Default 'candidate' for everyone else (NULL roles)
                result_candidate = connection.execute(text("UPDATE users SET role = 'candidate' WHERE role IS NULL"))
                print(f"Set default 'candidate' role for remaining users.")
                
                trans.commit()
                print("Migration data updated successfully!")
                
            except Exception as e:
                trans.rollback()
                print(f"Error updating data: {e}")
                raise e
                
    except Exception as e:
        print(f"Global Error: {e}")

if __name__ == "__main__":
    migrate()
