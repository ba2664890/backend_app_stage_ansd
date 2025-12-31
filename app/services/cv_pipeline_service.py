# cv_pipeline_service.py
import logging
from typing import Optional, List, Dict
from dataclasses import dataclass
from uuid import UUID
import numpy as np

from .file_service import FileService
from .cv_intelligent_extractor import CVIntelligentExtractor, CVExtractedData
from .rag_service import RAGService
from .cv_embedding_service import CVEmbeddingService
from .llm_client import LLMClient
from .models.database_models import OffreEmploiBrute, OffreEmploiEnrichie
from .recommendation_service import RecommendationService

logger = logging.getLogger(__name__)

@dataclass
class CVPipelineResult:
    """Résultat enrichi du pipeline CV."""
    cv_data: CVExtractedData
    relevant_job_ids: List[UUID]
    recommendations: List[Dict]
    explanations: List[str]  # Généré par LLM
    embedding_vector: np.ndarray

class CVPipelineService:
    """Orchestre l'ensemble du pipeline CV de A à Z."""
    
    def __init__(self):
        self.file_service = FileService()
        self.extractor = CVIntelligentExtractor()
        self.rag_service = RAGService()
        self.embedding_service = CVEmbeddingService()
        self.llm_client = LLMClient()
        self.recommendation_service = RecommendationService()
    
    async def process_cv_from_upload(
        self, 
        file_path: str, 
        user_id: Optional[str] = None,
        generate_explanations: bool = True
    ) -> CVPipelineResult:
        """
        Pipeline complet: fichier → recommandations + explications IA.
        
        Args:
            file_path: Chemin du fichier CV
            user_id: ID utilisateur (optionnel)
            generate_explanations: Si True, génère des explications LLM
            
        Returns:
            Résultat enrichi avec embeddings et contexte
        """
        
        try:
            # Étape 1: Extraction texte (votre FileService)
            logger.info(f"Étape 1: Extraction texte depuis {file_path}")
            raw_text = await self.file_service.extract_text_from_file(file_path)
            
            if len(raw_text.strip()) < 100:
                raise ValueError("CV trop court ou illisible")
            
            # Étape 2: Extraction intelligente (spaCy)
            logger.info("Étape 2: Extraction structurée avec spaCy")
            cv_data = self.extractor.extract(raw_text)
            
            # Étape 3: Enrichissement avec contexte RAG
            logger.info("Étape 3: Récupération contexte jobs via RAG")
            context_jobs = self._get_relevant_job_context(cv_data)
            
            # Étape 4: Embedding vectoriel
            logger.info("Étape 4: Génération embedding")
            cv_vector = await self.embedding_service.embed_cv(cv_data)
            
            # Étape 5: Recherche rapide des jobs similaires
            logger.info("Étape 5: Recherche vectorielle jobs")
            job_ids = await self.embedding_service.find_similar_jobs(
                cv_vector, 
                limit=100,
                filter_sectors=cv_data.sectors  # Filtre par secteur
            )
            
            # Étape 6: Post-filtrage et scoring fin avec votre algo existant
            logger.info("Étape 6: Scoring fin avec RecommendationService")
            recommendations = await self._score_and_rank_jobs(
                job_ids, cv_data, cv_vector, user_id
            )
            
            # Étape 7: Génération d'explications via LLM (optionnelle mais puissante)
            explanations = []
            if generate_explanations:
                logger.info("Étape 7: Génération explications LLM")
                explanations = await self._generate_llm_explanations(
                    cv_data, recommendations[:3]  # Top 3 seulement
                )
            
            return CVPipelineResult(
                cv_data=cv_data,
                relevant_job_ids=job_ids,
                recommendations=recommendations,
                explanations=explanations,
                embedding_vector=cv_vector
            )
            
        except Exception as e:
            logger.error(f"Erreur pipeline CV: {e}", exc_info=True)
            raise
    
    def _get_relevant_job_context(self, cv_data: CVExtractedData) -> str:
        """Utilise votre RAGService pour obtenir des jobs de référence."""
        # Crée une requête enrichie
        query = f"""
        Compétences: {', '.join(cv_data.skills[:5])}
        Expérience: {cv_data.experience_years} ans
        Titres recherchés: {', '.join(cv_data.job_titles[:3])}
        """
        
        # Recherche dans ChromaDB
        return self.rag_service.search_context(query, n_results=3)
    
    async def _score_and_rank_jobs(
        self, 
        job_ids: List[UUID], 
        cv_data: CVExtractedData,
        cv_vector: np.ndarray,
        user_id: Optional[str]
    ) -> List[Dict]:
        """Combine votre scoring existant avec les embeddings."""
        
        # Récupération des jobs depuis PostgreSQL
        jobs = self.recommendation_service.db.query(
            OffreEmploiBrute, OffreEmploiEnrichie
        ).join(
            OffreEmploiEnrichie, OffreEmploiBrute.id == OffreEmploiEnrichie.offre_id
        ).filter(
            OffreEmploiEnrichie.id.in_(job_ids)
        ).all()
        
        scored_jobs = []
        for brute, enrichie in jobs:
            # 1. Similarité embedding (60%)
            job_vector = np.array(enrichie.embedding_vector) if enrichie.embedding_vector else None
            if job_vector is not None:
                sim_embedding = np.dot(cv_vector, job_vector)
            else:
                sim_embedding = 0.5  # Fallback pour jobs pas encore embarqués
            
            # 2. Votre scoring classique (40%) - Appelle votre méthode existante
            base_score, reasons = self.recommendation_service._calculate_match_score(
                user_profile=None,  # À adapter avec le profil utilisateur si disponible
                brute=brute,
                enrichie=enrichie,
                pre_normalized_user_skills=cv_data.skills
            )
            
            # Score final pondéré
            final_score = sim_embedding * 0.6 + base_score * 0.4
            
            scored_jobs.append({
                "job": (brute, enrichie),
                "score": final_score,
                "reasons": reasons,
                "embedding_similarity": sim_embedding
            })
        
        # Tri final
        return sorted(scored_jobs, key=lambda x: x["score"], reverse=True)
    
    async def _generate_llm_explanations(
        self, 
        cv_data: CVExtractedData, 
        top_recommendations: List[Dict]
    ) -> List[str]:
        """Utilise votre LLMClient pour générer des explications personnalisées."""
        
        explanations = []
        
        for rec in top_recommendations:
            brute, enrichie = rec["job"]
            
            # Construire le prompt
            system_prompt = """
            Vous êtes un assistant RH expert qui explique pourquoi une offre correspond à un CV.
            SOYEZ CONCIS (2-3 phrases max). Mettez en avant les points forts de matching.
            """
            
            user_prompt = f"""
            CV: Expérience {cv_data.experience_years}ans, Compétences: {', '.join(cv_data.skills[:5])}
            
            JOB: {brute.title} chez {brute.company_name}
            Compétences requises: {', '.join(enrichie.extracted_skills[:5])}
            Secteur: {enrichie.extracted_sector}
            
            Pourquoi ce job correspond-il ?
            """
            
            # Appeler LLM via votre service existant
            explanation = await self.llm_client.generate_response(
                system_prompt=system_prompt,
                user_message=user_prompt,
                temperature=0.3  # Peu créatif, très factuel
            )
            
            explanations.append(explanation)
        
        return explanations