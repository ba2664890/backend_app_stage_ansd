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
        
        points = 20 if getattr(job_data, "is_ocr_extracted", False) else 10
        reason = "job_post_file" if getattr(job_data, "is_ocr_extracted", False) else "job_post_form"
        self.add_points(db, user_id, points, reason)
        return job_response

    async def post_job_file(self, db: Session, user_id: UUID, file_path: str) -> JobCreate:
        """Extrait les infos d'un fichier (PDF/Word ou Image), publie l'offre et attribue des points."""
        import os
        file_ext = os.path.splitext(file_path)[1].lower()
        extracted_data = None
        
        # PROMPT COMMUN
        prompt_instruction = """Tu es un expert en analyse d'offres d'emploi au Sénégal. 
Extrais les informations structurées de ce document.
INSTRUCTIONS:
1. Extrais UNIQUEMENT les informations présentes
2. Pour les champs manquants, utilise null
3. Convertis les salaires en FCFA si nécessaire
4. Localisation: villes sénégalaises (Dakar, Thiès...)
5. Contrat: CDI, CDD, Stage, etc.

FORMAT JSON ATTENDU:
{
    "title": "Titre exact du poste",
    "company_name": "Nom exact de l'entreprise",
    "location": "Ville",
    "contract_type": "Type de contrat",
    "description": "Description complète",
    "sector": "Secteur",
    "min_salary": 0,
    "max_salary": 0,
    "experience_years": 0,
    "education_level": "Niveau",
    "skills": ["comp1", "comp2"],
    "languages": ["lang1"],
    "benefits": ["avantages"],
    "remote_type": "onsite|hybrid|remote",
    "nb_positions": 1
}"""

        # CAS 1: IMAGES (Vision)
        if file_ext in ['.jpg', '.jpeg', '.png', '.webp']:
            try:
                logger.info(f"Traitement d'image pour Vision: {file_path}")
                base64_image = await self.file_service.get_image_base64(file_path)
                extracted_data = await self.llm_client.generate_vision_response(
                    system_prompt="Tu es une IA experte en extraction de données depuis des photos d'annonces d'emploi.",
                    user_message=prompt_instruction,
                    base64_image=base64_image
                )
            except Exception as e:
                logger.error(f"Erreur Vision: {e}")
                raise ValueError(f"Erreur lors de l'analyse de l'image: {str(e)}")

        # CAS 2: DOCUMENTS TEXTE (PDF/DOC)
        else:
            try:
                text = await self.file_service.extract_text_from_file(file_path)
                logger.info(f"Texte extrait du fichier ({len(text)} caractères)")
                text_excerpt = text[:6000]
                
                full_prompt = f"{prompt_instruction}\n\nTEXTE DE L'OFFRE:\n{text_excerpt}"
                
                extracted_data = await self.llm_client.generate_json_response(
                    system_prompt="Tu es un assistant expert en extraction de données d'emploi.",
                    user_message=full_prompt
                )
            except Exception as e:
                logger.error(f"Erreur extraction texte: {e}")
                raise ValueError(f"Impossible d'extraire le texte du fichier: {str(e)}")

        # Validation commune
        if extracted_data is None:
            raise ValueError("L'extraction IA a échoué. Le service n'a pas pu traiter le document.")
        
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
        return JobCreate(**cleaned_data)

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
