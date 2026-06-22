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
    
    def _get_base_email_html(
        self,
        title: str,
        content_html: str,
        action_url: Optional[str] = None,
        action_label: Optional[str] = None
    ) -> str:
        """Retourne un template HTML d'e-mail premium unifié."""
        action_button_html = ""
        if action_url and action_label:
            action_button_html = f"""
            <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 30px; margin-bottom: 10px; border-collapse: collapse;">
              <tr>
                <td align="center">
                  <a href="{action_url}" style="display: inline-block; background-color: #124E27; color: #ffffff; padding: 14px 32px; border-radius: 12px; font-weight: 700; font-size: 15px; text-decoration: none; font-family: sans-serif;">{action_label}</a>
                </td>
              </tr>
            </table>
            """
            
        return f"""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <title>{title}</title>
        </head>
        <body style="margin: 0; padding: 0; background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;">
          <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f1f5f9; padding: 30px 10px; border-collapse: collapse;">
            <tr>
              <td align="center">
                <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px; background-color: #ffffff; border-radius: 20px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05), 0 4px 6px -4px rgba(0, 0, 0, 0.05); overflow: hidden; border: 1px solid #e2e8f0; border-collapse: collapse;">
                  <!-- Header -->
                  <tr>
                    <td style="background: linear-gradient(135deg, #124E27 0%, #1c753b 100%); padding: 35px 40px; text-align: center;">
                      <h1 style="color: #ffffff; font-size: 28px; font-weight: 800; margin: 0; font-family: sans-serif; letter-spacing: -0.5px;">SunuSouba</h1>
                      <p style="color: #a7f3d0; font-size: 13px; font-weight: 600; margin: 8px 0 0 0; text-transform: uppercase; letter-spacing: 1.5px; font-family: sans-serif;">Notifications & Mises à jour</p>
                    </td>
                  </tr>
                  
                  <!-- Content -->
                  <tr>
                    <td style="padding: 40px 40px 30px 40px;">
                      {content_html}
                      {action_button_html}
                    </td>
                  </tr>
                  
                  <!-- Footer -->
                  <tr>
                    <td style="background-color: #f8fafc; padding: 30px 40px; border-top: 1px solid #e2e8f0; text-align: center;">
                      <p style="font-size: 12px; color: #94a3b8; margin: 0 0 10px 0; font-family: sans-serif;">Vous recevez cet e-mail suite à votre activité sur SunuSouba.</p>
                      <p style="font-size: 12px; color: #94a3b8; margin: 0; font-family: sans-serif;">
                        <a href="{settings.FRONTEND_URL}/candidate/settings" style="color: #124E27; text-decoration: underline; font-weight: 600;">Gérer mes alertes</a> • 
                        <a href="{settings.FRONTEND_URL}/contact" style="color: #124E27; text-decoration: underline; font-weight: 600;">Support</a>
                      </p>
                      <p style="font-size: 11px; color: #cbd5e1; margin-top: 20px; font-weight: 500; font-family: sans-serif;">&copy; {datetime.utcnow().year} SunuSouba. Tous droits réservés.</p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </body>
        </html>
        """

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
            # 1. Option alternative Resend par HTTP (nécessaire sur Render Free car SMTP (port 587) y est bloqué)
            resend_key = getattr(settings, 'RESEND_API_KEY', None)
            if resend_key:
                import requests
                payload = {
                    "from": "Sunusouba <no-reply@sunu-souba.com>",
                    "to": [to_email],
                    "subject": subject,
                    "text": body
                }
                if html_body:
                    payload["html"] = html_body
                
                try:
                    res = requests.post(
                        "https://api.resend.com/emails",
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {resend_key}",
                            "Content-Type": "application/json"
                        },
                        timeout=15
                    )
                    if res.status_code in [200, 201, 202]:
                        logger.info(f"Email envoyé avec succès via Resend HTTP API à {to_email}")
                        return True
                    else:
                        logger.error(f"Échec de l'envoi d'email via Resend HTTP API ({res.status_code}): {res.text}")
                except Exception as res_err:
                    logger.error(f"Erreur de connexion à l'API Resend : {res_err}")

            # 2. Configuration SMTP standard (fallback local ou si payant)
            smtp_host = getattr(settings, 'SMTP_HOST', 'smtp.gmail.com')
            smtp_port = getattr(settings, 'SMTP_PORT', 587)
            smtp_user = getattr(settings, 'SMTP_USER', '')
            smtp_password = getattr(settings, 'SMTP_PASSWORD', '')
            
            if not smtp_user or not smtp_password:
                logger.warning("SMTP non configuré et pas de clé Resend active, email non envoyé")
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
                "title": " Votre candidature a été présélectionnée !",
                "message": f"Bonne nouvelle ! Votre candidature pour '{job_title}' a été présélectionnée."
            },
            "interview_scheduled": {
                "title": " Entretien planifié",
                "message": f"Un entretien a été planifié pour votre candidature à '{job_title}'."
            },
            "offer_made": {
                "title": " Offre d'emploi reçue !",
                "message": f"Félicitations ! Une offre vous a été faite pour '{job_title}'."
            },
            "hired": {
                "title": " Candidature acceptée !",
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
                content_html = f"""
                <h2 style="color: #0f172a; margin: 0 0 16px 0; font-size: 20px; font-weight: 700; font-family: sans-serif;">{notification_data["title"]}</h2>
                <p style="white-space: pre-line; color: #475569; font-size: 15px; line-height: 1.6; font-family: sans-serif;">{notification_data["message"]}</p>
                """
                html_body = self._get_base_email_html(
                    title=notification_data["title"],
                    content_html=content_html,
                    action_url=f"{settings.FRONTEND_URL}/applications/{application.id}",
                    action_label="Voir ma candidature"
                )
                await self.send_email(
                    to_email=user.email,
                    subject=notification_data["title"],
                    body=notification_data["message"] + f"\n\nConsultez votre candidature: {settings.FRONTEND_URL}/applications/{application.id}",
                    html_body=html_body
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
            content_html = f"""
            <h2 style="color: #0f172a; margin: 0 0 16px 0; font-size: 20px; font-weight: 700; font-family: sans-serif;">Nouvelle candidature</h2>
            <p style="color: #475569; font-size: 15px; line-height: 1.6; font-family: sans-serif;"><strong>{candidate_name}</strong> a postulé pour le poste <strong>{job_title}</strong>.</p>
            """
            html_body = self._get_base_email_html(
                title=f"Nouvelle candidature: {job_title}",
                content_html=content_html,
                action_url=f"{settings.FRONTEND_URL}/applications/{application.id}",
                action_label="Voir la candidature"
            )
            await self.send_email(
                to_email=email,
                subject=f"Nouvelle candidature: {job_title}",
                body=f"Une nouvelle candidature a été reçue de {candidate_name} pour le poste '{job_title}'.",
                html_body=html_body
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
            title=" Rappel: Entretien demain",
            message=msg,
            action_url=f"/applications/{application.id}",
            extra_data={"application_id": str(application.id)}
        )
        
        # Envoyer email
        if user.email:
            content_html = f"""
            <h2 style="color: #0f172a; margin: 0 0 16px 0; font-size: 20px; font-weight: 700; font-family: sans-serif;">📅 Rappel d'entretien</h2>
            <p style="color: #475569; font-size: 15px; line-height: 1.6; font-family: sans-serif; white-space: pre-line;">Bonjour,

            Ceci est un rappel pour votre entretien concernant le poste <strong>'{job_title}'</strong>.
            
            <strong> Date :</strong> {application.interview_date.strftime('%d/%m/%Y à %H:%M')}
            <strong> Format :</strong> {fmt_map[application.interview_type] if application.interview_type in fmt_map else 'Non spécifié'}
            {location_info.strip()}
            {instructions_info.strip()}

            Bonne chance !</p>
            """
            html_body = self._get_base_email_html(
                title=f"Rappel: Entretien pour {job_title}",
                content_html=content_html,
                action_url=f"{settings.FRONTEND_URL}/applications/{application.id}",
                action_label="Consulter ma candidature"
            )
            await self.send_email(
                to_email=user.email,
                subject=f"Rappel: Entretien pour {job_title}",
                body=f"Bonjour,\n\nCeci est un rappel pour votre entretien concernant le poste '{job_title}' prévu le {application.interview_date.strftime('%d/%m/%Y à %H:%M')}.{location_info}{instructions_info}\n\nBonne chance !",
                html_body=html_body
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
            
        subject = f"{len(recommendations)} opportunités d'emploi qui vous correspondent"
        
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
            
            salary_badge_html = ""
            if salary_min:
                salary_str = f"{salary_min:,}"
                if salary_max:
                    salary_str += f" - {salary_max:,}"
                salary_badge_html = f"""
                <td width="8"></td>
                <td style="background-color: #f0fdf4; border-radius: 6px; padding: 4px 10px; font-size: 12px; font-weight: 600; color: #166534; font-family: sans-serif; white-space: nowrap;">
                  💵 {salary_str} FCFA
                </td>
                """
                
            badge_color = "#10b981" if score >= 80 else ("#f59e0b" if score >= 70 else "#6b7280")
            badge_color_light = "#ecfdf5" if score >= 80 else ("#fffbeb" if score >= 70 else "#f3f4f6")
            job_url = f"{settings.FRONTEND_URL}/candidate/job/{job_id}"
            
            recos_html += f"""
            <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom: 24px; background-color: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.02); border-collapse: collapse;">
              <tr>
                <td style="padding: 24px;">
                  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse;">
                    <tr>
                      <td style="vertical-align: top;">
                        <h3 style="margin: 0 0 4px 0; color: #0f172a; font-size: 17px; font-weight: 700; line-height: 1.4; font-family: sans-serif;">{title}</h3>
                        <p style="margin: 0 0 12px 0; color: #475569; font-size: 14px; font-weight: 600; font-family: sans-serif;">{company}</p>
                      </td>
                      <td align="right" valign="top" style="padding-left: 10px; vertical-align: top;">
                        <table role="presentation" cellpadding="0" cellspacing="0" style="background-color: {badge_color_light}; border-radius: 99px; border-collapse: collapse;">
                          <tr>
                            <td style="padding: 6px 14px; font-size: 12px; font-weight: 800; color: {badge_color}; text-align: center; white-space: nowrap; font-family: sans-serif;">
                              {score}% Match
                            </td>
                          </tr>
                        </table>
                      </td>
                    </tr>
                  </table>
                  
                  <table role="presentation" cellpadding="0" cellspacing="0" style="margin-bottom: 20px; border-collapse: collapse;">
                    <tr>
                      <td style="background-color: #f1f5f9; border-radius: 6px; padding: 4px 10px; font-size: 12px; font-weight: 600; color: #475569; font-family: sans-serif; white-space: nowrap;">
                        {contract_type}
                      </td>
                      <td width="8"></td>
                      <td style="background-color: #f1f5f9; border-radius: 6px; padding: 4px 10px; font-size: 12px; font-weight: 600; color: #475569; font-family: sans-serif; white-space: nowrap;">
                        📍 {location}
                      </td>
                      {salary_badge_html}
                    </tr>
                  </table>
                  
                  <table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse: collapse;">
                    <tr>
                      <td>
                        <a href="{job_url}" style="display: inline-block; background-color: #f0fdf4; color: #124E27; padding: 8px 18px; border-radius: 8px; font-size: 13px; font-weight: 700; text-decoration: none; border: 1px solid #bbf7d0; font-family: sans-serif;">Voir l'offre</a>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>
            """
            
        html_body = f"""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <title>Opportunités d'emploi SunuSouba</title>
        </head>
        <body style="margin: 0; padding: 0; background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;">
          <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f1f5f9; padding: 30px 10px; border-collapse: collapse;">
            <tr>
              <td align="center">
                <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px; background-color: #ffffff; border-radius: 20px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05), 0 4px 6px -4px rgba(0, 0, 0, 0.05); overflow: hidden; border: 1px solid #e2e8f0; border-collapse: collapse;">
                  <!-- Header -->
                  <tr>
                    <td style="background: linear-gradient(135deg, #124E27 0%, #1c753b 100%); padding: 35px 40px; text-align: center;">
                      <h1 style="color: #ffffff; font-size: 28px; font-weight: 800; margin: 0; font-family: sans-serif; letter-spacing: -0.5px;">SunuSouba</h1>
                      <p style="color: #a7f3d0; font-size: 13px; font-weight: 600; margin: 8px 0 0 0; text-transform: uppercase; letter-spacing: 1.5px; font-family: sans-serif;">Vos recommandations intelligentes</p>
                    </td>
                  </tr>
                  
                  <!-- Content -->
                  <tr>
                    <td style="padding: 40px 40px 30px 40px;">
                      <p style="font-size: 18px; font-weight: 700; color: #0f172a; margin-top: 0; margin-bottom: 12px; font-family: sans-serif;">Bonjour {candidate_name},</p>
                      <p style="font-size: 15px; line-height: 1.6; color: #475569; margin: 0 0 30px 0; font-family: sans-serif;">Notre intelligence artificielle a analysé votre profil et sélectionné <strong>{len(recommendations)} opportunités d'emploi</strong> qui correspondent parfaitement à vos compétences. Voici les meilleures offres du moment :</p>
                      
                      {recos_html}
                      
                      <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 20px; margin-bottom: 20px; border-collapse: collapse;">
                        <tr>
                          <td align="center">
                            <a href="{settings.FRONTEND_URL}/candidate/recommendations" style="display: inline-block; background-color: #124E27; color: #ffffff; padding: 14px 32px; border-radius: 12px; font-weight: 700; font-size: 15px; text-decoration: none; font-family: sans-serif;">Découvrir toutes les offres</a>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>
                  
                  <!-- Footer -->
                  <tr>
                    <td style="background-color: #f8fafc; padding: 30px 40px; border-top: 1px solid #e2e8f0; text-align: center;">
                      <p style="font-size: 12px; color: #94a3b8; margin: 0 0 10px 0; font-family: sans-serif;">Vous recevez cet e-mail suite à vos préférences de notifications sur SunuSouba.</p>
                      <p style="font-size: 12px; color: #94a3b8; margin: 0; font-family: sans-serif;">
                        <a href="{settings.FRONTEND_URL}/candidate/settings" style="color: #124E27; text-decoration: underline; font-weight: 600;">Gérer mes alertes</a> • 
                        <a href="{settings.FRONTEND_URL}/contact" style="color: #124E27; text-decoration: underline; font-weight: 600;">Support</a>
                      </p>
                      <p style="font-size: 11px; color: #cbd5e1; margin-top: 20px; font-weight: 500; font-family: sans-serif;">&copy; {datetime.utcnow().year} SunuSouba. Tous droits réservés.</p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </body>
        </html>
        """
        
        return await self.send_email(
            to_email=to_email,
            subject=subject,
            body=body_text,
            html_body=html_body
        )

