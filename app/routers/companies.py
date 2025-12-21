"""
Routes API pour la gestion des entreprises.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from ..database import get_db
from ..models.api_models import (
    CompanyCreate,
    CompanyUpdate,
    CompanyResponse,
    PaginatedResponse
)
from ..services.company_service import CompanyService
from ..utils.auth import get_current_user

router = APIRouter(prefix="/api/v1/companies", tags=["companies"])
company_service = CompanyService()


@router.post("", response_model=CompanyResponse, status_code=201)
async def create_company(
    company_data: CompanyCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Crée une nouvelle entreprise.
    
    **Permissions**: Utilisateur authentifié
    """
    try:
        company = company_service.create_company(db, company_data)
        return company
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la création de l'entreprise: {str(e)}")


@router.get("", response_model=PaginatedResponse[CompanyResponse])
async def get_companies(
    skip: int = Query(0, ge=0, description="Nombre d'entreprises à ignorer"),
    limit: int = Query(20, ge=1, le=100, description="Nombre d'entreprises à retourner"),
    sector: Optional[str] = Query(None, description="Filtrer par secteur"),
    is_verified: Optional[bool] = Query(None, description="Filtrer par statut de vérification"),
    search: Optional[str] = Query(None, description="Recherche textuelle"),
    db: Session = Depends(get_db)
):
    """
    Récupère une liste paginée d'entreprises avec filtres.
    
    **Permissions**: Public
    """
    try:
        companies, total = company_service.get_companies(
            db,
            skip=skip,
            limit=limit,
            sector=sector,
            is_verified=is_verified,
            search=search
        )
        
        # Calculer le nombre de pages
        pages = (total + limit - 1) // limit
        page = (skip // limit) + 1
        
        return PaginatedResponse(
            items=companies,
            total=total,
            page=page,
            size=limit,
            pages=pages,
            has_next=page < pages,
            has_prev=page > 1
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des entreprises: {str(e)}")


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(
    company_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Récupère une entreprise par son ID.
    
    **Permissions**: Public
    """
    company = company_service.get_company_by_id(db, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Entreprise non trouvée")
    return company


@router.put("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: UUID,
    company_data: CompanyUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Met à jour une entreprise.
    
    **Permissions**: Utilisateur authentifié (devrait être recruteur de l'entreprise)
    
    TODO: Ajouter vérification que l'utilisateur est recruteur de cette entreprise
    """
    try:
        company = company_service.update_company(db, company_id, company_data)
        if not company:
            raise HTTPException(status_code=404, detail="Entreprise non trouvée")
        return company
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la mise à jour: {str(e)}")


@router.post("/{company_id}/verify", response_model=CompanyResponse)
async def verify_company(
    company_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Vérifie une entreprise (marque is_verified = True).
    
    **Permissions**: Utilisateur authentifié (devrait être admin)
    
    TODO: Ajouter vérification que l'utilisateur est admin
    """
    company = company_service.verify_company(db, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Entreprise non trouvée")
    return company


@router.delete("/{company_id}", status_code=204)
async def delete_company(
    company_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Supprime une entreprise.
    
    **Permissions**: Utilisateur authentifié (devrait être admin)
    
    TODO: Ajouter vérification que l'utilisateur est admin
    """
    success = company_service.delete_company(db, company_id)
    if not success:
        raise HTTPException(status_code=404, detail="Entreprise non trouvée")
    return None
