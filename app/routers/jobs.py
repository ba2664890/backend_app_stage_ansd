"""
Routes API pour la gestion des offres d'emploi.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from uuid import UUID
import logging

from ..database import get_db
from ..models.api_models import (
    JobOfferResponse, 
    PaginatedResponse, 
    JobSearchParams,
    JobCreate
)
from ..services.job_service import JobService
from ..utils.auth import get_current_user, get_current_active_user_optional
from ..models.database_models import OffreEmploiBrute, OffreEmploiEnrichie

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])
job_service = JobService()

@router.get("", response_model=PaginatedResponse[JobOfferResponse])
async def search_jobs(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    location: Optional[str] = None,
    contract_type: Optional[str] = None,
    sector: Optional[str] = None,
    job_title: Optional[str] = None,
    min_salary: Optional[int] = None,
    max_salary: Optional[int] = None,
    source_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_active_user_optional)
):
    """
    Recherche des offres d'emploi avec filtres.
    Prend en compte la catégorie de l'utilisateur pour le filtrage strict.
    """
    params = JobSearchParams(
        skip=skip,
        limit=limit,
        search=search,
        location=location,
        contract_type=contract_type,
        sector=sector,
        job_title=job_title,
        min_salary=min_salary,
        max_salary=max_salary,
        source_type=source_type
    )
    
    # Récupérer la catégorie de l'utilisateur si connecté
    user_category = None
    if current_user:
        if hasattr(current_user, 'category'):
            user_category = current_user.category
        elif hasattr(current_user, 'profile') and current_user.profile and hasattr(current_user.profile, 'category'):
            user_category = current_user.profile.category
            
    paginated_response = job_service.search_jobs(db, params, user_category)

    # Si l'utilisateur est connecté et actif, calculer le score de matching IA dynamique pour chaque offre
    if current_user and hasattr(request.app.state, 'recommendation_service'):
        try:
            reco_service = request.app.state.recommendation_service
            for job_response in paginated_response.items:
                result = db.query(OffreEmploiBrute, OffreEmploiEnrichie).join(
                    OffreEmploiEnrichie, OffreEmploiBrute.id == OffreEmploiEnrichie.offre_id, isouter=True
                ).filter(OffreEmploiBrute.id == job_response.id).first()
                if result:
                    brute, enrichie = result
                    if enrichie:
                        score, reasons, breakdown = reco_service._calculate_match_score(
                            current_user, brute, enrichie
                        )
                        job_response.match_score = score
                        job_response.relevance_score = score
        except Exception as e:
            logger.error(f"Error calculating dynamic match scores in search_jobs: {e}")

    return paginated_response

@router.get("/my", response_model=List[JobOfferResponse])
async def get_my_jobs(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Récupère les offres postées par le recruteur connecté.
    """
    # Vérifier que c'est bien un recruteur
    user_obj = current_user.user
    recruiter_profile = user_obj.recruiter_profile
    if not recruiter_profile:
        # Fallback: vérifier le rôle
        role_val = getattr(user_obj.role, 'value', user_obj.role)
        if role_val != 'recruiter' and role_val != 'admin':
             raise HTTPException(status_code=403, detail="Accès réservé aux recruteurs")
             
    recruiter_id = recruiter_profile.id if recruiter_profile else None
    if not recruiter_id:
         raise HTTPException(status_code=400, detail="Profil recruteur non trouvé")
         
    return job_service.get_recruiter_jobs(db, recruiter_id)

@router.post("", response_model=JobOfferResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    job_data: JobCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Crée une nouvelle offre d'emploi.
    """
    user_obj = current_user.user
    recruiter_profile = user_obj.recruiter_profile
    if not recruiter_profile:
        raise HTTPException(status_code=403, detail="Seuls les recruteurs peuvent publier des offres")
        
    return job_service.create_job(
        db, 
        job_data, 
        recruiter_profile.id,
        recruiter_profile.company_id
    )

@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Supprime une offre d'emploi.
    """
    job_uuid = UUID(job_id)
    user_obj = current_user.user
    recruiter_profile = user_obj.recruiter_profile
    if not recruiter_profile:
         raise HTTPException(status_code=403, detail="Action réservée aux recruteurs")
         
    success = job_service.delete_job(db, job_uuid, recruiter_profile.id)
    if not success:
        raise HTTPException(status_code=404, detail="Offre non trouvée ou non autorisée")
    return None

@router.put("/{job_id}", response_model=JobOfferResponse)
async def update_job(
    job_id: str,
    job_data: JobCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Met à jour une offre d'emploi existante.
    """
    job_uuid = UUID(job_id)
    user_obj = current_user.user
    recruiter_profile = user_obj.recruiter_profile
    if not recruiter_profile:
        raise HTTPException(status_code=403, detail="Action réservée aux recruteurs")
        
    updated_job = job_service.update_job(
        db, 
        job_uuid, 
        job_data, 
        recruiter_profile.id
    )
    if not updated_job:
        raise HTTPException(status_code=404, detail="Offre non trouvée ou non autorisée")
    return updated_job

@router.get("/saved", response_model=List[JobOfferResponse])
async def get_saved_jobs(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Récupère les offres favorites."""
    return job_service.get_saved_jobs(db, current_user.user_id)

@router.post("/saved", status_code=status.HTTP_201_CREATED)
async def save_job(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Ajoute une offre aux favoris."""
    job_id = payload.get("job_id")
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id requis")
    
    try:
        job_service.save_job(db, current_user.user_id, job_id)
        return {"message": "Job saved"}
    except ValueError as e:
        # L'utilisateur n'existe pas dans cette DB ou l'offre est introuvable
        error_msg = str(e)
        if "Utilisateur" in error_msg and "introuvable" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session invalide : votre compte n'existe pas dans cette base de données. Veuillez vous reconnecter."
            )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)

@router.delete("/saved/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_saved_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Retire une offre des favoris."""
    try:
        job_uuid = UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format d'ID invalide")
    job_service.remove_saved_job(db, current_user.user_id, job_uuid)
    return None

@router.get("/{job_id}", response_model=JobOfferResponse)
async def get_job(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_active_user_optional)
):
    """Récupère une offre par son identifiant et calcule le score de matching dynamique."""
    try:
        uuid_obj = UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format d'ID invalide")

    result = db.query(OffreEmploiBrute, OffreEmploiEnrichie).join(
        OffreEmploiEnrichie, OffreEmploiBrute.id == OffreEmploiEnrichie.offre_id, isouter=True
    ).filter(OffreEmploiBrute.id == uuid_obj).first()

    if not result:
        raise HTTPException(status_code=404, detail="Offre non trouvée")

    brute, enrichie = result
    job_response = job_service._create_job_response(brute, enrichie)

    if current_user and hasattr(request.app.state, 'recommendation_service'):
        try:
            if enrichie:
                reco_service = request.app.state.recommendation_service
                score, reasons, breakdown = reco_service._calculate_match_score(
                    current_user, brute, enrichie
                )
                job_response.match_score = score
                job_response.relevance_score = score
        except Exception as e:
            logger.error(f"Error calculating dynamic match score for job {job_id}: {e}")

    return job_response
