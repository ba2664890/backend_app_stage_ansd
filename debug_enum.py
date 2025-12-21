import sys
import os
sys.path.append('/home/cardan/Documents/Stage_ansd_emploi/backend_app_stage_ansd')

from app.models.database_models import UserRole
from app.database import SessionLocal
from sqlalchemy import text

print("--- ENUM DEFINITION ---")
for e in UserRole:
    print(f"Name: {e.name}, Value: {e.value!r}, Type: {type(e.value)}")

print("\n--- LOOKUP TESTS ---")
try:
    print(f"UserRole('candidate'): {UserRole('candidate')}")
except Exception as e:
    print(f"UserRole('candidate') Error: {e}")

try:
    print(f"UserRole('CANDIDATE'): {UserRole('CANDIDATE')}")
except Exception as e:
    print(f"UserRole('CANDIDATE') Error: {e}")

print("\n--- DB CONTENT ---")
db = SessionLocal()
try:
    # Check actual string values in DB
    # We cast to text to avoid automatic SQLAlchemy conversion if possible, or just raw select
    result = db.execute(text("SELECT role::text FROM users LIMIT 5")).fetchall()
    print("Raw roles in DB:", result)
    
    # Check PostgreSQL Enum definition
    enum_def = db.execute(text("SELECT unnest(enum_range(NULL::user_role_enum))")).fetchall()
    print("Postgres Enum Definition:", enum_def)
    
except Exception as e:
    print(f"DB Error: {e}")
finally:
    db.close()
