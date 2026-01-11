from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from uuid import UUID

from ..database import get_db
from ..models.api_models import (
    JobCreate, JobOfferResponse, RewardResponse, 
    UserRewardResponse, AdvertiserStatsResponse
)
from ..utils.auth import get_current_user
from ..services.advertiser_service import AdvertiserService
from ..services.job_service import JobService
from ..services.llm_client import LLMClient
from ..services.file_service import FileService

router = APIRouter(
    prefix="/api/v1/advertiser",
    tags=["advertiser"]
)

def get_advertiser_service():
    """Injecteur de dépendance pour AdvertiserService."""
    job_service = JobService()
    llm_client = LLMClient()
    file_service = FileService()
    return AdvertiserService(job_service, llm_client, file_service)

@router.post("/jobs/form", response_model=JobOfferResponse)
async def post_job_form(
    job_data: JobCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: AdvertiserService = Depends(get_advertiser_service)
):
    """Publie une offre d'emploi via un formulaire standard."""
    return await service.post_job_form(db, current_user.user_id, job_data)

@router.post("/jobs/upload", response_model=JobOfferResponse)
async def post_job_file(
    file: UploadFile = File(...),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: AdvertiserService = Depends(get_advertiser_service)
):
    """Publie une offre en extrayant les données d'un fichier (PDF, Word)."""
    import logging
    log = logging.getLogger(__name__)
    
    try:
        file_path = await service.file_service.save_upload_file(file)
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Erreur sauvegarde fichier: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de la sauvegarde du fichier.")
    
    try:
        result = await service.post_job_file(db, current_user.user_id, file_path)
        return result
    except ValueError as e:
        # Erreurs de validation (titre manquant, extraction échouée, etc.)
        log.warning(f"Validation échouée pour upload annonceur: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Erreur inattendue upload annonceur: {type(e).__name__}: {e}", exc_info=True)
        # On renvoie le détail de l'erreur pour débugger sur Railway (en prod on masquerait normalement)
        raise HTTPException(status_code=500, detail=f"Erreur interne ({type(e).__name__}): {str(e)}")
    finally:
        await service.file_service.cleanup_file(file_path)

@router.get("/rewards", response_model=List[RewardResponse])
def list_rewards(
    db: Session = Depends(get_db),
    service: AdvertiserService = Depends(get_advertiser_service)
):
    """Liste les récompenses disponibles dans le catalogue."""
    return service.list_rewards(db)

@router.post("/rewards/claim/{reward_id}", response_model=UserRewardResponse)
def claim_reward(
    reward_id: UUID,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: AdvertiserService = Depends(get_advertiser_service)
):
    """Réclame une récompense."""
    try:
        return service.claim_reward(db, current_user.user_id, reward_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/stats", response_model=AdvertiserStatsResponse)
def get_stats(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: AdvertiserService = Depends(get_advertiser_service)
):
    """Récupère les statistiques de points et l'historique de l'annonceur."""
    return service.get_stats(db, current_user.user_id)
