"""
Service pour l'assistant RH IA.
"""

from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from uuid import UUID
import logging
import json

from ..models.database_models import RHChatHistory, Recruiter
from ..models.api_models import ChatRequest, GenerateJobDescriptionRequest

logger = logging.getLogger(__name__)


class RHAssistantService:
    """Service pour l'assistant RH basé sur l'IA."""
    
    def __init__(self):
        # Configuration LLM (à adapter selon votre provider)
        self.model_name = "gpt-3.5-turbo"  # ou "groq/mixtral-8x7b-32768"
        self.max_tokens = 1000
    
    async def chat(
        self,
        db: Session,
        recruiter_id: UUID,
        chat_request: ChatRequest
    ) -> Dict:
        """
        Traite une question du recruteur et retourne une réponse.
        
        Args:
            db: Session de base de données
            recruiter_id: ID du recruteur
            chat_request: Requête de chat
            
        Returns:
            Dict: Réponse avec answer, sources, suggestions
        """
        question = chat_request.question
        context = chat_request.context or {}
        
        # TODO: Intégrer avec un vrai LLM (OpenAI, Groq, etc.)
        # Pour l'instant, réponse simulée
        answer = self._generate_mock_answer(question, context)
        
        # Sauvegarder l'historique
        chat_history = RHChatHistory(
            recruiter_id=recruiter_id,
            question=question,
            answer=answer,
            context=context,
            model_used=self.model_name,
            tokens_used=len(question) + len(answer)  # Approximation
        )
        db.add(chat_history)
        db.commit()
        
        return {
            "answer": answer,
            "sources": ["Base de données interne", "Statistiques du marché"],
            "suggestions": [
                "Quels sont les candidats les plus qualifiés ?",
                "Analyse des compétences manquantes",
                "Tendances salariales pour ce poste"
            ]
        }
    
    def _generate_mock_answer(self, question: str, context: Dict) -> str:
        """Génère une réponse simulée (à remplacer par un vrai LLM)."""
        question_lower = question.lower()
        
        if "candidat" in question_lower or "profil" in question_lower:
            return ("Basé sur les données actuelles, je recommande de prioriser les candidats "
                   "avec 3-5 ans d'expérience dans le secteur. Les compétences clés à rechercher "
                   "sont Python, FastAPI, et PostgreSQL.")
        
        elif "salaire" in question_lower or "rémunération" in question_lower:
            return ("Pour ce type de poste au Sénégal, la fourchette salariale médiane est "
                   "entre 800 000 et 1 500 000 FCFA/mois selon l'expérience.")
        
        elif "compétence" in question_lower or "skill" in question_lower:
            return ("Les compétences les plus demandées actuellement sont : "
                   "1) Développement web (React, Vue.js), "
                   "2) Data Science (Python, ML), "
                   "3) Cloud (AWS, Azure).")
        
        else:
            return ("Je suis votre assistant RH. Je peux vous aider avec l'analyse des candidatures, "
                   "les recommandations de recrutement, les tendances du marché, et bien plus.")
    
    async def generate_job_description(
        self,
        db: Session,
        recruiter_id: UUID,
        request: GenerateJobDescriptionRequest
    ) -> Dict:
        """
        Génère une description de poste basée sur les paramètres.
        
        Args:
            db: Session de base de données
            recruiter_id: ID du recruteur
            request: Paramètres de génération
            
        Returns:
            Dict: Description générée avec compétences et salaire suggérés
        """
        # TODO: Utiliser un vrai LLM pour générer la description
        job_description = self._generate_mock_job_description(request)
        
        suggested_skills = self._suggest_skills(request.job_title, request.sector)
        suggested_salary = self._suggest_salary_range(request.job_title, request.experience_level)
        
        # Sauvegarder dans l'historique
        chat_history = RHChatHistory(
            recruiter_id=recruiter_id,
            question=f"Générer description pour: {request.job_title}",
            answer=job_description,
            context=request.model_dump(),
            model_used=self.model_name,
            tokens_used=len(job_description)
        )
        db.add(chat_history)
        db.commit()
        
        return {
            "job_description": job_description,
            "suggested_skills": suggested_skills,
            "suggested_salary_range": suggested_salary
        }
    
    def _generate_mock_job_description(self, request: GenerateJobDescriptionRequest) -> str:
        """Génère une description de poste simulée."""
        return f"""**{request.job_title}**

**À propos du poste:**
Nous recherchons un(e) {request.job_title} talentueux(se) pour rejoindre notre équipe dynamique.

**Responsabilités:**
- Participer activement au développement et à l'amélioration de nos solutions
- Collaborer avec les équipes techniques et métier
- Assurer la qualité et la performance des livrables
- Contribuer à l'innovation et aux bonnes pratiques

**Profil recherché:**
- Expérience: {request.experience_level or '2-5 ans'}
- Secteur: {request.sector or 'Technologie'}
- Compétences techniques solides
- Excellentes capacités de communication
- Esprit d'équipe et autonomie

**Ce que nous offrons:**
- Environnement de travail stimulant
- Opportunités de développement professionnel
- Rémunération attractive
- Avantages sociaux compétitifs

{request.additional_context or ''}
"""
    
    def _suggest_skills(self, job_title: str, sector: Optional[str]) -> List[str]:
        """Suggère des compétences basées sur le titre et secteur."""
        # Mapping simplifié (à améliorer avec ML/LLM)
        skills_map = {
            "développeur": ["Python", "JavaScript", "SQL", "Git", "API REST"],
            "data": ["Python", "SQL", "Machine Learning", "Pandas", "Visualization"],
            "rh": ["Recrutement", "Gestion des talents", "SIRH", "Droit du travail"],
            "commercial": ["Négociation", "CRM", "Prospection", "Closing"],
        }
        
        job_lower = job_title.lower()
        for key, skills in skills_map.items():
            if key in job_lower:
                return skills
        
        return ["Communication", "Travail d'équipe", "Autonomie", "Adaptabilité"]
    
    def _suggest_salary_range(
        self,
        job_title: str,
        experience_level: Optional[str]
    ) -> Optional[Dict[str, int]]:
        """Suggère une fourchette salariale."""
        # Données simplifiées pour le Sénégal (FCFA/mois)
        base_salary = 500000
        
        if "senior" in (experience_level or "").lower() or "lead" in job_title.lower():
            return {"min": 1200000, "max": 2500000}
        elif "junior" in (experience_level or "").lower():
            return {"min": 400000, "max": 800000}
        else:
            return {"min": 700000, "max": 1500000}
    
    def get_chat_history(
        self,
        db: Session,
        recruiter_id: UUID,
        limit: int = 50
    ) -> List[RHChatHistory]:
        """Récupère l'historique des conversations."""
        return db.query(RHChatHistory).filter(
            RHChatHistory.recruiter_id == recruiter_id
        ).order_by(RHChatHistory.created_at.desc()).limit(limit).all()
    
    async def analyze_candidate(
        self,
        db: Session,
        recruiter_id: UUID,
        candidate_id: UUID,
        job_id: UUID
    ) -> Dict:
        """
        Analyse un candidat par rapport à une offre.
        
        Returns:
            Dict: Analyse avec points forts, points faibles, recommandations
        """
        # TODO: Implémenter analyse IA réelle
        return {
            "match_score": 0.85,
            "strengths": [
                "Expérience pertinente de 4 ans",
                "Compétences techniques alignées",
                "Formation adaptée"
            ],
            "weaknesses": [
                "Manque d'expérience en leadership",
                "Pas de certification spécifique"
            ],
            "recommendations": [
                "Planifier un entretien technique",
                "Vérifier les références professionnelles",
                "Discuter des attentes salariales"
            ],
            "interview_questions": [
                "Pouvez-vous décrire votre projet le plus complexe ?",
                "Comment gérez-vous les deadlines serrés ?",
                "Quelles sont vos attentes pour ce poste ?"
            ]
        }
