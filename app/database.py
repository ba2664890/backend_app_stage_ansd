from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import os
from typing import Generator

# ✅ Configuration de la base de données PostgreSQL
DATABASE_URL = os.getenv(
    "DATABASE_URL" ,)

# ✅ Créer l'engine SQLAlchemy (sans StaticPool)
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,     # Vérifie la validité avant chaque requête
    pool_size=10,           # Taille du pool de connexions
    max_overflow=20,        # Connexions supplémentaires temporaires
    pool_recycle=1800,      # Recycle les connexions toutes les 30 minutes
    echo=False,
)

# ✅ Créer la session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ✅ Base pour les modèles ORM
Base = declarative_base()


# ✅ Fonction de dépendance FastAPI pour obtenir une session DB
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
