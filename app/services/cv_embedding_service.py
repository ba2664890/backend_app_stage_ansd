import os
import logging
import numpy as np
from typing import List, Optional, Dict, Any
from uuid import UUID
from pinecone import Pinecone
from .cv_intelligent_extractor import CVExtractedData
from .llm_client import LLMClient

logger = logging.getLogger(__name__)

class CVEmbeddingService:
    """Service d'embedding avancé avec Pinecone Inference (llama-text-embed-v2) et contexte multimodal."""
    
    def __init__(self):
        # Configuration Pinecone
        self.pinecone_api_key = os.getenv("PINECONE_API_KEY")
        self.index_name = os.getenv("PINECONE_INDEX_NAME") or "sunusouba"
        self.job_namespace = "rh_knowledge_base"
        self.cv_namespace = "candidate_cvs"
        
        # Modèle d'embedding hébergé sur Pinecone
        self.pinecone_model = "llama-text-embed-v2"
        
        self.pc = None
        self.index = None
        if self.pinecone_api_key:
            try:
                self.pc = Pinecone(api_key=self.pinecone_api_key)
                self.index = self.pc.Index(self.index_name)
                logger.info(f"CVEmbeddingService connecté à Pinecone (Index: {self.index_name})")
            except Exception as e:
                logger.error(f"Erreur de connexion à Pinecone: {e}")

        # LLM pour la synthèse multimodale (optionnel, utilisé si images/liens complexes)
        self.llm = LLMClient()

    def _get_embedding(self, text: str, input_type: str = "passage") -> List[float]:
        """Génère l'embedding via l'API d'Inférence de Pinecone."""
        if not self.pc:
            logger.warning("Pinecone non configuré. Retourne un vecteur de zéros.")
            return [0.0] * 768 # llama-text-embed-v2 utilise généralement 1024 ou 768 dimensions, mais retourne 0 pour l'instant si désactivé
            
        try:
            # input_type peut être "query" ou "passage" pour les modèles de type e5 ou llama-embed
            response = self.pc.inference.embed(
                model=self.pinecone_model,
                inputs=[text],
                parameters={"input_type": input_type}
            )
            return response.data[0].values
        except Exception as e:
            logger.error(f"Erreur d'inférence Pinecone ({self.pinecone_model}): {e}")
            return []

    async def embed_cv(self, cv_data: CVExtractedData, visual_metadata: Optional[str] = None, links_metadata: Optional[str] = None) -> np.ndarray:
        """Génère l'embedding du CV en fusionnant texte, images (via metadata) et liens."""
        
        # Construction d'un profil sémantique dense
        semantic_profile = self._build_comprehensive_semantic_representation(
            cv_data=cv_data, 
            visual_metadata=visual_metadata, 
            links_metadata=links_metadata
        )
        
        # Appel à Pinecone Inference
        vector_list = self._get_embedding(semantic_profile, input_type="passage")
        
        if not vector_list:
             vector_list = [0.0] * 768
             
        return np.array(vector_list, dtype=np.float32)

    def _build_comprehensive_semantic_representation(self, cv_data: CVExtractedData, visual_metadata: str = None, links_metadata: str = None) -> str:
        """Construit un texte hautement structuré adapté aux LLMs et modèles d'embedding."""
        sections = [
            "=== PROFIL CANDIDAT ===",
            f"Titres cibles : {', '.join(cv_data.job_titles) if cv_data.job_titles else 'Non spécifié'}",
            f"Expérience validée : {cv_data.experience_years} ans",
            f"Secteurs d'activité : {', '.join(cv_data.sectors) if cv_data.sectors else 'Général'}",
            "",
            "=== COMPÉTENCES CLÉS ===",
            f"Technologies et Savoir-faire : {', '.join(cv_data.skills) if cv_data.skills else 'Non spécifié'}",
            ""
        ]
        
        if links_metadata:
            sections.extend([
                "=== PRÉSENCE EN LIGNE (PORTFOLIO / GITHUB) ===",
                links_metadata,
                ""
            ])
            
        if visual_metadata:
            sections.extend([
                "=== ANALYSE VISUELLE DU CV (IMAGES/DESIGN) ===",
                visual_metadata,
                ""
            ])
            
        sections.extend([
            "=== EXTRAIT DES EXPÉRIENCES (RÉSUMÉ) ===",
            # On prend un extrait propre du texte brut pour le contexte général
            cv_data.clean_text[:1500] 
        ])
        
        return "\n".join(sections)

    async def add_job_embedding(self, job_id: UUID, title: str, skills: List[str], description: str):
        """Pré-calcul et stockage de l'embedding job dans Pinecone."""
        if not self.index:
            return
            
        job_semantic = f"Offre d'emploi : {title}\nCompétences requises : {', '.join(skills[:15])}\nDescription : {(description or '')[:800]}"
        vector = self._get_embedding(job_semantic, input_type="passage")
        
        if vector:
            try:
                self.index.upsert(
                    vectors=[{
                        "id": str(job_id),
                        "values": vector,
                        "metadata": {
                            "title": title,
                            "skills": skills,
                            "type": "job"
                        }
                    }],
                    namespace=self.job_namespace
                )
            except Exception as e:
                logger.error(f"Erreur upsert Pinecone job: {e}")

    async def find_similar_jobs(self, cv_vector: np.ndarray, limit: int = 50, filter_sectors: List[str] = None) -> List[UUID]:
        """Recherche les jobs similaires."""
        if not self.index:
            return []
            
        try:
            # TODO: Ajouter un filtre sur metadata "sector" si filter_sectors est fourni (nécessite d'ajouter le secteur aux metadata de l'offre)
            results = self.index.query(
                vector=cv_vector.tolist(),
                top_k=limit,
                include_metadata=False,
                namespace=self.job_namespace
            )
            return [UUID(match.id) for match in results.matches]
        except Exception as e:
            logger.error(f"Erreur recherche jobs similaires: {e}")
            return []

    async def find_similar_cvs(self, job_embedding: np.ndarray, limit: int = 100) -> List[UUID]:
        """Recherche des candidats pour un job."""
        if not self.index:
            return []
            
        try:
            results = self.index.query(
                vector=job_embedding.tolist(),
                top_k=limit,
                include_metadata=False,
                namespace=self.cv_namespace
            )
            return [UUID(match.id) for match in results.matches]
        except Exception as e:
            logger.error(f"Erreur recherche CVs similaires: {e}")
            return []

    async def embed_job(self, title: str, skills: List[str], description: str) -> np.ndarray:
        """Génère l'embedding d'un job pour l'utiliser comme requête de recherche (query)."""
        skills = skills or []
        job_text = f"Recherche de candidat pour : {title}\nCompétences idéales : {', '.join(skills[:15])}\nContexte : {(description or '')[:500]}"
        
        # input_type="query" optimise le vecteur pour chercher dans la base (si le modèle le supporte)
        vector_list = self._get_embedding(job_text, input_type="query")
        
        if not vector_list:
            vector_list = [0.0] * 768
            
        return np.array(vector_list, dtype=np.float32)