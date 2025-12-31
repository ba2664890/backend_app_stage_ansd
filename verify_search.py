
import sys
import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add parent dir to path
sys.path.append(os.getcwd())

from app.database import SessionLocal
from app.services.job_service import JobService
from app.models.api_models import JobSearchParams

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_fix():
    print("--- Verifying Job Search Fix ---")
    db = SessionLocal()
    try:
        service = JobService()
        
        # Test case: "emploi stage alternance recrutement"
        # Before fix: 0 results (because it looked for the exact phrase)
        # After fix: Should return results containing ANY of those terms
        
        query_str = "emploi stage alternance recrutement"
        params = JobSearchParams(
            skip=0, 
            limit=10, 
            search=query_str
        )
        
        print(f"Searching for: '{query_str}'")
        result = service.search_jobs(db, params)
        
        print(f"Results found: {result.total}")
        
        if result.total > 0:
            print("\nTop 3 matches:")
            for item in result.items[:3]:
                print(f"- {item.title} (Company: {item.company_name})")
            print("\n✅ Verification SUCCESS: 'OR' logic is working.")
        else:
            print("\n⚠️ Verification WARNING: No results found. Database might be empty or terms not present.")
            
            # Double check with a simple known term
            print("Checking simple term 'stage'...")
            params_simple = JobSearchParams(skip=0, limit=10, search="stage")
            res_simple = service.search_jobs(db, params_simple)
            print(f"Results for 'stage': {res_simple.total}")

    except Exception as e:
        print(f"❌ Verification FAILED with error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    verify_fix()
