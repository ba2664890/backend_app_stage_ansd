from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List

from ..database import get_db
from ..models.api_models import WebhookCreate, WebhookResponse
from ..services.webhook_service import WebhookService
from ..utils.auth import get_current_user

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])
webhook_service = WebhookService()

@router.post("", response_model=WebhookResponse, status_code=201)
async def create_webhook(
    webhook_data: WebhookCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Crée un nouveau webhook pour une entreprise.
    """
    try:
        # Note: Dans un vrai contexte, vérifier que current_user appartient à company_id
        webhook = webhook_service.create_webhook(
            db=db,
            company_id=webhook_data.company_id,
            url=webhook_data.url,
            events=webhook_data.events
        )
        return webhook
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur création webhook: {str(e)}")

@router.get("/company/{company_id}", response_model=List[WebhookResponse])
async def get_company_webhooks(
    company_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Récupère les webhooks d'une entreprise.
    """
    return webhook_service.get_company_webhooks(db, company_id)

@router.put("/{webhook_id}/toggle", response_model=WebhookResponse)
async def toggle_webhook(
    webhook_id: UUID,
    is_active: bool = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Active ou désactive un webhook.
    """
    webhook = webhook_service.toggle_webhook(db, webhook_id, is_active)
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook non trouvé")
    return webhook

@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Supprime un webhook.
    """
    success = webhook_service.delete_webhook(db, webhook_id)
    if not success:
        raise HTTPException(status_code=404, detail="Webhook non trouvé")
    return None
