"""
Service pour la gestion de l'espace annonceur et du système de récompenses.
"""

import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from uuid import UUID
import uuid
from datetime import datetime

from ..models.database_models import (
    User, AdvertiserProfile, OffreEmploiBrute, OffreEmploiEnrichie,
    Reward, UserReward, PointTransaction, UserRole
)
from ..models.api_models import JobCreate, JobOfferResponse
from .job_service import JobService
from .llm_client import LLMClient
from .file_service import FileService

logger = logging.getLogger(__name__)

class AdvertiserService:
    def __init__(self, job_service: JobService, llm_client: LLMClient, file_service: FileService):
        """Initialise le service annonceur."""
        self.job_service = job_service
        self.llm_client = llm_client
        self.file_service = file_service

    def get_or_create_profile(self, db: Session, user_id: UUID) -> AdvertiserProfile:
        """Récupère ou crée le profil annonceur d'un utilisateur."""
        profile = db.query(AdvertiserProfile).filter(AdvertiserProfile.user_id == user_id).first()
        if not profile:
            profile = AdvertiserProfile(user_id=user_id, points=0, level=1)
            db.add(profile)
            db.commit()
            db.refresh(profile)
        return profile

    def add_points(self, db: Session, user_id: UUID, amount: int, reason: str) -> AdvertiserProfile:
        """Ajoute des points au profil de l'annonceur."""
        profile = self.get_or_create_profile(db, user_id)
        profile.points += amount
        profile.total_contributions += 1
        
        # Logique simple de montée de niveau : +1 niveau toutes les 5 contributions
        profile.level = (profile.total_contributions // 5) + 1
        
        transaction = PointTransaction(
            advertiser_id=profile.id,
            amount=amount,
            reason=reason
        )
        db.add(transaction)
        db.commit()
        return profile

    async def post_job_form(self, db: Session, user_id: UUID, job_data: JobCreate) -> JobOfferResponse:
        """Publie une offre via un formulaire et attribue des points."""
        # Note: On passe None pour recruiter_id et company_id car c'est un contributeur externe
        job_response = self.job_service.create_job(db, job_data, recruiter_id=None, company_id=None)
        
        # Mettre à jour le contributeur
        db_job = db.query(OffreEmploiBrute).filter(OffreEmploiBrute.id == job_response.id).first()
        db_job.contributor_id = user_id
        db.commit()
        
        self.add_points(db, user_id, 10, "job_post_form")
        return job_response

    async def post_job_file(self, db: Session, user_id: UUID, file_path: str) -> JobOfferResponse:
        """Extrait les infos d'un fichier, publie l'offre et attribue des points."""
        try:
            text = await self.file_service.extract_text_from_file(file_path)
            logger.info(f"Texte extrait du fichier ({len(text)} caractères)")
        except Exception as e:
            logger.error(f"Erreur extraction texte: {e}")
            raise ValueError(f"Impossible d'extraire le texte du fichier: {str(e)}")
        
        # Limiter le texte pour éviter les dépassements de tokens
        text_excerpt = text[:6000]
        
        # Extraire les infos via LLM avec prompt amélioré
        prompt = f"""Tu es un expert en analyse d'offres d'emploi au Sénégal. Extrais les informations structurées de cette offre d'emploi.

TEXTE DE L'OFFRE:
{text_excerpt}

INSTRUCTIONS:
1. Extrais UNIQUEMENT les informations présentes dans le texte
2. Pour les champs manquants, utilise null
3. Pour les salaires, convertis en FCFA si nécessaire
4. Pour les compétences, extrais une liste de 3-10 compétences clés
5. Pour la localisation, utilise les villes sénégalaises (Dakar, Thiès, Saint-Louis, etc.)

FORMAT JSON ATTENDU:
{{
    "title": "Titre exact du poste",
    "company_name": "Nom exact de l'entreprise",
    "location": "Ville au Sénégal",
    "contract_type": "CDI|CDD|Stage|Freelance|Apprentissage",
    "description": "Description complète du poste et des missions",
    "sector": "Secteur d'activité (Informatique, Finance, Santé, etc.)",
    "min_salary": 0,
    "max_salary": 0,
    "experience_years": 0,
    "education_level": "Bac +2|Bac +3|Bac +5|Doctorat|Autodidacte",
    "skills": ["compétence1", "compétence2", "compétence3"],
    "languages": ["Français", "Anglais"],
    "benefits": ["Avantage1", "Avantage2"],
    "remote_type": "onsite|hybrid|remote",
    "nb_positions": 1
}}

Réponds UNIQUEMENT avec le JSON, sans texte additionnel."""
        
        try:
            extracted_data = await self.llm_client.generate_json_response(
                system_prompt="Tu es un assistant expert en extraction de données d'emploi pour le marché sénégalais. Tu réponds toujours en JSON valide.",
                user_message=prompt
            )
        except Exception as e:
            logger.error(f"Erreur appel LLM: {e}")
            raise ValueError("Le service d'extraction IA est temporairement indisponible. Veuillez réessayer dans quelques instants.")
        
        # Validation renforcée
        if extracted_data is None:
            raise ValueError("L'extraction IA a échoué. Le service LLM n'a pas pu traiter le document. Vérifiez que le fichier contient du texte lisible.")
        
        if not isinstance(extracted_data, dict):
            logger.error(f"Type de données invalide reçu: {type(extracted_data)}")
            raise ValueError("L'extraction IA a retourné des données dans un format invalide.")
        
        if not extracted_data.get("title"):
            raise ValueError("Le titre du poste est manquant. Assurez-vous que le document contient un intitulé de poste clair.")
        
        if not extracted_data.get("company_name"):
            raise ValueError("Le nom de l'entreprise est manquant. Assurez-vous que le document mentionne l'entreprise.")
        
        # Nettoyage et normalisation des données (robuste aux valeurs None du LLM)
        cleaned_data = {
            "title": (extracted_data.get("title") or "").strip(),
            "company_name": (extracted_data.get("company_name") or "").strip(),
            "location": (extracted_data.get("location") or "Dakar").strip(),
            "contract_type": (extracted_data.get("contract_type") or "CDI").strip(),
            "description": (extracted_data.get("description") or "").strip() or f"Poste de {extracted_data.get('title')} chez {extracted_data.get('company_name')}",
            "sector": extracted_data.get("sector"),
            "min_salary": extracted_data.get("min_salary"),
            "max_salary": extracted_data.get("max_salary"),
            "experience_years": extracted_data.get("experience_years"),
            "education_level": extracted_data.get("education_level"),
            "skills": extracted_data.get("skills", []) if isinstance(extracted_data.get("skills"), list) else [],
            "languages": extracted_data.get("languages", []) if isinstance(extracted_data.get("languages"), list) else [],
            "benefits": extracted_data.get("benefits", []) if isinstance(extracted_data.get("benefits"), list) else [],
            "remote_type": (extracted_data.get("remote_type") or "onsite").strip(),
            "nb_positions": extracted_data.get("nb_positions") or 1
        }
        
        logger.info(f"Données extraites et nettoyées: title={cleaned_data['title']}, company={cleaned_data['company_name']}")
            
        job_create = JobCreate(**cleaned_data)
        job_response = self.job_service.create_job(db, job_create, recruiter_id=None, company_id=None)
        
        # Mettre à jour le contributeur
        db_job = db.query(OffreEmploiBrute).filter(OffreEmploiBrute.id == job_response.id).first()
        db_job.contributor_id = user_id
        db.commit()
        
        self.add_points(db, user_id, 20, "job_post_file")
        return job_response

    def list_rewards(self, db: Session) -> List[Reward]:
        """Liste les récompenses actives disponibles."""
        return db.query(Reward).filter(Reward.is_active == True).all()

    def claim_reward(self, db: Session, user_id: UUID, reward_id: UUID) -> UserReward:
        """Réclame une récompense en utilisant les points accumulés."""
        profile = self.get_or_create_profile(db, user_id)
        reward = db.query(Reward).filter(Reward.id == reward_id).first()
        
        if not reward or not reward.is_active:
            raise ValueError("Cette récompense n'est plus disponible.")
            
        if profile.points < reward.cost_points:
            raise ValueError(f"Points insuffisants. Il vous faut {reward.cost_points} points.")
            
        if reward.stock == 0:
            raise ValueError("Cette récompense est en rupture de stock.")
            
        # Débiter les points
        profile.points -= reward.cost_points
        if reward.stock > 0:
            reward.stock -= 1
            
        claim_code = f"RW-{uuid.uuid4().hex[:6].upper()}"
        user_reward = UserReward(
            advertiser_id=profile.id,
            reward_id=reward.id,
            claim_code=claim_code,
            status="claimed"
        )
        
        transaction = PointTransaction(
            advertiser_id=profile.id,
            amount=-reward.cost_points,
            reason=f"claim_reward: {reward.name}"
        )
        
        db.add(user_reward)
        db.add(transaction)
        db.commit()
        db.refresh(user_reward)
        return user_reward

    def get_stats(self, db: Session, user_id: UUID) -> Dict[str, Any]:
        """Récupère les statistiques et transactions de l'annonceur."""
        profile = self.get_or_create_profile(db, user_id)
        recent_transactions = db.query(PointTransaction).filter(
            PointTransaction.advertiser_id == profile.id
        ).order_by(PointTransaction.created_at.desc()).limit(15).all()
        
        claimed_rewards = db.query(UserReward).filter(
            UserReward.advertiser_id == profile.id
        ).order_by(UserReward.claimed_at.desc()).all()
        
        return {
            "profile": profile,
            "recent_transactions": recent_transactions,
            "claimed_rewards": claimed_rewards
        }
