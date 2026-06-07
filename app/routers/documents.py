
import os
import shutil
import uuid
from typing import List
from app.services.cloudinary_service import CloudinaryService
from app.utils import logger
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..models.database_models import User, Document
from ..utils.auth import get_current_user
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(
    prefix="/api/v1/documents",
    tags=["documents"]
)

class DocumentResponse(BaseModel):
    id: uuid.UUID
    name: str
    file_type: str
    size: str
    category: str
    uploaded_at: datetime
    is_verified: bool
    url: str

    class Config:
        from_attributes = True

UPLOAD_DIR = "app/static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    category: str = Form(...),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    import logging

    from ..services.file_service import FileService
    from ..services.cloudinary_service import CloudinaryService

    logger = logging.getLogger(__name__)

    allowed_types = [
        "application/pdf",
        "image/jpeg",
        "image/png",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ]

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail="Type de fichier non supporté."
        )

    cloudinary_url = None
    cloudinary_public_id = None

    try:

        # ----------------------------
        # Vérification taille
        # ----------------------------

        content = await file.read()
        file_size = len(content)

        if file_size > 5 * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail="Le fichier ne doit pas dépasser 5 Mo."
            )

        file.file.seek(0)

        if file_size < 1024:
            size_str = f"{file_size} B"
        elif file_size < 1024 * 1024:
            size_str = f"{file_size / 1024:.1f} KB"
        else:
            size_str = f"{file_size / (1024 * 1024):.1f} MB"

        # ----------------------------
        # Upload Cloudinary
        # ----------------------------

        try:
            upload_result = CloudinaryService.upload_file(
                file.file
            )

            cloudinary_url = upload_result["url"]
            cloudinary_public_id = upload_result["public_id"]

            logger.info(
                f"✅ Upload Cloudinary réussi: {cloudinary_public_id}"
            )

        except Exception as e:
            logger.exception("Erreur Cloudinary")

            raise HTTPException(
                status_code=500,
                detail=f"Erreur upload Cloudinary: {str(e)}"
            )

        # ----------------------------
        # Extraction du texte
        # ----------------------------

        extracted_text = None

        try:
            file.file.seek(0)

            file_service = FileService()

            extracted_text = (
                await file_service.extract_text_from_upload(file)
            )

            if extracted_text:
                logger.info(
                    f"✅ Texte extrait ({len(extracted_text)} caractères)"
                )

        except Exception as e:
            logger.warning(
                f"⚠️ Extraction impossible: {e}"
            )

        # ----------------------------
        # Sauvegarde DB
        # ----------------------------

        try:

            new_doc = Document(
                user_id=current_user.user_id,
                name=file.filename,
                file_path=cloudinary_url,
                cloudinary_url=cloudinary_url,
                cloudinary_public_id=cloudinary_public_id,
                file_type=file.content_type,
                size=size_str,
                category=category,
                uploaded_at=datetime.utcnow(),
                extracted_text=extracted_text
            )

            db.add(new_doc)
            db.commit()
            db.refresh(new_doc)

        except Exception as e:

            db.rollback()

            logger.exception(
                "Erreur base de données"
            )

            # nettoyage Cloudinary
            if cloudinary_public_id:
                try:
                    CloudinaryService.delete_file(
                        cloudinary_public_id
                    )
                except Exception:
                    pass

            raise HTTPException(
                status_code=500,
                detail=f"Erreur base de données: {str(e)}"
            )

        return {
            "id": new_doc.id,
            "name": new_doc.name,
            "file_type": new_doc.file_type,
            "size": new_doc.size,
            "category": new_doc.category,
            "uploaded_at": new_doc.uploaded_at,
            "is_verified": new_doc.is_verified,
            "url": cloudinary_url
        }

    except HTTPException:
        raise

    except Exception as e:

        logger.exception(
            "Erreur inattendue upload document"
        )

        if cloudinary_public_id:
            try:
                CloudinaryService.delete_file(
                    cloudinary_public_id
                )
            except Exception:
                pass

        raise HTTPException(
            status_code=500,
            detail=f"Erreur serveur: {str(e)}"
        )

@router.get("", response_model=List[DocumentResponse])
def get_documents(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    docs = db.query(Document).filter(Document.user_id == current_user.user_id).all()
    
    return [
        {
            "id": doc.id,
            "name": doc.name,
            "file_type": doc.file_type,
            "size": doc.size,
            "category": doc.category,
            "uploaded_at": doc.uploaded_at,
            "is_verified": doc.is_verified,
            "url": f"/static/uploads/{os.path.basename(doc.file_path)}"
        }
        for doc in docs
    ]

@router.delete("/{document_id}")
def delete_document(
    document_id: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(Document).filter(Document.id == document_id, Document.user_id == current_user.user_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document non trouvé.")
    
    try:
        if doc.cloudinary_public_id:
            CloudinaryService.delete_file(
                doc.cloudinary_public_id
            )
    except Exception as e:
        logger.warning(
            f"Erreur suppression Cloudinary: {e}"
        )
    
    db.delete(doc)
    db.commit()
    
    return {"message": "Document supprimé avec succès."}
