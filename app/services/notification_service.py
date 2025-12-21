"""
Service de notifications (Email, Push, In-app).
"""

from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from ..models.database_models import Notification, User, Application
from ..config import settings

logger = logging.getLogger(__name__)


class NotificationService:
    """Service pour gérer les notifications."""
    
    def create_notification(
        self,
        db: Session,
        user_id: UUID,
        type: str,
        title: str,
        message: str,
        action_url: Optional[str] = None,
        extra_data: Optional[Dict] = None
    ) -> Notification:
        """Crée une notification in-app."""
        notification = Notification(
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            action_url=action_url,
            extra_data=extra_data or {}
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)
        
        logger.info(f"Notification créée: {type} pour user {user_id}")
        return notification
    
    def get_user_notifications(
        self,
        db: Session,
        user_id: UUID,
        unread_only: bool = False,
        limit: int = 50
    ) -> List[Notification]:
        """Récupère les notifications d'un utilisateur."""
        query = db.query(Notification).filter(Notification.user_id == user_id)
        
        if unread_only:
            query = query.filter(Notification.is_read == False)
        
        return query.order_by(Notification.created_at.desc()).limit(limit).all()
    
    def mark_as_read(self, db: Session, notification_id: UUID) -> Optional[Notification]:
        """Marque une notification comme lue."""
        notification = db.query(Notification).filter(Notification.id == notification_id).first()
        
        if notification:
            notification.is_read = True
            notification.read_at = datetime.now()
            db.commit()
            db.refresh(notification)
        
        return notification
    
    def mark_all_as_read(self, db: Session, user_id: UUID) -> int:
        """Marque toutes les notifications d'un utilisateur comme lues."""
        count = db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.is_read == False
        ).update({
            "is_read": True,
            "read_at": datetime.now()
        })
        db.commit()
        return count
    
    async def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None
    ) -> bool:
        """
        Envoie un email.
        
        Note: Configurez les variables d'environnement:
        - SMTP_HOST
        - SMTP_PORT
        - SMTP_USER
        - SMTP_PASSWORD
        """
        try:
            # Configuration SMTP (à adapter selon votre provider)
            smtp_host = getattr(settings, 'SMTP_HOST', 'smtp.gmail.com')
            smtp_port = getattr(settings, 'SMTP_PORT', 587)
            smtp_user = getattr(settings, 'SMTP_USER', '')
            smtp_password = getattr(settings, 'SMTP_PASSWORD', '')
            
            if not smtp_user or not smtp_password:
                logger.warning("SMTP non configuré, email non envoyé")
                return False
            
            # Créer le message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = smtp_user
            msg['To'] = to_email
            
            # Ajouter le corps texte
            part1 = MIMEText(body, 'plain')
            msg.attach(part1)
            
            # Ajouter le corps HTML si fourni
            if html_body:
                part2 = MIMEText(html_body, 'html')
                msg.attach(part2)
            
            # Envoyer
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.send_message(msg)
            
            logger.info(f"Email envoyé à {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur envoi email: {e}")
            return False
    
    async def notify_application_status_change(
        self,
        db: Session,
        application: Application,
        old_status: str,
        new_status: str
    ):
        """Notifie le candidat d'un changement de statut de candidature."""
        user = application.user
        job_title = application.job.offre_brute.title if application.job.offre_brute else "Offre"
        
        # Messages selon le statut
        status_messages = {
            "shortlisted": {
                "title": "🎯 Votre candidature a été présélectionnée !",
                "message": f"Bonne nouvelle ! Votre candidature pour '{job_title}' a été présélectionnée."
            },
            "interview_scheduled": {
                "title": "📅 Entretien planifié",
                "message": f"Un entretien a été planifié pour votre candidature à '{job_title}'."
            },
            "offer_made": {
                "title": "🎉 Offre d'emploi reçue !",
                "message": f"Félicitations ! Une offre vous a été faite pour '{job_title}'."
            },
            "hired": {
                "title": "✅ Candidature acceptée !",
                "message": f"Félicitations ! Vous avez été retenu(e) pour '{job_title}'."
            },
            "rejected": {
                "title": "Candidature non retenue",
                "message": f"Malheureusement, votre candidature pour '{job_title}' n'a pas été retenue."
            }
        }
        
        notification_data = status_messages.get(new_status)
        
        if notification_data:
            # Créer notification in-app
            self.create_notification(
                db,
                user_id=user.id,
                type="application_status",
                title=notification_data["title"],
                message=notification_data["message"],
                action_url=f"/applications/{application.id}",
                extra_data={
                    "application_id": str(application.id),
                    "old_status": old_status,
                    "new_status": new_status
                }
            )
            
            # Envoyer email
            if user.email:
                await self.send_email(
                    to_email=user.email,
                    subject=notification_data["title"],
                    body=notification_data["message"] + f"\n\nConsultez votre candidature: {settings.FRONTEND_URL}/applications/{application.id}",
                    html_body=f"""
                    <html>
                        <body>
                            <h2>{notification_data["title"]}</h2>
                            <p>{notification_data["message"]}</p>
                            <p><a href="{settings.FRONTEND_URL}/applications/{application.id}">Voir ma candidature</a></p>
                        </body>
                    </html>
                    """
                )
    
    async def notify_new_application(
        self,
        db: Session,
        application: Application,
        recruiter_emails: List[str]
    ):
        """Notifie les recruteurs d'une nouvelle candidature."""
        job_title = application.job.offre_brute.title if application.job.offre_brute else "Offre"
        candidate_name = f"{application.user.profile.first_name} {application.user.profile.last_name}" if application.user.profile else "Candidat"
        
        for email in recruiter_emails:
            await self.send_email(
                to_email=email,
                subject=f"Nouvelle candidature: {job_title}",
                body=f"Une nouvelle candidature a été reçue de {candidate_name} pour le poste '{job_title}'.",
                html_body=f"""
                <html>
                    <body>
                        <h2>Nouvelle candidature</h2>
                        <p><strong>{candidate_name}</strong> a postulé pour <strong>{job_title}</strong></p>
                        <p><a href="{settings.FRONTEND_URL}/applications/{application.id}">Voir la candidature</a></p>
                    </body>
                </html>
                """
            )
    
    async def send_interview_reminder(
        self,
        db: Session,
        application: Application,
        hours_before: int = 24
    ):
        """Envoie un rappel d'entretien."""
        if not application.interview_date:
            return
        
        user = application.user
        job_title = application.job.offre_brute.title if application.job.offre_brute else "Offre"
        
        # Créer notification
        self.create_notification(
            db,
            user_id=user.id,
            type="interview_reminder",
            title="📅 Rappel: Entretien demain",
            message=f"N'oubliez pas votre entretien pour '{job_title}' prévu le {application.interview_date.strftime('%d/%m/%Y à %H:%M')}",
            action_url=f"/applications/{application.id}",
            extra_data={"application_id": str(application.id)}
        )
        
        # Envoyer email
        if user.email:
            await self.send_email(
                to_email=user.email,
                subject=f"Rappel: Entretien pour {job_title}",
                body=f"Bonjour,\n\nCeci est un rappel pour votre entretien concernant le poste '{job_title}' prévu le {application.interview_date.strftime('%d/%m/%Y à %H:%M')}.\n\nBonne chance !"
            )
