"""
Routes API pour la gestion des compétences et GEPP.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from uuid import UUID

from ..database import get_db
from ..models.api_models import CompanySkillNeedCreate, CompanySkillNeedResponse, SkillGapResponse
from ..services.skill_gap_service import SkillGapService
from ..utils.auth import get_current_user

router = APIRouter(prefix="/api/v1/skills", tags=["skills-gepp"])
skill_service = SkillGapService()


@router.post("/companies/{company_id}/needs", response_model=CompanySkillNeedResponse, status_code=201)
async def add_company_skill_need(
    company_id: UUID,
    skill_data: CompanySkillNeedCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Ajoute un besoin en compétence pour une entreprise."""
    try:
        skill_need = skill_service.add_skill_need(db, company_id, skill_data)
        return skill_need
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies/{company_id}/needs", response_model=List[CompanySkillNeedResponse])
async def get_company_skill_needs(
    company_id: UUID,
    db: Session = Depends(get_db)
):
    """Récupère les besoins en compétences d'une entreprise."""
    needs = skill_service.get_company_skill_needs(db, company_id)
    return needs


@router.get("/companies/{company_id}/gap-analysis", response_model=Dict[str, Any])
async def analyze_company_skill_gaps(
    company_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Analyse les écarts de compétences pour une entreprise."""
    analysis = skill_service.analyze_skill_gaps(db, company_id)
    return analysis

@router.get("/gaps/{company_id}", response_model=List[SkillGapResponse])
async def analyze_skill_gaps_alias(
    company_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Alias pour l'analyse des écarts (Frontend compatibility)."""
    return skill_service.get_skill_gaps_list(db, company_id)


@router.get("/companies/{company_id}/training-recommendations", response_model=List[Dict[str, Any]])
async def get_training_recommendations(
    company_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Suggère des formations basées sur les écarts de compétences."""
    recommendations = skill_service.suggest_training(db, company_id)
    return recommendations

@router.get("/training/{company_id}", response_model=List[Dict[str, Any]])
async def get_training_recommendations_alias(
    company_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Alias pour les recommandations de formation (Frontend compatibility)."""
    return skill_service.suggest_training(db, company_id)


@router.get("/market-trends", response_model=List[Dict[str, Any]])
async def get_market_skill_trends(
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """Récupère les tendances des compétences sur le marché."""
    trends = skill_service.get_market_skill_trends(db, limit)
    return trends
