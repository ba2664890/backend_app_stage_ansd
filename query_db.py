import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.database_models import RHChatHistory

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db = SessionLocal()

try:
    histories = db.query(RHChatHistory).order_by(RHChatHistory.created_at.desc()).limit(5).all()
    print(f"Found {len(histories)} history entries.")
    for idx, h in enumerate(histories):
        print(f"\n--- Entry {idx} (ID: {h.id}, Created: {h.created_at}) ---")
        print(f"Question: {h.question}")
        print(f"Answer (Length: {len(h.answer) if h.answer else 0}):")
        print(h.answer)
        print("------------------------------------------")
finally:
    db.close()
