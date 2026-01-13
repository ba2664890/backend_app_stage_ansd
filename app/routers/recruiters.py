"""
Routes API pour la gestion des recruteurs.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
import logging

logger = logging.getLogger(__name__)

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


@router.post("/register", response_model=RecruiterResponse, status_code=201)
async def create_recruiter(
    recruiter_data: RecruiterCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Enregistre l'utilisateur actuel comme recruteur pour une entreprise.
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
    # ... (inchangé)
    user_id = current_user.user_id
    recruiter = recruiter_service.get_or_create_recruiter(db, user_id)
    if not recruiter:
        raise HTTPException(status_code=404, detail="Vous n'êtes pas enregistré comme recruteur")
    return recruiter


@router.get("/{recruiter_id}", response_model=RecruiterWithCompanyResponse)
async def get_recruiter(
    recruiter_id: UUID,
    db: Session = Depends(get_db)
):
    # ... (inchangé)
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
    # ... (inchangé)
    success = recruiter_service.delete_recruiter(db, recruiter_id)
    if not success:
        raise HTTPException(status_code=404, detail="Recruteur non trouvé")
    return None


# Correction de la route pour matcher le frontend
@router.get("/company/{company_id}", response_model=PaginatedResponse[RecruiterResponse])
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

# Import pour le matching (placé ici pour éviter les cycles si possible, ou en haut)
from fastapi import Request
from ..models.database_models import OffreEmploiBrute, OffreEmploiEnrichie, UserProfile

@router.post("/match-candidates")
async def find_candidates_for_job(
    request: Request,
    job_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Pour un job donné, trouve les candidats (CVs) les plus pertinents.
    Utilise la recherche vectorielle Qdrant (embedding CV vs embedding Job).
    """
    try:
        # 1. Récupérer le job et ses détails enrichis (conversion string -> UUID pour SQLAlchemy)
        try:
            job_uuid = UUID(job_id) if isinstance(job_id, str) else job_id
        except ValueError:
            raise HTTPException(status_code=400, detail="Format d'ID de job invalide")

        job = db.query(OffreEmploiBrute).filter(OffreEmploiBrute.id == job_uuid).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job non trouvé")
            
        enrichie = db.query(OffreEmploiEnrichie).filter(OffreEmploiEnrichie.offre_id == job_uuid).first()
        skills = enrichie.extracted_skills if enrichie and enrichie.extracted_skills else []
        
        # 2. Accéder au service d'embedding via l'état de l'app
        if not hasattr(request.app.state, 'cv_pipeline_service'):
             raise HTTPException(status_code=503, detail="Service de pipeline CV non disponible")
             
        embedding_service = request.app.state.cv_pipeline_service.cv_embedding_service
        
        # 3. Générer embedding du job (Titre + Skills + Desc)
        # Note: on utilise await car embed_job est async
        job_embedding = await embedding_service.embed_job(
            title=job.title,
            skills=skills,
            description=job.description
        )
        
        # 4. Chercher dans Qdrant les CVs similaires
        candidate_ids = await embedding_service.find_similar_cvs(job_embedding, limit=20)
        
        candidates = []
        if candidate_ids:
            # 5. Récupérer les profils complets depuis Postgres si on a des IDs de Qdrant
            candidates = db.query(UserProfile).filter(UserProfile.id.in_(candidate_ids)).all()
        
        # 6. Fallback SQL si aucun candidat trouvé via vectoriel (ou si mode léger)
        if not candidates:
            from sqlalchemy import or_, func, any_
            
            # Recherche par titre (insensible à la casse)
            title_query = f"%{job.title}%"
            
            # Construction de la requête de fallback
            fallback_query = db.query(UserProfile).filter(UserProfile.is_active == True)
            
            # Filtre par titre ou par compétences
            conditions = [UserProfile.current_title.ilike(title_query)]
            
            if skills:
                # Pour PostgreSQL, on peut utiliser l'opérateur de chevauchement d'arrays && 
                # ou vérifier si une des compétences du job est dans l'array des compétences du profil
                # Ici on utilise une approche simple : le profil a au moins une compétence en commun
                from sqlalchemy.dialects.postgresql import ARRAY
                fallback_query = fallback_query.filter(
                    or_(
                        UserProfile.current_title.ilike(title_query),
                        UserProfile.skills.overlap(skills)
                    )
                )
            else:
                fallback_query = fallback_query.filter(UserProfile.current_title.ilike(title_query))
            
            # Limiter et exécuter
            candidates = fallback_query.limit(20).all()
            
        return {"candidates": candidates, "count": len(candidates)}
        
    except Exception as e:
        import traceback
        logger.error(f"Erreur matching candidats: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Erreur matching candidats: {str(e)}")
