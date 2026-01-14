from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, aliased
from sqlalchemy import or_, and_, func, desc
from typing import List, Dict, Any
from uuid import UUID
from datetime import datetime

from ..database import get_db
from ..models.database_models import Message, User, UserProfile, Application, Recruiter
from ..models.api_models import MessageCreate, MessageResponse, ConversationSummary
from ..utils.auth import get_current_user

router = APIRouter(prefix="/api/v1/messages", tags=["messages"])

@router.post("/send", response_model=MessageResponse)
async def send_message(
    message_data: MessageCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Envoie un message à un utilisateur.
    Condition: L'utilisateur cible doit exister.
    """
    # Vérifier que le destinataire existe
    receiver = db.query(User).filter(User.id == message_data.receiver_id).first()
    if not receiver:
        raise HTTPException(status_code=404, detail="Destinataire non trouvé")
    
    new_message = Message(
        sender_id=current_user.user_id,
        receiver_id=message_data.receiver_id,
        content=message_data.content,
        is_read=False
    )
    
    db.add(new_message)
    db.commit()
    db.refresh(new_message)
    
    return new_message

@router.get("/history/{other_user_id}", response_model=List[MessageResponse])
async def get_conversation_history(
    other_user_id: UUID,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Récupère l'historique des messages avec un utilisateur spécifique.
    """
    messages = db.query(Message).filter(
        or_(
            and_(Message.sender_id == current_user.user_id, Message.receiver_id == other_user_id),
            and_(Message.sender_id == other_user_id, Message.receiver_id == current_user.user_id)
        )
    ).order_by(Message.created_at.asc()).limit(limit).all()
    
    return messages

@router.put("/read/{other_user_id}")
async def mark_conversation_read(
    other_user_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Marque tous les messages reçus d'un utilisateur comme lus.
    """
    db.query(Message).filter(
        Message.sender_id == other_user_id,
        Message.receiver_id == current_user.user_id,
        Message.is_read == False
    ).update({"is_read": True})
    
    db.commit()
    return {"success": True}

@router.get("/conversations", response_model=List[ConversationSummary])
async def get_conversations(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Récupère la liste des conversations actives (basée sur les messages et candidatures).
    """
    user_id = current_user.user_id
    
    # Stratégie : 
    # 1. Récupérer les ID des utilisateurs avec qui on a échangé des messages
    # 2. Si Recruteur, récupérer aussi les ID des candidats qui ont postulé (pour initier les conv)
    
    # --- 1. Conversations existantes ---
    # Sous-requête pour trouver le dernier message par interlocuteur
    # C'est complexe en SQL pur via ORM, on va faire une approche plus code-level pour le MVP
    # ou utiliser une requête union.
    
    # Récupérer tous les messages impliquant l'utilisateur
    all_messages = db.query(Message).filter(
        or_(Message.sender_id == user_id, Message.receiver_id == user_id)
    ).order_by(Message.created_at.desc()).all()
    
    conversations_map = {}
    
    for msg in all_messages:
        other_id = msg.receiver_id if msg.sender_id == user_id else msg.sender_id
        
        if other_id not in conversations_map:
            conversations_map[other_id] = {
                "last_message": msg.content,
                "last_message_at": msg.created_at,
                "unread_count": 0
            }
        
        if msg.receiver_id == user_id and not msg.is_read:
            conversations_map[other_id]["unread_count"] += 1
            
    # --- 2. Candidatures (Si Recruiter) ---
    recruiter = db.query(Recruiter).filter(Recruiter.user_id == user_id).first()
    if recruiter:
        # Trouver les candidats ayant postulé aux offres de l'entreprise du recruteur
        # Application a directement company_id
        applications = db.query(Application).filter(
            Application.company_id == recruiter.company_id
        ).all()
        
        for app in applications:
            if app.user_id not in conversations_map and app.user_id != user_id:
                conversations_map[app.user_id] = {
                    "last_message": "Nouvelle candidature",
                    "last_message_at": app.created_at,
                    "unread_count": 0, # Pas de msg non lu, juste une notif potentielle
                    "is_application": True
                }

    # --- 3. Enrichir avec les infos utilisateurs ---
    contact_ids = list(conversations_map.keys())
    if not contact_ids:
        return []
        
    users = db.query(User).filter(User.id.in_(contact_ids)).all()
    
    # Mapper profiles manuellement si joinedload complexe
    profiles = db.query(UserProfile).filter(UserProfile.user_id.in_(contact_ids)).all()
    profiles_map = {p.user_id: p for p in profiles}
    
    results = []
    for user in users:
        conv_data = conversations_map.get(user.id)
        profile = profiles_map.get(user.id)
        
        results.append(ConversationSummary(
            user_id=user.id,
            first_name=profile.first_name if profile else None,
            last_name=profile.last_name if profile else None,
            email=user.email,
            last_message=conv_data["last_message"],
            last_message_at=conv_data["last_message_at"],
            unread_count=conv_data["unread_count"],
            role=user.role.value
        ))
        
    # Trier par date du dernier message
    results.sort(key=lambda x: x.last_message_at or datetime.min, reverse=True)
    
    return results
