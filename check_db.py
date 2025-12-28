import os
from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql://neondb_owner:npg_dMZCO35gNoeP@ep-long-resonance-a4y4jpe4-pooler.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

engine = create_engine(DATABASE_URL)

def check_and_fix():
    with engine.connect() as conn:
        print("Checking for match_score in applications table...")
        result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='applications' AND column_name='match_score'"))
        if not result.fetchone():
            print("Column match_score missing. Adding it...")
            conn.execute(text("ALTER TABLE applications ADD COLUMN match_score FLOAT"))
            conn.commit()
            print("Column match_score added successfully.")
        else:
            print("Column match_score already exists.")

if __name__ == "__main__":
    try:
        check_and_fix()
    except Exception as e:
        print(f"Error: {e}")
