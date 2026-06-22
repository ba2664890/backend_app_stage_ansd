import sys
import os
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import json

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("recommendation_digests")

# Add project path to sys.path
sys.path.append(os.getcwd())

from app.database import SessionLocal
from app.models.database_models import UserProfile, User, UserRole
from app.services.recommendation_service import RecommendationService
from app.services.notification_service import NotificationService
from app.models.api_models import RecommendationRequest

async def run_digest_generation(db: Session) -> int:
    """
    Parcourt tous les candidats, vérifie s'ils doivent recevoir un digest,
    génère les offres correspondantes et leur envoie.
    Retourne le nombre d'e-mails envoyés.
    """
    logger.info("Démarrage du traitement des digests de recommandations...")
    
    # 1. Instancier les services
    rec_service = RecommendationService()
    notif_service = NotificationService()
    
    # 2. Récupérer tous les profils des utilisateurs candidats
    profiles = db.query(UserProfile).join(User).filter(User.role == UserRole.CANDIDATE).all()
    
    email_sent_count = 0
    now = datetime.utcnow()
    
    for profile in profiles:
        user = profile.user
        if not user or not user.email:
            continue
            
        # Parser les settings
        settings_data = profile.settings or {}
        notifications = settings_data.get("notifications", {})
        
        # Vérifier si les recommandations sont activées
        is_enabled = notifications.get("recommendations", True)
        if not is_enabled:
            continue
            
        frequency = notifications.get("recommendations_frequency", "weekly")
        if frequency == "disabled":
            continue
            
        # Vérifier la date du dernier envoi
        last_sent_str = notifications.get("last_recommendations_email_sent")
        should_send = False
        
        if not last_sent_str:
            # Premier envoi
            should_send = True
        else:
            try:
                last_sent = datetime.fromisoformat(last_sent_str)
                time_diff = now - last_sent
                
                if frequency == "daily":
                    # Si plus de 20 heures se sont écoulées
                    if time_diff >= timedelta(hours=20):
                        should_send = True
                elif frequency == "weekly":
                    # Si plus de 6 jours se sont écoulés
                    if time_diff >= timedelta(days=6):
                        should_send = True
            except Exception as e:
                logger.error(f"Erreur lors du parsing de la date du dernier envoi pour l'utilisateur {user.id}: {e}")
                should_send = True
                
        if should_send:
            logger.info(f"Génération des recommandations pour {user.email} ({frequency})...")
            try:
                # Créer une requête par défaut pour RecommendationRequest
                request_payload = RecommendationRequest(
                    limit=10,
                    min_match_score=0.5
                )
                
                # Récupérer les recommandations
                reco_response = rec_service.get_recommendations(db, str(user.id), request_payload)
                top_recos = reco_response.recommendations[:10]
                
                if not top_recos:
                    logger.info(f"Aucune recommandation trouvée pour {user.email}.")
                    continue
                    
                candidate_name = f"{profile.first_name}" if profile.first_name else "Candidat"
                
                # Formater les recommandations pour l'email
                recos_list = [
                    {
                        "title": r.title,
                        "company_name": r.company_name,
                        "location": r.location,
                        "match_score": int(r.match_score * 100),
                        "salary_min": r.salary_min,
                        "salary_max": r.salary_max,
                        "contract_type": r.contract_type or "Non spécifié",
                        "job_id": r.job_id
                    }
                    for r in top_recos
                ]
                
                # Envoyer l'email
                success = await notif_service.send_job_recommendations_email(
                    to_email=user.email,
                    candidate_name=candidate_name,
                    recommendations=recos_list
                )
                
                if success:
                    # Mettre à jour les paramètres pour stocker le timestamp de l'envoi
                    if "notifications" not in settings_data:
                        settings_data["notifications"] = {}
                    settings_data["notifications"]["last_recommendations_email_sent"] = now.isoformat()
                    profile.settings = settings_data
                    
                    db.add(profile)
                    db.commit()
                    
                    email_sent_count += 1
                    logger.info(f"Email envoyé avec succès à {user.email}.")
                else:
                    logger.error(f"Échec de l'envoi de l'email pour {user.email}.")
                    
            except Exception as ex:
                logger.error(f"Erreur lors de la génération/envoi pour {user.email}: {ex}")
                db.rollback()
                
    logger.info(f"Fin du traitement des digests de recommandations. {email_sent_count} emails envoyés.")
    return email_sent_count

async def main():
    db = SessionLocal()
    try:
        await run_digest_generation(db)
    finally:
        db.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
