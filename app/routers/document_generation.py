"""
Router FastAPI pour la génération de documents (CV, lettres de motivation, etc.)
POST /api/v1/documents/generate/cover-letter
POST /api/v1/documents/generate/cv
POST /api/v1/documents/generate/letter
GET  /api/v1/documents/generate/download/{filename}
"""
import os
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.database_models import User, UserProfile, Document
from ..utils.auth import get_current_user
from ..services.document_generation_service import DocumentGenerationService, UserProfileData
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/documents/generate",
    tags=["document-generation"],
)

OUTPUT_DIR = "app/static/generated"
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ─────────────────────────────────────────────────────────
# SCHEMAS PYDANTIC
# ─────────────────────────────────────────────────────────

class CoverLetterRequest(BaseModel):
    job_title: str = Field(..., description="Intitulé du poste visé")
    company_name: str = Field(..., description="Nom de l'entreprise")
    job_description: Optional[str] = Field("", description="Description de l'offre (optionnel)")
    tone: Optional[str] = Field("professionnel", description="professionnel | dynamique | formel")

class CVRequest(BaseModel):
    target_job: Optional[str] = Field("", description="Poste cible pour personnaliser l'accroche")

class OtherLetterRequest(BaseModel):
    letter_type: str = Field(
        ...,
        description="Type: resignation | internship_request | follow_up | recommendation_request"
    )
    context: Dict[str, str] = Field(
        default_factory=dict,
        description="Champs contextuels (ex: {'company': 'Sonatel', 'notice_period': '1 mois'})"
    )

class DocumentGenerationResponse(BaseModel):
    success: bool
    message: str
    document_type: str
    file_name: str
    download_url: str
    content_preview: Optional[str] = None  # Les 300 premiers caractères du texte généré


# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────

def _profile_from_db(db_profile: UserProfile, user: User) -> UserProfileData:
    """Convertit le profil DB en dataclass de génération."""
    return UserProfileData(
        first_name=db_profile.first_name or "",
        last_name=db_profile.last_name or "",
        email=user.email or "",
        phone=db_profile.phone or "",
        location=db_profile.location or "",
        current_title=db_profile.current_title or "",
        experience_years=db_profile.experience_years or 0,
        education_level=db_profile.education_level or "",
        skills=db_profile.skills or [],
        bio=db_profile.bio or "",
        linkedin=db_profile.linkedin or "",
        github=db_profile.github or "",
        portfolio=db_profile.portfolio or "",
        languages=db_profile.languages,
        experiences=db_profile.experiences,
        certifications=db_profile.certifications,
    )


def _save_document_to_db(
    db: Session,
    user_id,
    file_path: str,
    file_name: str,
    doc_type: str,
) -> Document:
    """Persiste le document généré dans la table documents."""
    file_size = os.path.getsize(file_path)
    size_str = f"{file_size / 1024:.1f} KB"

    new_doc = Document(
        id=uuid.uuid4(),
        user_id=user_id,
        name=file_name,
        file_path=file_path,
        file_type="application/pdf",
        size=size_str,
        category=doc_type,
        uploaded_at=datetime.utcnow(),
        is_verified=False,
    )
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)
    return new_doc


# ─────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────

@router.post("/cover-letter", response_model=DocumentGenerationResponse)
async def generate_cover_letter(
    request: CoverLetterRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Génère une lettre de motivation personnalisée pour le candidat connecté."""
    profile_db = db.query(UserProfile).filter(
        UserProfile.user_id == current_user.user_id
    ).first()

    if not profile_db:
        raise HTTPException(status_code=404, detail="Profil candidat introuvable. Complétez votre profil d'abord.")

    if not profile_db.first_name or not profile_db.last_name:
        raise HTTPException(status_code=422, detail="Votre prénom et nom doivent être renseignés dans le profil.")

    profile = _profile_from_db(profile_db, current_user)
    svc = DocumentGenerationService()

    try:
        result = await svc.generate_cover_letter(
            profile=profile,
            job_title=request.job_title,
            company_name=request.company_name,
            job_description=request.job_description,
            tone=request.tone,
        )
    except Exception as e:
        logger.error(f"Erreur génération lettre de motivation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erreur lors de la génération du document.")

    _save_document_to_db(db, current_user.user_id, result.file_path, result.file_name, "cover_letter")

    return DocumentGenerationResponse(
        success=True,
        message="Lettre de motivation générée avec succès.",
        document_type="cover_letter",
        file_name=result.file_name,
        download_url=f"/api/v1/documents/generate/download/{result.file_name}",
        content_preview=result.content_text[:300] + "..." if len(result.content_text) > 300 else result.content_text,
    )


@router.post("/cv", response_model=DocumentGenerationResponse)
async def generate_cv(
    request: CVRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Génère un CV PDF professionnel à partir du profil candidat."""
    profile_db = db.query(UserProfile).filter(
        UserProfile.user_id == current_user.user_id
    ).first()

    if not profile_db:
        raise HTTPException(status_code=404, detail="Profil candidat introuvable.")

    if not profile_db.first_name:
        raise HTTPException(status_code=422, detail="Votre prénom doit être renseigné dans le profil.")

    profile = _profile_from_db(profile_db, current_user)
    svc = DocumentGenerationService()

    try:
        result = await svc.generate_cv(profile=profile, target_job=request.target_job or "")
    except Exception as e:
        logger.error(f"Erreur génération CV: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erreur lors de la génération du CV.")

    _save_document_to_db(db, current_user.user_id, result.file_path, result.file_name, "cv")

    return DocumentGenerationResponse(
        success=True,
        message="CV généré avec succès.",
        document_type="cv",
        file_name=result.file_name,
        download_url=f"/api/v1/documents/generate/download/{result.file_name}",
        content_preview=result.content_text[:300],
    )


@router.post("/letter", response_model=DocumentGenerationResponse)
async def generate_other_letter(
    request: OtherLetterRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Génère une lettre administrative (démission, stage, relance, recommandation)."""
    allowed_types = ["resignation", "internship_request", "follow_up", "recommendation_request"]
    if request.letter_type not in allowed_types:
        raise HTTPException(
            status_code=422,
            detail=f"Type de lettre invalide. Valeurs acceptées : {', '.join(allowed_types)}"
        )

    profile_db = db.query(UserProfile).filter(
        UserProfile.user_id == current_user.user_id
    ).first()

    if not profile_db:
        raise HTTPException(status_code=404, detail="Profil candidat introuvable.")

    profile = _profile_from_db(profile_db, current_user)
    svc = DocumentGenerationService()

    try:
        result = await svc.generate_other_letter(
            profile=profile,
            letter_type=request.letter_type,
            context=request.context,
        )
    except Exception as e:
        logger.error(f"Erreur génération lettre ({request.letter_type}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erreur lors de la génération de la lettre.")

    _save_document_to_db(db, current_user.user_id, result.file_path, result.file_name, request.letter_type)

    return DocumentGenerationResponse(
        success=True,
        message=f"Lettre générée avec succès.",
        document_type=request.letter_type,
        file_name=result.file_name,
        download_url=f"/api/v1/documents/generate/download/{result.file_name}",
        content_preview=result.content_text[:300],
    )


@router.get("/download/{filename}")
async def download_generated_document(
    filename: str,
    current_user=Depends(get_current_user),
):
    """Télécharge un document PDF généré."""
    # Sécurité : on n'accepte que les noms sans chemin traversal
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide.")

    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Fichier introuvable ou expiré.")

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/types")
async def list_document_types(current_user=Depends(get_current_user)):
    """Retourne la liste des types de documents supportés."""
    return {
        "types": [
            {"id": "cv",                     "label": "CV Professionnel",                 "endpoint": "/cv"},
            {"id": "cover_letter",           "label": "Lettre de motivation",             "endpoint": "/cover-letter"},
            {"id": "resignation",            "label": "Lettre de démission",              "endpoint": "/letter"},
            {"id": "internship_request",     "label": "Demande de stage",                 "endpoint": "/letter"},
            {"id": "follow_up",              "label": "Lettre de relance candidature",    "endpoint": "/letter"},
            {"id": "recommendation_request", "label": "Demande de recommandation",        "endpoint": "/letter"},
        ]
    }
