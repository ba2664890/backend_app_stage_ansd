import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql://neondb_owner:npg_dMZCO35gNoeP@ep-long-resonance-a4y4jpe4-pooler.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
engine = create_engine(DATABASE_URL)

with engine.begin() as conn:
    cols = [
        "gender VARCHAR(50)",
        "date_of_birth VARCHAR(50)",
        "school_name VARCHAR(255)",
        "school_level VARCHAR(100)",
        "school_field VARCHAR(255)",
        "school_region VARCHAR(100)",
        "orientation_goal VARCHAR(255)",
        "interests VARCHAR[]",
        "university VARCHAR(255)",
        "study_level VARCHAR(100)",
        "study_domain VARCHAR(255)",
        "study_year VARCHAR(100)",
        "is_alternance BOOLEAN DEFAULT FALSE",
        "internship_count INTEGER",
        "seeking_type VARCHAR(100)",
        "key_skills VARCHAR[]",
        "informal_activity VARCHAR(255)",
        "informal_sector VARCHAR(255)",
        "spoken_languages VARCHAR[]",
        "school_level_reached VARCHAR(100)",
        "informal_goal VARCHAR(255)",
        "practical_skills TEXT"
    ]
    for col in cols:
        try:
            col_name = col.split()[0]
            conn.execute(text(f"ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS {col}"))
            print(f"Added column {col_name}")
        except Exception as e:
            print(f"Error adding {col_name}: {e}")
print("Done")
