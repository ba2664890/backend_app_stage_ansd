"""
Routes API pour la gestion des recruteurs.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from ..database import get_db
from ..models.api_models import (
    RecruiterCreate,
    RecruiterResponse,
    RecruiterWithCompanyResponse,
    PaginatedResponse
)
from ..services.recruiter_service import RecruiterService
from ..utils.auth import get_current_user

router = APIRouter(prefix="/api/v1/recruiters", tags=["recruiters"])
recruiter_service = RecruiterService()


@router.post("", response_model=RecruiterResponse, status_code=201)
async def create_recruiter(
    recruiter_data: RecruiterCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Enregistre l'utilisateur actuel comme recruteur pour une entreprise.
    
    **Permissions**: Utilisateur authentifié
    """
    try:
        user_id = current_user.user_id
        recruiter = recruiter_service.create_recruiter(db, user_id, recruiter_data)
        return recruiter
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la création du recruteur: {str(e)}")


@router.get("/me", response_model=RecruiterWithCompanyResponse)
async def get_my_recruiter_profile(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Récupère le profil recruteur de l'utilisateur actuel.
    
    **Permissions**: Utilisateur authentifié
    """
    user_id = current_user.user_id
    recruiter = recruiter_service.get_recruiter_by_user(db, user_id)
    if not recruiter:
        raise HTTPException(status_code=404, detail="Vous n'êtes pas enregistré comme recruteur")
    return recruiter


@router.get("/{recruiter_id}", response_model=RecruiterWithCompanyResponse)
async def get_recruiter(
    recruiter_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Récupère un recruteur par son ID.
    
    **Permissions**: Public
    """
    recruiter = recruiter_service.get_recruiter_by_id(db, recruiter_id)
    if not recruiter:
        raise HTTPException(status_code=404, detail="Recruteur non trouvé")
    return recruiter


@router.delete("/{recruiter_id}", status_code=204)
async def delete_recruiter(
    recruiter_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Supprime un recruteur.
    
    **Permissions**: Utilisateur authentifié (devrait être le recruteur lui-même ou admin)
    
    TODO: Ajouter vérification des permissions
    """
    success = recruiter_service.delete_recruiter(db, recruiter_id)
    if not success:
        raise HTTPException(status_code=404, detail="Recruteur non trouvé")
    return None


# Route pour lister les recruteurs d'une entreprise (dans companies.py ou ici)
@router.get("/company/{company_id}/recruiters", response_model=PaginatedResponse[RecruiterResponse])
async def get_company_recruiters(
    company_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Récupère tous les recruteurs d'une entreprise.
    
    **Permissions**: Public
    """
    try:
        recruiters, total = recruiter_service.get_recruiters_by_company(
            db,
            company_id,
            skip=skip,
            limit=limit
        )
        
        pages = (total + limit - 1) // limit
        page = (skip // limit) + 1
        
        return PaginatedResponse(
            items=recruiters,
            total=total,
            page=page,
            size=limit,
            pages=pages,
            has_next=page < pages,
            has_prev=page > 1
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des recruteurs: {str(e)}")
