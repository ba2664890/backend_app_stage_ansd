import logging
import json
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from uuid import UUID

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
        
        # Prompt Système Maître
        self.system_prompt = """
        Tu es 'RH-Expert', l'Assistant IA complet pour la gestion des Ressources Humaines.
        Tu connais le droit du travail Sénégalais et les meilleures pratiques mondiales.
        Tes capacités :
        1. Rédiger des contrats, lettres, offres d'emploi.
        2. Analyser des CVs et extraire les compétences clés.
        3. Répondre aux questions sur les politiques internes de l'entreprise (si fourni en contexte).
        4. Proposer des grilles de salaire et des plans de carrière.
        Sois professionnel, précis et proactif.
        """

    async def process_chat(self, db: Session, recruiter_id: UUID, request: ChatRequest) -> Dict:
        """Point d'entrée principal du Chat."""
        question = request.question
        
        # 1. Vectorisation de la question
        query_embedding = self.embedder.embed_query(question)
        
        # 2. RAG : Recherche dans la base de connaissance interne
        internal_context = self.rag.search_knowledge(query_embedding, n_results=2)
        
        # 3. Construction du contexte pour le LLM
        context_str = ""
        if internal_context:
            context_str = "CONTEXTE INTERNE (Documents de l'entreprise) :\n"
            for doc in internal_context:
                context_str += f"- {doc['metadata'].get('title', 'Document')}: {doc['content']}\n"
        
        # 4. Génération de la réponse
        prompt = f"Question: {question}\n\n{context_str}"
        answer = self.llm.generate(self.system_prompt, prompt)
        
        # 5. Sauvegarde (comme avant)
        # ... (Code de sauvegarde DB ici) ...
        
        return {
            "answer": answer,
            "sources_used": [doc['metadata'].get('title') for doc in internal_context]
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
            cv_embedding = self.embedder.embed_documents([cv_text])[0]
            
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
                embedding=cv_embedding
            )
            
            # Nettoyage fichier temporaire si nécessaire (ou garder dans file_service)
            # await self.file_service.cleanup_file(file_path) # Optionnel
            
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
        # 1. Vectoriser l'offre
        job_embedding = self.embedder.embed_query(job_description_text)
        
        # 2. Chercher les CVs proches
        matches = self.rag.find_candidates_for_job(job_embedding, limit=5)
        
        if not matches:
            return {"message": "Aucun candidat correspondant trouvé dans la base.", "matches": []}
        
        # 3. Utiliser le LLM pour créer un rapport de matching
        match_report = []
        for match in matches:
            # On pourrait faire un appel LLM par match pour détailler, ou simplement retourner les données RAG
            # Pour aller vite, on format les données RAG
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

from datetime import datetime