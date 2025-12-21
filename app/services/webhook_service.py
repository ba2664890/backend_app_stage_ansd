"""
Service de webhooks pour intégrations externes.
"""

from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from uuid import UUID
import logging
import hmac
import hashlib
import httpx
from datetime import datetime

from ..models.database_models import Webhook

logger = logging.getLogger(__name__)


class WebhookService:
    """Service pour gérer les webhooks."""
    
    def create_webhook(
        self,
        db: Session,
        company_id: UUID,
        url: str,
        events: List[str],
        secret: Optional[str] = None
    ) -> Webhook:
        """Crée un webhook."""
        import secrets
        
        webhook = Webhook(
            company_id=company_id,
            url=url,
            events=events,
            secret=secret or secrets.token_urlsafe(32),
            is_active=True
        )
        db.add(webhook)
        db.commit()
        db.refresh(webhook)
        
        logger.info(f"Webhook créé pour company {company_id}: {url}")
        return webhook
    
    def get_company_webhooks(
        self,
        db: Session,
        company_id: UUID
    ) -> List[Webhook]:
        """Récupère tous les webhooks d'une entreprise."""
        return db.query(Webhook).filter(
            Webhook.company_id == company_id
        ).all()
    
    def delete_webhook(self, db: Session, webhook_id: UUID) -> bool:
        """Supprime un webhook."""
        webhook = db.query(Webhook).filter(Webhook.id == webhook_id).first()
        if webhook:
            db.delete(webhook)
            db.commit()
            return True
        return False
    
    def toggle_webhook(self, db: Session, webhook_id: UUID, is_active: bool) -> Optional[Webhook]:
        """Active/désactive un webhook."""
        webhook = db.query(Webhook).filter(Webhook.id == webhook_id).first()
        if webhook:
            webhook.is_active = is_active
            db.commit()
            db.refresh(webhook)
        return webhook
    
    def _generate_signature(self, payload: str, secret: str) -> str:
        """Génère une signature HMAC pour sécuriser le webhook."""
        return hmac.new(
            secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    async def trigger_webhooks(
        self,
        db: Session,
        company_id: UUID,
        event: str,
        data: Dict
    ):
        """
        Déclenche tous les webhooks actifs pour un événement.
        
        Args:
            db: Session de base de données
            company_id: ID de l'entreprise
            event: Type d'événement (ex: "application.created")
            data: Données de l'événement
        """
        webhooks = db.query(Webhook).filter(
            Webhook.company_id == company_id,
            Webhook.is_active == True,
            Webhook.events.contains([event])
        ).all()
        
        for webhook in webhooks:
            await self._send_webhook(webhook, event, data)
    
    async def _send_webhook(self, webhook: Webhook, event: str, data: Dict):
        """Envoie un webhook à une URL."""
        import json
        
        payload = {
            "event": event,
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        
        payload_str = json.dumps(payload)
        signature = self._generate_signature(payload_str, webhook.secret)
        
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": signature,
            "X-Webhook-Event": event
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    webhook.url,
                    json=payload,
                    headers=headers
                )
                
                if response.status_code >= 200 and response.status_code < 300:
                    logger.info(f"Webhook envoyé avec succès: {webhook.url} - Event: {event}")
                else:
                    logger.warning(f"Webhook échoué: {webhook.url} - Status: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Erreur envoi webhook {webhook.url}: {e}")


# Exemples d'événements webhook:
WEBHOOK_EVENTS = {
    "application.created": "Nouvelle candidature reçue",
    "application.status_changed": "Statut de candidature modifié",
    "application.hired": "Candidat embauché",
    "application.rejected": "Candidat rejeté",
    "job.created": "Nouvelle offre créée",
    "job.expired": "Offre expirée",
}
