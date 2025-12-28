"""
Routes API pour la gestion des candidatures (ATS).
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from ..database import get_db
from ..models.api_models import (
    ApplicationCreate,
    ApplicationResponse,
    ApplicationWithDetailsResponse,
    ApplicationUpdateStatus,
    ApplicationUpdateNotes,
    ApplicationStatusHistoryResponse,
    ApplicationStatsResponse,
    PaginatedResponse
)
from ..services.application_service import ApplicationService
from ..utils.auth import get_current_user

router = APIRouter(prefix="/api/v1/applications", tags=["applications"])
application_service = ApplicationService()


@router.post("", response_model=ApplicationResponse, status_code=201)
async def create_application(
    application_data: ApplicationCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Soumettre une candidature à une offre d'emploi.
    
    **Permissions**: Utilisateur authentifié
    """
    try:
        user_id = current_user.user_id
        application = application_service.create_application(db, user_id, application_data)
        return application
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la création de la candidature: {str(e)}")


@router.get("/me", response_model=PaginatedResponse[ApplicationResponse])
async def get_my_applications(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Récupère toutes les candidatures de l'utilisateur actuel.
    
    **Permissions**: Utilisateur authentifié
    """
    user_id = current_user.user_id
    applications, total = application_service.get_user_applications(db, user_id, skip, limit)
    
    pages = (total + limit - 1) // limit
    page = (skip // limit) + 1
    
    return PaginatedResponse(
        items=applications,
        total=total,
        page=page,
        size=limit,
        pages=pages,
        has_next=page < pages,
        has_prev=page > 1
    )


# Statistique Routes (Static paths must come before variable paths like /{application_id})

@router.get("/stats", response_model=ApplicationStatsResponse)
async def get_application_stats_generic(
    company_id: Optional[UUID] = Query(None),
    job_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Endpoint unique pour les stats (supporte company_id ou job_id).
    """
    if company_id:
        stats = application_service.get_application_stats(db, company_id=company_id)
        return ApplicationStatsResponse(**stats)
    if job_id:
        stats = application_service.get_application_stats(db, job_id=job_id)
        return ApplicationStatsResponse(**stats)
    raise HTTPException(status_code=400, detail="company_id ou job_id requis")


@router.get("/stats/company/{company_id}", response_model=ApplicationStatsResponse)
async def get_company_application_stats(
    company_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Statistiques des candidatures pour une entreprise.
    
    **Permissions**: Recruteur de l'entreprise
    """
    stats = application_service.get_application_stats(db, company_id=company_id)
    return ApplicationStatsResponse(**stats)


@router.get("/stats/job/{job_id}", response_model=ApplicationStatsResponse)
async def get_job_application_stats(
    job_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Statistiques des candidatures pour une offre.
    
    **Permissions**: Recruteur de l'entreprise
    """
    stats = application_service.get_application_stats(db, job_id=job_id)
    return ApplicationStatsResponse(**stats)


# Instance Routes (Variable paths)

@router.get("/{application_id}", response_model=ApplicationResponse)
async def get_application(
    application_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Récupère une candidature par son ID.
    
    **Permissions**: Utilisateur authentifié (candidat ou recruteur de l'entreprise)
    
    TODO: Vérifier que l'utilisateur a le droit de voir cette candidature
    """
    application = application_service.get_application_by_id(db, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Candidature non trouvée")
    return application


@router.put("/{application_id}/status", response_model=ApplicationResponse)
async def update_application_status(
    application_id: UUID,
    status_data: ApplicationUpdateStatus,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Met à jour le statut d'une candidature.
    
    **Permissions**: Recruteur de l'entreprise
    
    TODO: Vérifier que l'utilisateur est recruteur de l'entreprise
    """
    try:
        changed_by = current_user.user_id
        application = application_service.update_status(db, application_id, status_data, changed_by)
        if not application:
            raise HTTPException(status_code=404, detail="Candidature non trouvée")
        return application
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la mise à jour: {str(e)}")


@router.post("/{application_id}/notes", response_model=ApplicationResponse)
async def update_application_notes(
    application_id: UUID,
    notes_data: ApplicationUpdateNotes,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Met à jour les notes RH d'une candidature.
    
    **Permissions**: Recruteur de l'entreprise
    """
    application = application_service.update_notes(db, application_id, notes_data)
    if not application:
        raise HTTPException(status_code=404, detail="Candidature non trouvée")
    return application


@router.get("/{application_id}/history", response_model=List[ApplicationStatusHistoryResponse])
async def get_application_history(
    application_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Récupère l'historique des changements de statut d'une candidature.
    
    **Permissions**: Utilisateur authentifié
    """
    history = application_service.get_application_history(db, application_id)
    return history


@router.post("/{application_id}/withdraw", status_code=204)
async def withdraw_application(
    application_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Retirer une candidature (par le candidat).
    """
    try:
        user_id = current_user.user_id
        application = application_service.withdraw_application(db, application_id, user_id)
        if not application:
            raise HTTPException(status_code=404, detail="Candidature non trouvée")
        return None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# Routes pour les entreprises/recruteurs

@router.get("/company/{company_id}", response_model=PaginatedResponse[ApplicationWithDetailsResponse])
async def get_company_applications(
    company_id: UUID,
    status: Optional[str] = Query(None, description="Filtrer par statut"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Récupère toutes les candidatures d'une entreprise.
    """
    applications, total = application_service.get_company_applications(
        db, company_id, status, skip, limit
    )
    
    pages = (total + limit - 1) // limit
    page = (skip // limit) + 1
    
    return PaginatedResponse(
        items=applications,
        total=total,
        page=page,
        size=limit,
        pages=pages,
        has_next=page < pages,
        has_prev=page > 1
    )


@router.get("/job/{job_id}/all", response_model=PaginatedResponse[ApplicationWithDetailsResponse])
async def get_job_applications(
    job_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Récupère toutes les candidatures pour une offre d'emploi.
    
    **Permissions**: Recruteur de l'entreprise
    """
    applications, total = application_service.get_job_applications(db, job_id, skip, limit)
    
    pages = (total + limit - 1) // limit
    page = (skip // limit) + 1
    
    return PaginatedResponse(
        items=applications,
        total=total,
        page=page,
        size=limit,
        pages=pages,
        has_next=page < pages,
        has_prev=page > 1
    )
