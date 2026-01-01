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
        text = await self.file_service.extract_text_from_file(file_path)
        
        # Extraire les infos via LLM
        prompt = f"""
        Extrais les informations de cette offre d'emploi au format JSON.
        Texte : {text[:4000]}
        
        Format attendu :
        {{
            "title": "Titre du poste (obligatoire)",
            "company_name": "Nom de l'entreprise (obligatoire)",
            "location": "Ville/Région",
            "contract_type": "CDI/CDD/Stage/etc",
            "description": "Description complète du poste",
            "sector": "Secteur d'activité",
            "min_salary": 0,
            "max_salary": 0,
            "experience_years": 0,
            "skills": ["compétence1", "compétence2"]
        }}
        """
        
        extracted_data = await self.llm_client.generate_json_response(
            system_prompt="Tu es un assistant expert en extraction de données d'emploi.",
            user_message=prompt
        )
        
        # Validation minimale
        if not extracted_data or not extracted_data.get("title") or not extracted_data.get("company_name"):
            logger.error(f"Extraction LLM échouée ou incomplète: {extracted_data}")
            raise ValueError("Impossible d'extraire les informations essentielles du fichier. Assurez-vous que le document contient l'intitulé du poste et le nom de l'entreprise.")
            
        job_create = JobCreate(**extracted_data)
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
