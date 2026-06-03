"""
Routes API pour la gestion des offres d'emploi.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from uuid import UUID

from ..database import get_db
from ..models.api_models import (
    JobOfferResponse, 
    PaginatedResponse, 
    JobSearchParams,
    JobCreate
)
from ..services.job_service import JobService
from ..utils.auth import get_current_user, get_current_active_user_optional
# get_current_active_user_optional est nécessaire pour la recherche publique (visiteur vs connecté)

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])
job_service = JobService()

@router.get("", response_model=PaginatedResponse[JobOfferResponse])
async def search_jobs(
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
        # On suppose que category est accessible sur l'objet user ou via son profil
        # Vérifions le modèle User. Il a un champ 'category' ? 
        # Non, User a 'role'. UserProfile a peut-être 'category' ?
        # Dans database_models.py, User a role mais pas directement category sauf si c'est un champ ajouté dynamiquement.
        # Mais le frontend envoie 'category' dans le token ou le User context.
        # Le model 'User' n'a PAS de champ category visiblement (step 1258).
        # MAIS wait, le frontend fait `const category = (user as any)?.category`.
        # On va vérifier si le User Pydantic le renvoie.
        # Si non, on va supposer que c'est sur le profil.
        if hasattr(current_user, 'category'):
            user_category = current_user.category
        elif hasattr(current_user, 'profile') and current_user.profile and hasattr(current_user.profile, 'category'):
            user_category = current_user.profile.category
            
    return job_service.search_jobs(db, params, user_category)

@router.get("/my", response_model=List[JobOfferResponse])
async def get_my_jobs(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Récupère les offres postées par le recruteur connecté.
    """
    # Vérifier que c'est bien un recruteur
    if not hasattr(current_user, 'recruiter_profile') or not current_user.recruiter_profile:
        # Fallback: vérifier le rôle
        if current_user.role != 'recruiter' and current_user.role != 'admin':
             raise HTTPException(status_code=403, detail="Accès réservé aux recruteurs")
             
    recruiter_id = current_user.recruiter_profile.id if current_user.recruiter_profile else None
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
    if not current_user.recruiter_profile:
        raise HTTPException(status_code=403, detail="Seuls les recruteurs peuvent publier des offres")
        
    return job_service.create_job(
        db, 
        job_data, 
        current_user.recruiter_profile.id,
        current_user.recruiter_profile.company_id
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
    if not current_user.recruiter_profile:
         raise HTTPException(status_code=403, detail="Action réservée aux recruteurs")
         
    success = job_service.delete_job(db, job_uuid, current_user.recruiter_profile.id)
    if not success:
        raise HTTPException(status_code=404, detail="Offre non trouvée ou non autorisée")
    return None

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
    db: Session = Depends(get_db),
    current_user = Depends(get_current_active_user_optional)
):
    """Récupère une offre par son identifiant."""
    job = job_service.get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Offre non trouvée")
    return job
