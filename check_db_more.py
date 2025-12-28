import os
from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql://neondb_owner:npg_dMZCO35gNoeP@ep-long-resonance-a4y4jpe4-pooler.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

engine = create_engine(DATABASE_URL)

def check_table(table_name, columns):
    with engine.connect() as conn:
        print(f"Checking table {table_name}...")
        for col, col_type in columns:
            result = conn.execute(text(f"SELECT column_name FROM information_schema.columns WHERE table_name='{table_name}' AND column_name='{col}'"))
            if not result.fetchone():
                print(f"Column {col} missing in {table_name}. Adding it...")
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col} {col_type}"))
                conn.commit()
                print(f"Column {col} added successfully.")
            else:
                print(f"Column {col} already exists.")

if __name__ == "__main__":
    try:
        # OffreEmploiBrute
        check_table("offres_emploi_brutes", [
            ("recruiter_id", "UUID"),
            ("company_id", "UUID")
        ])
    except Exception as e:
        print(f"Error: {e}")
