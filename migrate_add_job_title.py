#!/usr/bin/env python3
"""
Migration pour ajouter la colonne extracted_job_title à offres_emploi_enrichies.
"""

import os
from sqlalchemy import create_engine, text

# Utiliser la même URL que dans config.py
DATABASE_URL = "postgresql://neondb_owner:npg_dMZCO35gNoeP@ep-long-resonance-a4y4jpe4-pooler.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

engine = create_engine(DATABASE_URL)

def migrate():
    with engine.connect() as conn:
        print("Migration: Ajout de extracted_job_title...")

        # Vérifier si la colonne existe déjà
        res = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name='offres_emploi_enrichies'
            AND column_name='extracted_job_title'
        """))
        if res.fetchone():
            print("✅ La colonne extracted_job_title existe déjà")
            return

        # Ajouter la colonne
        print("Ajout de la colonne extracted_job_title...")
        conn.execute(text("""
            ALTER TABLE offres_emploi_enrichies
            ADD COLUMN extracted_job_title VARCHAR(255)
        """))
        conn.commit()

        print("✅ Migration terminée")

if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        print(f"❌ Erreur: {e}")