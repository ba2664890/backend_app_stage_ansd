import logging
import json
import uuid
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime

# Vos imports existants
from ..models.database_models import RHChatHistory, Recruiter, User, UserProfile
from ..models.api_models import ChatRequest
# On suppose que file_service.py est dans le même dossier
from .file_service import FileService
from .ai_providers import LLMProvider, EmbeddingProvider
from .rag_manager import RAGManager

logger = logging.getLogger(__name__)

class RHExpertService:
    def __init__(self):
        self.llm = LLMProvider()
        self.embedder = EmbeddingProvider()
        self.rag = RAGManager()
        self.file_service = FileService()
        
        # Prompt Système Maître révisé pour être plus naturel
        self.system_prompt = """
        Tu es 'RH-Expert', l'Assistant IA complet pour la gestion des Ressources Humaines.
        Tu connais le droit du travail Sénégalais et les meilleures pratiques mondiales.
        Tu communiques de façon naturelle, courtoise, professionnelle et directe.

        Directives :
        1. **Ton Naturel et Chaleureux** : Sois poli, humain et professionnel. Salue l'utilisateur ou remercie-le de manière conviviale et naturelle sans répétitions artificielles.
        2. **Adaptation de la Longueur** : Adapte la longueur de tes réponses au contexte :
           - Réponds de manière brève et polie aux salutations, remerciements ou remarques courtes (ex. "Bonjour ! Comment puis-je vous aider aujourd'hui ?").
           - Va droit au but pour les questions directes et simples.
           - Fournis des réponses détaillées, structurées et soignées pour les demandes complexes comme la rédaction de contrats ou de politiques internes.
        3. **Capacités** :
           - Rédiger des contrats, lettres, offres d'emploi.
           - Analyser des CVs et extraire les compétences clés.
           - Répondre aux questions sur les politiques internes de l'entreprise (si fourni en contexte).
           - Proposer des grilles de salaire et des plans de carrière.
        """

    async def should_use_rag(self, question: str) -> bool:
        """
        Détermine si la question de l'utilisateur nécessite une recherche d'information 
        dans la base de connaissances via RAG.
        """
        # Nettoyage et heuristiques simples pour les salutations/remerciements évidents (sans appel LLM)
        q = question.strip().lower().strip("?.! ")
        conversational_words = {
            "bonjour", "salut", "bonsoir", "hello", "hi", "hey",
            "merci", "merci beaucoup", "thanks", "thx", "d'accord", "ok", "okay",
            "cool", "parfait", "super", "génial", "oui", "non", "au revoir", "bye",
            "ca va", "comment ca va", "comment vas tu", "comment allez vous",
            "de rien", "je vous en prie", "pas de souci", "pas de probleme"
        }
        words = [w.strip("?,.!") for w in q.split()]
        if len(words) <= 3 and any(w in conversational_words for w in words):
            logger.info(f"RAG court-circuité par règle simple pour: '{question}'")
            return False
            
        if len(words) <= 1:
            logger.info(f"RAG court-circuité pour requête d'un mot: '{question}'")
            return False

        # Sinon, on demande au LLM d'analyser l'intention de la question de façon concise
        classification_prompt = (
            "Tu es un classificateur d'intention pour un chatbot RH au Sénégal. "
            "Détermine si la requête suivante nécessite de consulter la base de connaissances interne "
            "(le code du travail, les politiques internes, les CVs indexés ou contrats de travail).\n"
            "Réponds uniquement par 'OUI' si une recherche d'informations spécifiques est nécessaire, "
            "ou 'NON' s'il s'agit d'une salutation, d'une présentation de tes compétences ('qui es-tu', 'que peux-tu faire'), "
            "d'une phrase de politesse ou d'une question générale ne nécessitant pas de contexte particulier.\n"
            "Réponds UNIQUEMENT par 'OUI' ou 'NON'."
        )
        try:
            # self.llm.generate est synchrone
            response = self.llm.generate(
                system_prompt=classification_prompt,
                user_prompt=question,
                temperature=0.0
            )
            clean_response = response.strip().upper()
            logger.info(f"Classification RAG pour '{question}' : {clean_response}")
            return "OUI" in clean_response
        except Exception as e:
            logger.error(f"Erreur lors de la classification de l'intention RAG : {e}")
            return True  # Par défaut, on cherche si erreur

    async def process_chat(self, db: Session, recruiter_id: UUID, request: ChatRequest) -> Dict:
        """Point d'entrée principal du Chat."""
        question = request.question
        
        # 1. Analyse d'intention RAG
        use_rag = await self.should_use_rag(question)
        internal_context = []
        
        if use_rag:
            # 2. RAG : Recherche dans la base de connaissance interne
            # Correction : On passe la question brute (string) pour que RAGManager s'occupe de la vectorisation cohérente
            logger.info(f"Recherche RAG active pour : {question}")
            internal_context = self.rag.search_knowledge(question, n_results=2)
        else:
            logger.info(f"Recherche RAG ignorée pour la requête conversationnelle : {question}")
        
        # 3. Construction du contexte pour le LLM
        context_str = ""
        if internal_context:
            context_str = "CONTEXTE INTERNE (Documents de l'entreprise) :\n"
            for doc in internal_context:
                context_str += f"- {doc['metadata'].get('title', 'Document')}: {doc['content']}\n"
        
        # 4. Génération de la réponse
        prompt = f"Question: {question}\n\n{context_str}"
        answer = self.llm.generate(self.system_prompt, prompt)
        
        # 5. Sauvegarde
        try:
            chat_history = RHChatHistory(
                recruiter_id=recruiter_id,
                question=question,
                answer=answer,
                context={"rag_sources_used": bool(internal_context)},
                model_used=self.llm.model,
                tokens_used=len(question) + len(answer)
            )
            db.add(chat_history)
            db.commit()
        except Exception as e:
            logger.error(f"Erreur de sauvegarde historique RHExpertService: {e}")
        
        return {
            "answer": answer,
            "sources_used": [doc['metadata'].get('title') for doc in internal_context] if internal_context else []
        }

    async def upload_and_analyze_cv(
        self, 
        db: Session, 
        file, 
        recruiter_id: UUID
    ) -> Dict:
        """
        Pipeline complet d'upload d'un CV :
        1. Sauvegarde fichier (FileService)
        2. Extraction texte (FileService)
        3. Analyse LLM (Extraction Skills)
        4. Indexation Vectorielle (RAG)
        """
        try:
            # 1. Sauvegarde physique
            file_path = await self.file_service.save_upload_file(file)
            
            # 2. Extraction Texte
            cv_text = await self.file_service.extract_text_from_file(file_path)
            
            if not cv_text or len(cv_text) < 100:
                raise ValueError("Le texte extrait est trop court ou vide.")

            # 3. Analyse par LLM (Structured Extraction)
            analysis_prompt = f"""
            Analyse ce CV et extrait les informations au format JSON :
            {cv_text[:4000]} # Tronquer pour éviter de dépasser la limite contexte
            
            Format JSON attendu :
            {{
                "full_name": "Nom du candidat",
                "email": "Email",
                "phone": "Téléphone",
                "skills": ["compétence1", "compétence2"],
                "experience_years": nombre,
                "current_role": "Poste actuel",
                "education": ["Diplôme 1", "Diplôme 2"],
                "summary": "Résumé du profil en 3 lignes"
            }}
            """
            
            candidate_data = self.llm.generate_json(
                system_prompt="Tu es un expert en parsing de CV.",
                user_prompt=analysis_prompt
            )
            
            # 4. Indexation dans le RAG (pour recherches futures)
            # Correction : Laisser index_cv générer l'embedding avec le modèle de dimension correct (768)
            metadata = {
                "recruiter_id": str(recruiter_id),
                "file_name": file.filename,
                "upload_date": str(datetime.now()),
                "extracted_skills": json.dumps(candidate_data.get("skills", []))
            }
            
            self.rag.index_cv(
                cv_id=str(uuid.uuid4()), 
                text_content=cv_text, 
                metadata=metadata,
                embedding=None
            )
            
            return {
                "status": "success",
                "message": "CV analysé et indexé avec succès.",
                "candidate_profile": candidate_data
            }
            
        except Exception as e:
            logger.error(f"Erreur upload CV: {e}")
            raise e

    async def match_candidates_to_job(
        self, 
        db: Session, 
        job_description_text: str,
        recruiter_id: UUID
    ) -> Dict:
        """
        trouve les meilleurs candidats dans la base RAG pour une offre donnée.
        """
        # Correction : On passe directement le texte brut à find_candidates_for_job
        # pour éviter la vectorisation avec des dimensions de modèles incompatibles.
        matches = self.rag.find_candidates_for_job(job_description_text, limit=5)
        
        if not matches:
            return {"message": "Aucun candidat correspondant trouvé dans la base.", "matches": []}
        
        # 3. Utiliser le LLM pour créer un rapport de matching
        match_report = []
        for match in matches:
            match_report.append({
                "candidate_id": match['cv_id'],
                "score": round((1 - match['distance']) * 100, 2), # Cosine similarity approx
                "skills": match['metadata'].get('extracted_skills'),
                "snippet": match['content_snippet']
            })
            
        # 4. Génération d'un résumé global par le LLM
        summary_prompt = f"""
        Voici une liste de {len(matches)} candidats potentiels pour une offre.
        Offre : {job_description_text[:500]}
        
        Candidats trouvés :
        {json.dumps(match_report, indent=2)}
        
        Rédige un résumé pour le recruteur classant les 3 meilleurs profils avec leurs points forts.
        """
        
        ai_summary = self.llm.generate(
            system_prompt="Tu es un assistant recrutement.",
            user_prompt=summary_prompt
        )
        
        return {
            "matches": match_report,
            "ai_summary": ai_summary
        }

    async def generate_contract(self, contract_type: str, details: Dict) -> str:
        """Génère un contrat de travail juridique."""
        prompt = f"""
        Rédige un contrat de travail {contract_type} conforme au droit sénégalais.
        Détails :
        {json.dumps(details)}
        
        Inclus toutes les clauses légales nécessaires (période d'essai, préavis, congés, etc.).
        """
        return self.llm.generate(self.system_prompt, prompt)