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
            # Enrichir dynamiquement le message d'entretien planifié
            if new_status == "interview_scheduled":
                details_str = ""
                if application.interview_date:
                    details_str += f" prévu le {application.interview_date.strftime('%d/%m/%Y à %H:%M')}."
                
                fmt_map = {"visio": "en visioconférence", "physical": "en présentiel", "phone": "par téléphone"}
                itype = application.interview_type
                if itype in fmt_map:
                    details_str += f" L'entretien se déroulera {fmt_map[itype]}."
                
                if itype == "visio" and application.interview_link:
                    details_str += f" Lien de connexion : {application.interview_link}"
                elif itype == "physical" and application.interview_address:
                    details_str += f" Adresse : {application.interview_address}"
                
                if application.interview_instructions:
                    details_str += f"\n\nConsignes : {application.interview_instructions}"
                
                notification_data["message"] = f"Un entretien a été planifié pour '{job_title}'" + details_str

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
                        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                            <h2 style="color: #1a5c32;">{notification_data["title"]}</h2>
                            <p style="white-space: pre-line;">{notification_data["message"]}</p>
                            <p style="margin-top: 24px;"><a href="{settings.FRONTEND_URL}/applications/{application.id}" style="background-color: #1a5c32; color: white; padding: 10px 18px; text-decoration: none; border-radius: 6px; font-weight: bold;">Voir ma candidature</a></p>
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
        
        fmt_map = {"visio": "visioconférence", "physical": "présentiel", "phone": "téléphone"}
        format_info = f" ({fmt_map[application.interview_type]})" if application.interview_type in fmt_map else ""
        
        location_info = ""
        if application.interview_type == "visio" and application.interview_link:
            location_info = f"\nLien de connexion : {application.interview_link}"
        elif application.interview_type == "physical" and application.interview_address:
            location_info = f"\nAdresse : {application.interview_address}"
            
        instructions_info = f"\nConsignes : {application.interview_instructions}" if application.interview_instructions else ""
        
        msg = f"N'oubliez pas votre entretien{format_info} pour '{job_title}' prévu le {application.interview_date.strftime('%d/%m/%Y à %H:%M')}.{location_info}{instructions_info}"
        
        # Créer notification
        self.create_notification(
            db,
            user_id=user.id,
            type="interview_reminder",
            title="📅 Rappel: Entretien demain",
            message=msg,
            action_url=f"/applications/{application.id}",
            extra_data={"application_id": str(application.id)}
        )
        
        # Envoyer email
        if user.email:
            await self.send_email(
                to_email=user.email,
                subject=f"Rappel: Entretien pour {job_title}",
                body=f"Bonjour,\n\nCeci est un rappel pour votre entretien concernant le poste '{job_title}' prévu le {application.interview_date.strftime('%d/%m/%Y à %H:%M')}.{location_info}{instructions_info}\n\nBonne chance !"
            )

    async def send_job_recommendations_email(
        self,
        to_email: str,
        candidate_name: str,
        recommendations: List[Dict]
    ) -> bool:
        """Envoie les meilleures recommandations d'emploi matchées par email."""
        if not recommendations:
            return False
            
        subject = f"🎯 {len(recommendations)} opportunités d'emploi qui vous correspondent"
        
        # Version texte brute
        body_text = f"Bonjour {candidate_name},\n\nVoici les meilleures offres d'emploi sélectionnées pour vous par notre IA :\n\n"
        for r in recommendations:
            title = r.get("title", "Offre d'emploi")
            company = r.get("company_name", "Entreprise")
            location = r.get("location", "Non spécifiée")
            score = r.get("match_score", 0)
            contract = r.get("contract_type", "Non spécifié")
            job_id = r.get("job_id")
            body_text += f"- {title} chez {company} ({location}) - Match {score}% - Contrat: {contract}\n"
            body_text += f"  Voir l'offre: {settings.FRONTEND_URL}/candidate/job/{job_id}\n\n"
        
        body_text += f"\nRetrouvez toutes vos recommandations sur : {settings.FRONTEND_URL}/candidate/recommendations"
        
        # Version HTML premium
        recos_html = ""
        for r in recommendations:
            title = r.get("title", "Offre d'emploi")
            company = r.get("company_name", "Entreprise")
            location = r.get("location", "Non spécifiée")
            score = r.get("match_score", 0)
            salary_min = r.get("salary_min")
            salary_max = r.get("salary_max")
            contract_type = r.get("contract_type", "Non spécifié")
            job_id = r.get("job_id")
            
            salary_str = ""
            if salary_min and salary_max:
                salary_str = f" • {salary_min:,} - {salary_max:,} FCFA"
            elif salary_min:
                salary_str = f" • Min. {salary_min:,} FCFA"
                
            badge_color = "#10b981" if score >= 80 else ("#f59e0b" if score >= 70 else "#6b7280")
            job_url = f"{settings.FRONTEND_URL}/candidate/job/{job_id}"
            
            recos_html += f"""
            <div style="border: 1px solid #e5e7eb; border-radius: 16px; padding: 18px; margin-bottom: 16px; background-color: #ffffff; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td>
                            <h3 style="margin: 0 0 6px 0; color: #111827; font-size: 18px; font-weight: 700; font-family: sans-serif;">{title}</h3>
                        </td>
                        <td style="text-align: right; vertical-align: top;">
                            <span style="background-color: {badge_color}1a; color: {badge_color}; padding: 6px 12px; border-radius: 8px; font-size: 12px; font-weight: 700; white-space: nowrap; font-family: sans-serif;">
                                {score}% Match
                            </span>
                        </td>
                    </tr>
                </table>
                <p style="margin: 0 0 8px 0; color: #4b5563; font-size: 14px; font-weight: 600; font-family: sans-serif;">{company} • {location}</p>
                <p style="margin: 0 0 16px 0; color: #6b7280; font-size: 13px; font-family: sans-serif;">Contrat : {contract_type}{salary_str}</p>
                <a href="{job_url}" style="display: inline-block; background-color: #1a5c32; color: #ffffff; padding: 10px 16px; text-decoration: none; border-radius: 8px; font-size: 13px; font-weight: 700; font-family: sans-serif;">Voir l'offre</a>
            </div>
            """
            
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; background-color: #f9fafb; padding: 20px;">
                <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 24px; padding: 32px; box-shadow: 0 4px 6px rgba(0,0,0,0.02);">
                    <div style="text-align: center; margin-bottom: 24px;">
                        <h2 style="color: #1a5c32; margin: 0; font-size: 24px; font-weight: 800;">SunuSouba</h2>
                        <p style="color: #6b7280; margin: 4px 0 0 0; font-size: 14px; font-weight: 600; text-transform: uppercase; tracking-wider: 0.1em;">Vos Recommandations Personnalisées</p>
                    </div>
                    <p style="font-size: 16px; color: #111827; font-weight: 600;">Bonjour {candidate_name},</p>
                    <p style="font-size: 14px; color: #4b5563; margin-bottom: 24px;">Notre intelligence artificielle a analysé le marché de l'emploi et a sélectionné ces opportunités qui correspondent parfaitement à vos compétences et à vos critères :</p>
                    
                    {recos_html}
                    
                    <div style="text-align: center; margin-top: 32px; padding-top: 24px; border-t: 1px solid #e5e7eb;">
                        <a href="{settings.FRONTEND_URL}/candidate/recommendations" style="display: inline-block; background-color: #1a5c32; color: white; padding: 12px 24px; text-decoration: none; border-radius: 12px; font-weight: bold; font-size: 14px;">Découvrir toutes les offres</a>
                    </div>
                </div>
            </body>
        </html>
        """
        
        return await self.send_email(
            to_email=to_email,
            subject=subject,
            body=body_text,
            html_body=html_body
        )

