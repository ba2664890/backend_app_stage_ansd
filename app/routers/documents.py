
import os
import shutil
import uuid
from typing import List
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
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Validate file type
    allowed_types = ["application/pdf", "image/jpeg", "image/png", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Type de fichier non supporté.")

    # Generate unique filename
    file_ext = os.path.splitext(file.filename)[1]
    unique_filename = f"{current_user.id}_{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)

    # Save file
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Erreur lors de la sauvegarde du fichier.")

    # Calculate size
    file_size = os.path.getsize(file_path)
    # Convert to human readable
    if file_size < 1024:
        size_str = f"{file_size} B"
    elif file_size < 1024 * 1024:
        size_str = f"{file_size / 1024:.1f} KB"
    else:
        size_str = f"{file_size / (1024 * 1024):.1f} MB"

    # Create DB entry
    new_doc = Document(
        user_id=current_user.user_id,
        name=file.filename,
        file_path=file_path,
        file_type=file.content_type,
        size=size_str,
        category=category,
        uploaded_at=datetime.utcnow()
    )
    
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)

    return {
        "id": new_doc.id,
        "name": new_doc.name,
        "file_type": new_doc.file_type,
        "size": new_doc.size,
        "category": new_doc.category,
        "uploaded_at": new_doc.uploaded_at,  # Make sure this matches the model field type
        "is_verified": new_doc.is_verified,
        "url": f"/static/uploads/{unique_filename}"
    }

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
    
    # Remove file from disk
    if os.path.exists(doc.file_path):
        os.remove(doc.file_path)
    
    db.delete(doc)
    db.commit()
    
    return {"message": "Document supprimé avec succès."}
