from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import or_
from uuid import UUID
from typing import List, Dict, Any, Optional

from ..database import get_db
from ..models.api_models import JobOfferResponse
from ..models.database_models import UserProfile, UserRole
from ..services.user_service import UserService
from ..services.job_service import JobService
from ..utils.auth import get_current_user

router = APIRouter(prefix="/api/v1/users", tags=["users"])
user_service = UserService()
job_service = JobService()


def _role_value(current_user) -> str:
    role = getattr(getattr(current_user, "user", None), "role", None)
    return getattr(role, "value", role) or ""


def _can_view_profile(current_user, target: UserProfile) -> bool:
    role = _role_value(current_user)
    return (
        str(current_user.user_id) == str(target.user_id)
        or role in {UserRole.RECRUITER.value, UserRole.HR_MANAGER.value, UserRole.ADMIN.value}
    )


def _profile_payload(profile: UserProfile, current_user_id: Optional[UUID] = None) -> Dict[str, Any]:
    user = profile.user
    
    settings = profile.settings or {}
    privacy = settings.get("privacy", {})
    show_email = privacy.get("show_email", True)
    show_phone = privacy.get("show_phone", True)
    
    email_val = user.email if user else None
    phone_val = profile.phone
    whatsapp_val = profile.whatsapp
    
    # If not the profile owner, mask private fields
    if current_user_id is None or str(current_user_id) != str(profile.user_id):
        if not show_email:
            email_val = "Non partagé (privé)"
        if not show_phone:
            phone_val = "Non partagé (privé)"
            whatsapp_val = "Non partagé (privé)"
            
    return {
        "id": str(profile.user_id),
        "profile_id": str(profile.id),
        "email": email_val,
        "role": getattr(user.role, "value", user.role) if user else None,
        "points": profile.points,
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "phone": phone_val,
        "whatsapp": whatsapp_val,
        "location": profile.location,
        "category": getattr(profile.category, "value", profile.category),
        "current_title": profile.current_title,
        "experience_years": profile.experience_years,
        "education_level": profile.education_level,
        "skills": profile.skills or [],
        "preferred_contract_type": profile.preferred_contract_type or [],
        "preferred_salary_min": profile.preferred_salary_min,
        "preferred_salary_max": profile.preferred_salary_max,
        "bio": profile.bio,
        "availability": profile.availability,
        "cv_url": profile.cv_url,
        "linkedin": profile.linkedin,
        "github": profile.github,
        "portfolio": profile.portfolio,
        "languages": profile.languages or [],
        "experiences": profile.experiences or [],
        "certifications": profile.certifications or [],
        "gender": profile.gender,
        "date_of_birth": profile.date_of_birth,
        "school_name": profile.school_name,
        "school_level": profile.school_level,
        "school_field": profile.school_field,
        "school_region": profile.school_region,
        "orientation_goal": profile.orientation_goal,
        "interests": profile.interests or [],
        "university": profile.university,
        "study_level": profile.study_level,
        "study_domain": profile.study_domain,
        "study_year": profile.study_year,
        "is_alternance": profile.is_alternance,
        "internship_count": profile.internship_count,
        "seeking_type": profile.seeking_type,
        "key_skills": profile.key_skills or [],
        "informal_activity": profile.informal_activity,
        "informal_sector": profile.informal_sector,
        "spoken_languages": profile.spoken_languages or [],
        "school_level_reached": profile.school_level_reached,
        "informal_goal": profile.informal_goal,
        "practical_skills": profile.practical_skills,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }

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


@router.get("/profile/recu", response_model=Dict[str, Any])
async def get_my_profile(
    current_user = Depends(get_current_user)
):
    """Récupère le profil de l'utilisateur connecté."""
    return _profile_payload(current_user, current_user.user_id)


@router.get("/profile/{user_id}", response_model=Dict[str, Any])
async def get_profile_by_id(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Récupère un profil candidat.
    Les recruteurs/admins peuvent ouvrir les profils depuis la carte, un candidat ne peut ouvrir que son propre profil.
    """
    profile = db.query(UserProfile).filter(
        or_(UserProfile.user_id == user_id, UserProfile.id == user_id)
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profil non trouvé")

    if not _can_view_profile(current_user, profile):
        raise HTTPException(status_code=403, detail="Vous n'avez pas accès à ce profil")

    return _profile_payload(profile, current_user.user_id)

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
    return job_service.get_saved_jobs(db, current_user.user_id)

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
        job_service.save_job(db, current_user.user_id, job_id)
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
