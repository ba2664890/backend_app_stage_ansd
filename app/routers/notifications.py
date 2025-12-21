"""
Routes API pour les notifications.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from ..database import get_db
from ..models.api_models import PaginatedResponse
from ..services.notification_service import NotificationService
from ..utils.auth import get_current_user

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])
notification_service = NotificationService()


@router.get("/me", response_model=List[dict])
async def get_my_notifications(
    unread_only: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Récupère les notifications de l'utilisateur actuel."""
    user_id = current_user.user_id
    notifications = notification_service.get_user_notifications(db, user_id, unread_only, limit)
    
    return [{
        "id": str(n.id),
        "type": n.type,
        "title": n.title,
        "message": n.message,
        "action_url": n.action_url,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat(),
        "read_at": n.read_at.isoformat() if n.read_at else None
    } for n in notifications]


@router.put("/{notification_id}/read")
async def mark_notification_as_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Marque une notification comme lue."""
    notification = notification_service.mark_as_read(db, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification non trouvée")
    
    return {"message": "Notification marquée comme lue"}


@router.put("/mark-all-read")
async def mark_all_notifications_as_read(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Marque toutes les notifications comme lues."""
    user_id = current_user.user_id
    count = notification_service.mark_all_as_read(db, user_id)
    
    return {"message": f"{count} notification(s) marquée(s) comme lue(s)"}
