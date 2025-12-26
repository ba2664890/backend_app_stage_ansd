from app.database import SessionLocal, engine
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check():
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'offres_emploi_brutes';"))
            columns = [row[0] for row in result]
            logger.info(f"Columns in offres_emploi_brutes: {columns}")
            
            result = connection.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'user_saved_jobs';"))
            columns = [row[0] for row in result]
            logger.info(f"Columns in user_saved_jobs: {columns}")
    except Exception as e:
        logger.error(f"Error: {e}")

if __name__ == '__main__':
    check()
