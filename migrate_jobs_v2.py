import os
from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql://neondb_owner:npg_dMZCO35gNoeP@ep-long-resonance-a4y4jpe4-pooler.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

engine = create_engine(DATABASE_URL)

def migrate():
    with engine.connect() as conn:
        print("Migrating offres_emploi_brutes...")
        
        # Add remote_type
        print("Checking for remote_type...")
        res = conn.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name='offres_emploi_brutes' AND column_name='remote_type'"))
        if not res.fetchone():
            print("Adding remote_type...")
            conn.execute(text("ALTER TABLE offres_emploi_brutes ADD COLUMN remote_type VARCHAR(50)"))
            conn.commit()
            
        # Add is_urgent
        print("Checking for is_urgent...")
        res = conn.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name='offres_emploi_brutes' AND column_name='is_urgent'"))
        if not res.fetchone():
            print("Adding is_urgent...")
            conn.execute(text("ALTER TABLE offres_emploi_brutes ADD COLUMN is_urgent BOOLEAN DEFAULT FALSE"))
            conn.commit()
            
        # Add languages
        print("Checking for languages...")
        res = conn.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name='offres_emploi_brutes' AND column_name='languages'"))
        if not res.fetchone():
            print("Adding languages...")
            conn.execute(text("ALTER TABLE offres_emploi_brutes ADD COLUMN languages TEXT[]"))
            conn.commit()
            
        # Add benefits
        print("Checking for benefits...")
        res = conn.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name='offres_emploi_brutes' AND column_name='benefits'"))
        if not res.fetchone():
            print("Adding benefits...")
            conn.execute(text("ALTER TABLE offres_emploi_brutes ADD COLUMN benefits TEXT[]"))
            conn.commit()
            
        print("Migration complete.")

if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        print(f"Error: {e}")
