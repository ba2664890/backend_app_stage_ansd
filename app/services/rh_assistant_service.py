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
        user_or_recruiter_id: UUID,
        chat_request: ChatRequest,
        user_role: str = 'recruiter'
    ) -> Dict:
        """
        Traite une question de l'utilisateur (recruteur ou candidat).
        """
        question = chat_request.question
        context_data = chat_request.context or {}
        
        # Définir le système prompt selon le rôle
        if user_role == 'candidate':
            system_prompt = """
Tu es l'Assistant Carrière de 'Emploi Sénégal', un expert en orientation professionnelle et recherche d'emploi.
Ton objectif est d'aider les candidats avec précision, empathie et encouragement.

Directives :
1. **Analyse Personnalisée** : Utilise le contexte fourni (profil, documents CVs/diplômes, offres recommandées) pour donner des conseils adaptés.
2. **Analyse Proactive** : Si tu vois le contenu d'un CV dans le contexte, ANALYSE-LE IMMÉDIATEMENT et fournis des retours détaillés (points forts, points faibles, suggestions d'amélioration).
3. **Expertise Locale** : Tu connais les spécificités du marché sénégalais (secteurs, villes, tendances, salaires).
4. **Encouragement** : Sois positif et motivant. Aide le candidat à surmonter les obstacles.
5. **Pratique** : Propose des actions concrètes (améliorer CV, préparer entretien, postuler à telle offre).
6. **Honnêteté** : Si tu ne connais pas quelque chose, admets-le et propose une recherche.
"""
        else:
            system_prompt = SYSTEM_PROMPT  # Prompt RH par défaut
        
        # 1. RAG : Rechercher des infos pertinentes dans la base vectorielle
        logger.info(f"Recherche RAG pour: {question} (role: {user_role})")
        
        # Pour les candidats, on pourrait chercher dans leurs documents aussi
        if user_role == 'candidate':
            # Récupérer le profil et les documents du candidat
            from ..models.database_models import UserProfile, Document
            
            profile = db.query(UserProfile).filter(UserProfile.user_id == user_or_recruiter_id).first()
            documents = db.query(Document).filter(Document.user_id == user_or_recruiter_id).limit(5).all()
            
            logger.info(f"🔍 Candidat {user_or_recruiter_id}: {len(documents)} documents trouvés dans la DB")
            
            # Contexte enrichi pour candidat
            candidate_context = f"Profil candidat: "
            if profile:
                candidate_context += f"{profile.first_name or ''} {profile.last_name or ''}, "
                candidate_context += f"Compétences: {', '.join(profile.skills or [])}. "
                candidate_context += f"Expérience: {profile.experience_years or 0} ans. "
                candidate_context += f"Localisation: {profile.location or 'Non spécifiée'}."
            
            # Lire le contenu des documents depuis la DB (pas depuis le filesystem)
            if documents:
                candidate_context += f"\n\nDocuments du candidat:\n"
                
                for doc in documents:
                    candidate_context += f"\n--- {doc.category.upper()}: {doc.name} ---\n"
                    
                    if doc.extracted_text:
                        # Texte déjà extrait et stocké en DB
                        logger.info(f"✅ Texte trouvé en DB pour {doc.name}: {len(doc.extracted_text)} caractères")
                        # Limiter à 2000 caractères pour éviter de surcharger le contexte
                        candidate_context += doc.extracted_text[:2000]
                        if len(doc.extracted_text) > 2000:
                            candidate_context += "\n[... contenu tronqué pour économiser les tokens ...]"
                        candidate_context += "\n"
                    else:
                        # Fallback : tenter d'extraire depuis le fichier (ancien système)
                        logger.warning(f"⚠️ Pas de texte extrait en DB pour {doc.name}, tentative d'extraction du fichier...")
                        try:
                            from .file_service import FileService
                            file_service = FileService()
                            doc_text = await file_service.extract_text_from_file(doc.file_path)
                            logger.info(f"✅ Extraction réussie depuis fichier: {len(doc_text)} caractères")
                            candidate_context += doc_text[:2000]
                            if len(doc_text) > 2000:
                                candidate_context += "\n[... contenu tronqué ...]"
                            candidate_context += "\n"
                        except Exception as e:
                            logger.error(f"❌ Impossible d'extraire le texte de {doc.name}: {e}")
                            candidate_context += f"[Document non accessible - veuillez le re-télécharger]\n"
            else:
                logger.warning(f"⚠️ Aucun document trouvé pour le candidat {user_or_recruiter_id}")
            
            # RAG sur les offres pertinentes
            rag_context = self.rag_service.search_context(question, n_results=3)
            full_context = f"{candidate_context}\n\n{rag_context if rag_context else 'Aucune offre spécifique trouvée.'}"
        else:
            # Mode recruteur : RAG classique sur toutes les offres
            rag_context = self.rag_service.search_context(question, n_results=5)
            full_context = rag_context if rag_context else "Aucune offre spécifique trouvée dans la base de données actuelle pour cette requête."
        
        # 2. LLM : Générer la réponse
        answer = await self.llm_client.generate_response(
            system_prompt=system_prompt,
            user_message=question,
            context=full_context
        )
        
        # 3. Sauvegarder l'historique
        if user_role == 'recruiter':
            chat_history = RHChatHistory(
                recruiter_id=user_or_recruiter_id,
                question=question,
                answer=answer,
                context={**context_data, "rag_sources_used": bool(rag_context if user_role == 'recruiter' else full_context)},
                model_used=self.llm_client.model,
                tokens_used=len(question) + len(answer)
            )
            db.add(chat_history)
            db.commit()
        # Note: Pour les candidats, on pourrait créer une table CandidateChatHistory séparée
        
        return {
            "answer": answer,
            "sources": ["Base de données interne (Offres d'emploi)", "Votre profil"] if user_role == 'candidate' else ["Base de données interne (Offres d'emploi)"],
            "suggestions": self._generate_dynamic_suggestions(question, user_role)
        }
    
    def _generate_dynamic_suggestions(self, last_question: str, user_role: str = 'recruiter') -> List[str]:
        """Génère des suggestions basées sur le contexte et le rôle."""
        if user_role == 'candidate':
            suggestions = [
                "Comment améliorer mon CV ?",
                "Quelles sont les compétences les plus demandées ?",
                "Comment me préparer à un entretien d'embauche ?"
            ]
            # Logique simple pour varier les suggestions
            if "cv" in last_question.lower():
                suggestions.insert(0, "Analyser mon CV et proposer des améliorations")
            elif "entretien" in last_question.lower():
                suggestions.insert(0, "Me donner des exemples de questions d'entretien")
        else:
            # Suggestions pour recruteurs
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