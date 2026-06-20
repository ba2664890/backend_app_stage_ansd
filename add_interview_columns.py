from sqlalchemy import create_engine, text
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_dMZCO35gNoeP@ep-long-resonance-a4y4jpe4-pooler.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
)

engine = create_engine(DATABASE_URL)

with engine.begin() as conn:
    cols = [
        "interview_type VARCHAR(50)",
        "interview_link VARCHAR(512)",
        "interview_address VARCHAR(512)",
        "interview_instructions TEXT"
    ]
    for col in cols:
        try:
            col_name = col.split()[0]
            conn.execute(text(f"ALTER TABLE applications ADD COLUMN IF NOT EXISTS {col}"))
            print(f"Added column {col_name} to applications table")
        except Exception as e:
            print(f"Error adding {col_name}: {e}")

print("Database update done.")
