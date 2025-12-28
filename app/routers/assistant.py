"""
Routes API pour l'assistant RH IA.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from uuid import UUID

from ..database import get_db
from ..models.api_models import (
    ChatRequest,
    ChatResponse,
    ChatHistoryResponse,
    GenerateJobDescriptionRequest,
    GenerateJobDescriptionResponse
)
from ..services.rh_assistant_service import RHAssistantService
from ..services.recruiter_service import RecruiterService
from ..utils.auth import get_current_user

router = APIRouter(prefix="/api/v1/assistant", tags=["ai-assistant"])
assistant_service = RHAssistantService()
recruiter_service = RecruiterService()


@router.post("/chat", response_model=ChatResponse)
async def chat_with_assistant(
    chat_request: ChatRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Discuter avec l'assistant RH IA.
    
    **Permissions**: Recruteur
    """
    try:
        # Vérifier que l'utilisateur est un recruteur
        user_id = current_user.user_id
        recruiter = recruiter_service.get_or_create_recruiter(db, user_id)
        
        if not recruiter:
            raise HTTPException(
                status_code=403,
                detail="Vous devez être recruteur pour utiliser l'assistant RH"
            )
        
        response = await assistant_service.chat(db, recruiter.id, chat_request)
        return ChatResponse(**response)
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur: {str(e)}")


@router.get("/history", response_model=List[ChatHistoryResponse])
async def get_chat_history(
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Récupère l'historique des conversations.
    
    **Permissions**: Recruteur
    """
    user_id = current_user.user_id
    recruiter = recruiter_service.get_or_create_recruiter(db, user_id)
    
    if not recruiter:
        raise HTTPException(status_code=403, detail="Recruteur uniquement")
    
    history = assistant_service.get_chat_history(db, recruiter.id, limit)
    return history


@router.post("/generate-job-description", response_model=GenerateJobDescriptionResponse)
async def generate_job_description(
    request: GenerateJobDescriptionRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Génère une description de poste avec l'IA.
    
    **Permissions**: Recruteur
    """
    try:
        user_id = current_user.user_id
        recruiter = recruiter_service.get_or_create_recruiter(db, user_id)
        
        if not recruiter:
            raise HTTPException(status_code=403, detail="Recruteur uniquement")
        
        response = await assistant_service.generate_job_description(db, recruiter.id, request)
        return GenerateJobDescriptionResponse(**response)
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur: {str(e)}")


from ..models.database_models import Application

@router.post("/analyze-candidate", response_model=Dict[str, Any])
async def analyze_candidate(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Analyse un candidat par rapport à une offre avec l'IA.
    
    **Permissions**: Recruteur
    """
    user_id = current_user.user_id
    recruiter = recruiter_service.get_or_create_recruiter(db, user_id)
    
    if not recruiter:
        raise HTTPException(status_code=403, detail="Recruteur uniquement")
        
    application_id = payload.get("application_id")
    if not application_id:
        raise HTTPException(status_code=400, detail="application_id requis")
        
    application = db.query(Application).filter(Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Candidature non trouvée")
    
    # Appeler le service avec les IDs extraits
    # Note: application.user_id est l'ID du candidat
    analysis = await assistant_service.analyze_candidate(
        db, 
        recruiter.id, 
        application.user_id, 
        application.job_id
    )
    return analysis
