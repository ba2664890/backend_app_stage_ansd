from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List, Dict, Any, Optional

from ..database import get_db
from ..models.api_models import JobOfferResponse
from ..services.user_service import UserService
from ..services.job_service import JobService
from ..utils.auth import get_current_user

router = APIRouter(prefix="/api/v1/users", tags=["users"])
user_service = UserService()
job_service = JobService()

# ==================== SETTINGS & ACCOUNT ====================

@router.get("/settings", response_model=Dict[str, Any])
async def get_user_settings(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Récupère les paramètres de l'utilisateur.
    """
    # Note: Implémentation simplifiée, à connecter à un vrai modèle de settings si existant
    return user_service.get_settings(db, current_user.user_id)

@router.put("/settings", response_model=Dict[str, Any])
async def update_user_settings(
    settings: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Met à jour les paramètres de l'utilisateur.
    """
    return user_service.update_settings(db, current_user.user_id, settings)

@router.delete("/account", status_code=204)
async def delete_user_account(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Supprime le compte utilisateur.
    """
    success = user_service.delete_user(db, current_user.user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    return None

@router.get("/export")
async def export_user_data(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Exporte toutes les données de l'utilisateur (GDPR).
    """
    # TODO: Implémenter le service d'export réel
    return {"message": "Export feature not fully implemented yet", "user_id": str(current_user.id)}

# ==================== FAVORITES ====================
# Alias pour /api/v1/jobs/saved, utilisé par favoritesService.ts

@router.get("/favorites")
async def get_favorites(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Récupère les offres favorites."""
    return job_service.get_saved_jobs(db, current_user.id) # user.id ou user.user_id selon le model

@router.post("/favorites")
async def add_favorite(
    payload: Dict[str, Any], # { "job_id": "..." }
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Ajoute une offre aux favoris."""
    job_id = payload.get("job_id")
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id requis")
    
    try:
        job_service.save_job(db, current_user.id, job_id)
        return {"message": "Job added to favorites"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/favorites/{job_id}", status_code=204)
async def remove_favorite(
    job_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Supprime une offre des favoris."""
    try:
        # TODO: Ajouter remove_saved_job dans JobService si inexistant
        # Pour l'instant on suppose qu'il faut l'implementer
        # job_service.remove_saved_job(db, current_user.id, job_id)
        pass 
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return None
