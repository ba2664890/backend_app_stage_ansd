
import os
import shutil
import uuid
from typing import List, Optional
from app.services.cloudinary_service import CloudinaryService
from app.utils import logger
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from ..database import get_db
from ..models.database_models import User, Document, UserProfile
from ..utils.auth import get_current_user, get_current_user_optional, verify_token
from ..config import settings
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
    size: Optional[str] = None
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
        # Sauvegarde locale & Upload Cloudinary
        # ----------------------------
        local_filename = f"{uuid.uuid4()}_{file.filename}"
        local_path = os.path.join(UPLOAD_DIR, local_filename)

        # Sauvegarde locale (sert à l'extraction et de fallback de stockage)
        with open(local_path, "wb") as buffer:
            buffer.write(content)

        file_path_db = local_path

        try:
            # Uploader sur Cloudinary si configuré
            if hasattr(settings, "CLOUDINARY_URL") and settings.CLOUDINARY_URL:
                file.file.seek(0)
                upload_result = CloudinaryService.upload_file(file.file)
                cloudinary_url = upload_result["url"]
                cloudinary_public_id = upload_result["public_id"]
                file_path_db = cloudinary_url
                logger.info(f"✅ Upload Cloudinary réussi: {cloudinary_public_id}")
            else:
                logger.info("ℹ️ Cloudinary non configuré, stockage local utilisé uniquement.")
        except Exception as e:
            logger.warning(f"⚠️ Échec upload Cloudinary ({e}), stockage local conservé.")

        # ----------------------------
        # Extraction du texte
        # ----------------------------

        extracted_text = None

        try:
            # Utiliser le fichier local pour l'extraction de texte (plus robuste)
            file_service = FileService()
            extracted_text = await file_service.extract_text_from_file(local_path)

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
                file_path=file_path_db,
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

            # nettoyage fichier local
            if os.path.exists(local_path):
                try: os.remove(local_path)
                except: pass

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
            "url": f"/api/v1/documents/download/{new_doc.id}"
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
            "url": f"/api/v1/documents/download/{doc.id}"
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


@router.get("/download/{document_id}")
def download_document(
    document_id: str,
    token: Optional[str] = Query(None),
    current_user = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    # Authentification par token dans l'URL ou en-tête
    user = current_user
    if not user and token:
        try:
            payload = verify_token(token)
            sub = payload.get("sub")
            if sub:
                from uuid import UUID
                try:
                    user_uuid = UUID(sub)
                    user = db.query(UserProfile).filter(UserProfile.user_id == user_uuid).first()
                except ValueError:
                    pass
                if not user:
                    user_obj = db.query(User).filter(User.email == sub).first()
                    if user_obj:
                        user = db.query(UserProfile).filter(UserProfile.user_id == user_obj.id).first()
        except Exception:
            raise HTTPException(status_code=401, detail="Token de téléchargement invalide ou expiré.")

    if not user:
        raise HTTPException(status_code=401, detail="Authentification requise pour télécharger ce document.")

    # Récupérer le document
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de document invalide.")

    doc = db.query(Document).filter(Document.id == doc_uuid).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document non trouvé.")

    # Si le fichier existe localement
    if doc.file_path and not doc.file_path.startswith("http") and os.path.exists(doc.file_path):
        media_type = doc.file_type or "application/octet-stream"
        disposition = "inline" if media_type == "application/pdf" or doc.name.endswith(".pdf") else "attachment"
        return FileResponse(
            path=doc.file_path,
            media_type=media_type,
            filename=doc.name,
            headers={"Content-Disposition": f"{disposition}; filename={doc.name}"},
        )

    # Sinon, si on a un URL Cloudinary, on le télécharge depuis Cloudinary et on le renvoie pour contourner CORS
    if doc.cloudinary_url:
        import requests
        from fastapi.responses import StreamingResponse
        try:
            response = requests.get(doc.cloudinary_url, stream=True)
            if response.status_code == 200:
                media_type = response.headers.get("content-type") or doc.file_type or "application/octet-stream"
                disposition = "inline" if media_type == "application/pdf" or doc.name.endswith(".pdf") else "attachment"
                
                def file_stream():
                    for chunk in response.iter_content(chunk_size=8192):
                        yield chunk
                
                return StreamingResponse(
                    file_stream(),
                    media_type=media_type,
                    headers={
                        "Content-Disposition": f"{disposition}; filename={doc.name}",
                        "Access-Control-Allow-Origin": "*"
                    }
                )
        except Exception as e:
            logger.error(f"Erreur de streaming Cloudinary: {e}")
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=doc.cloudinary_url)

    # Si c'est un chemin local mais le fichier physique n'existe plus sur le serveur (container redémarré)
    raise HTTPException(status_code=404, detail="Le fichier physique est introuvable sur ce serveur.")
