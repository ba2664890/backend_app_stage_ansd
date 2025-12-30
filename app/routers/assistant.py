"""
Routes API pour l'assistant RH IA.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
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
from ..services.llm_client import LLMClient
from ..services.rag_service import RAGService
from ..services.recruiter_service import RecruiterService
from ..utils.auth import get_current_user

router = APIRouter(prefix="/api/v1/assistant", tags=["ai-assistant"])


@router.post("/chat", response_model=ChatResponse)
async def chat_with_assistant(
    request: Request,
    chat_request: ChatRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Discuter avec l'assistant RH IA.
    
    **Permissions**: Recruteur
    """
    try:
        # Récupérer les services depuis l'état de l'application
        assistant_service = request.app.state.assistant_service
        recruiter_service = request.app.state.recruiter_service
        
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
    request: Request,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Récupère l'historique des conversations.
    
    **Permissions**: Recruteur
    """
    assistant_service = request.app.state.assistant_service
    recruiter_service = request.app.state.recruiter_service
    
    user_id = current_user.user_id
    recruiter = recruiter_service.get_or_create_recruiter(db, user_id)
    
    if not recruiter:
        raise HTTPException(status_code=403, detail="Recruteur uniquement")
    
    history = assistant_service.get_chat_history(db, recruiter.id, limit)
    return history


@router.post("/generate-job-description", response_model=GenerateJobDescriptionResponse)
async def generate_job_description(
    request: Request,
    job_request: GenerateJobDescriptionRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Génère une description de poste avec l'IA.
    
    **Permissions**: Recruteur
    """
    try:
        assistant_service = request.app.state.assistant_service
        recruiter_service = request.app.state.recruiter_service
        
        user_id = current_user.user_id
        recruiter = recruiter_service.get_or_create_recruiter(db, user_id)
        
        if not recruiter:
            raise HTTPException(status_code=403, detail="Recruteur uniquement")
        
        response = await assistant_service.generate_job_description(db, recruiter.id, job_request)
        return GenerateJobDescriptionResponse(**response)
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur: {str(e)}")


from ..models.database_models import Application

@router.post("/analyze-candidate", response_model=Dict[str, Any])
async def analyze_candidate(
    request: Request,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Analyse un candidat par rapport à une offre avec l'IA.
    
    **Permissions**: Recruteur
    """
    assistant_service = request.app.state.assistant_service
    recruiter_service = request.app.state.recruiter_service
    
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

@router.post("/reindex")
async def reindex_rag_data(
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Re-indexe manuellement les offres d'emploi dans la base vectorielle.
    
    **Permissions**: Admin uniquement (simulé ici par recruteur pour le test)
    """
    # En prod, on vérifierait le rôle admin
    rag_service = request.app.state.rag_service
    
    try:
        rag_service.index_offres_emploi(db)
        return {"success": True, "message": f"Indexation terminée. Base vectorielle contient {rag_service.get_count()} documents."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur d'indexation: {str(e)}")
