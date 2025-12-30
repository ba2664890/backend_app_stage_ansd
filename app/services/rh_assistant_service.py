from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from uuid import UUID
import logging
import json

from ..models.database_models import RHChatHistory, Recruiter, OffreEmploiBrute
from ..models.api_models import ChatRequest, GenerateJobDescriptionRequest
from .llm_client import LLMClient
from .rag_service import RAGService

logger = logging.getLogger(__name__)

# Prompt Système pour définir la personnalité du bot RH
SYSTEM_PROMPT = """
Tu es l'Assistant RH Intelligence de 'Emploi Sénégal', un expert du marché du travail local.
Ton objectif est d'aider les recruteurs avec précision, empathie et professionnalisme.

Directives :
1. **Source de Vérité** : Utilise en priorité le contexte fourni (extraits d'offres d'emploi).
2. **Expertise Locale** : Tu connais les spécificités du Sénégal (villes, secteurs porteurs, droit du travail).
3. **Conversational** : Réponds de manière fluide. Ne te contente pas de lister, analyse et conseille.
4. **Action** : Propose des étapes concrètes (ex: "Je vous suggère de contacter ce profil car...").
5. **Honnêteté** : Si tu ne connais pas la réponse ou si le contexte est insuffisant, admets-le et propose une recherche complémentaire.
"""

class RHAssistantService:
    """Service pour l'assistant RH basé sur l'IA et RAG."""
    
    def __init__(self, llm_client: LLMClient, rag_service: RAGService):
        self.llm_client = llm_client
        self.rag_service = rag_service
    
    async def chat(
        self,
        db: Session,
        recruiter_id: UUID,
        chat_request: ChatRequest
    ) -> Dict:
        """
        Traite une question du recruteur.
        """
        question = chat_request.question
        context_data = chat_request.context or {}
        
        # 1. RAG : Rechercher des infos pertinentes dans la base vectorielle
        logger.info(f"Recherche RAG pour: {question}")
        rag_context = self.rag_service.search_context(question, n_results=5)
        
        # Formatage enrichi du contexte pour le LLM
        full_context = rag_context if rag_context else "Aucune offre spécifique trouvée dans la base de données actuelle pour cette requête."
        
        # 2. LLM : Générer la réponse
        answer = await self.llm_client.generate_response(
            system_prompt=SYSTEM_PROMPT,
            user_message=question,
            context=full_context
        )
        
        # 3. Sauvegarder l'historique
        chat_history = RHChatHistory(
            recruiter_id=recruiter_id,
            question=question,
            answer=answer,
            context={**context_data, "rag_sources_used": bool(rag_context)},
            model_used=self.llm_client.model,
            tokens_used=len(question) + len(answer) # Approximation simple
        )
        db.add(chat_history)
        db.commit()
        
        return {
            "answer": answer,
            "sources": "Base de données interne (Offres d'emploi)",
            "suggestions": self._generate_dynamic_suggestions(question)
        }
    
    def _generate_dynamic_suggestions(self, last_question: str) -> List[str]:
        """Génère des suggestions basées sur le contexte."""
        suggestions = [
            "Générer une description de poste pour un développeur Python",
            "Quelles sont les compétences les plus demandées en ce moment ?",
            "Analyser le profil d'un candidat"
        ]
        # Logique simple pour varier les suggestions
        if "salaire" in last_question.lower():
            suggestions.insert(0, "Comparer les salaires par secteur d'activité")
        return suggestions
    
    async def generate_job_description(
        self,
        db: Session,
        recruiter_id: UUID,
        request: GenerateJobDescriptionRequest
    ) -> Dict:
        """
        Génère une description de poste via LLM.
        """
        # Construction du prompt pour la génération
        prompt = f"""
        Rédige une offre d'emploi complète pour le poste de : {request.job_title}.
        Secteur : {request.sector or 'Non spécifié'}.
        Niveau d'expérience : {request.experience_level or 'Non spécifié'}.
        Contexte additionnel : {request.additional_context or ''}.
        
        Inclus les sections suivantes :
        1. Titre du poste
        2. À propos de nous
        3. Mission principale
        4. Responsabilités
        5. Compétences requises (Hard & Soft skills)
        6. Avantages
        """
        
        # Appel direct au LLM (Pas besoin de RAG ici, c'est de la création)
        job_description = await self.llm_client.generate_response(
            system_prompt="Tu es un expert en rédaction de RH.",
            user_message=prompt
        )
        
        # Ici, on pourrait appeler une méthode LLM forçant le JSON pour extraire skills et salaire
        # Pour l'exemple, on garde une structure simple ou simulée pour les suggestions
        
        # Sauvegarde
        chat_history = RHChatHistory(
            recruiter_id=recruiter_id,
            question=f"Générer description pour: {request.job_title}",
            answer=job_description,
            context=request.model_dump(),
            model_used=self.llm_client.model
        )
        db.add(chat_history)
        db.commit()
        
        return {
            "job_description": job_description,
            "suggested_skills": [], # Pourrait être rempli par un appel parse_llm_output(job_description)
            "suggested_salary_range": None
        }

    async def analyze_candidate(
        self,
        db: Session,
        recruiter_id: UUID,
        candidate_id: UUID,
        job_id: UUID
    ) -> Dict:
        """
        Analyse un candidat par rapport à une offre en utilisant le LLM.
        """
        # 1. Récupérer les données (Mock simplifié pour l'exemple, à adapter avec vos models)
        # candidate = db.query(UserProfile).filter(UserProfile.id == candidate_id).first()
        # job = db.query(OffreEmploiEnrichie).filter(OffreEmploiEnrichie.id == job_id).first()
        
        # Pour l'exemple, on simule le texte à envoyer au LLM
        candidate_text = "Candidat avec 3 ans d'expérience en Python, Django et PostgreSQL."
        job_text = "Nous cherchons un Dev Python Senior avec 5 ans d'expérience. Django requis."
        
        prompt = f"""
        Analyse ce matching :
        Candidat : {candidate_text}
        Offre : {job_text}
        
        Donne :
        1. Un score de matching (0-100).
        2. Les points forts.
        3. Les points faibles.
        4. 3 questions d'entretien suggérées.
        """
        
        # Utilisation de la méthode JSON pour structurer la réponse
        analysis_dict = await self.llm_client.generate_json_response(
            system_prompt="Tu es un expert en recrutement technique.",
            user_message=prompt
        )
        
        # Fallback si la réponse JSON échoue
        if not analysis_dict:
            return {
                "match_score": 0,
                "error": "Impossible d'analyser le profil actuellement."
            }
            
        return analysis_dict

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