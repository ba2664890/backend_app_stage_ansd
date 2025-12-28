import os
from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql://neondb_owner:npg_dMZCO35gNoeP@ep-long-resonance-a4y4jpe4-pooler.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

engine = create_engine(DATABASE_URL)

def check_table(table_name):
    with engine.connect() as conn:
        print(f"Checking table {table_name}...")
        result = conn.execute(text(f"SELECT column_name FROM information_schema.columns WHERE table_name='{table_name}'"))
        columns = [row[0] for row in result.fetchall()]
        print(f"Columns in {table_name}: {columns}")

if __name__ == "__main__":
    try:
        check_table("offres_emploi_brutes")
    except Exception as e:
        print(f"Error: {e}")
