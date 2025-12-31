# cv_embedding_service.py
import numpy as np
from typing import List, Optional, Tuple
from uuid import UUID
import asyncio
from datetime import datetime
from .cv_intelligent_extractor import CVExtractedData
import os

class CVEmbeddingService:
    """Service d'embedding LÉGER (Stub) - Plus de Qdrant ni Transformers."""
    
    def __init__(self, 
                 model_name: str = "dangvantuan/sentence-camembert-base",
                 qdrant_url: str = None,
                 collection_prefix: str = "cv_jobs"):
        # On garde les arguments pour ne pas casser l'instanciation, mais on ne fait rien
        self.enabled = False
        print("⚠️ Mode LÉGER activé : Embeddings et Qdrant désactivés pour économiser les ressources.")

    async def embed_cv(self, cv_data: CVExtractedData) -> np.ndarray:
        """Retourne un vecteur vide."""
        return np.zeros(768, dtype=np.float32)

    async def add_job_embedding(self, job_id: UUID, title: str, skills: List[str], description: str):
        """No-op."""
        pass
    
    async def find_similar_jobs(self, cv_vector: np.ndarray, limit: int = 50) -> List[UUID]:
        """Retourne une liste vide."""
        return []
    
    async def find_similar_cvs(self, job_embedding: np.ndarray, limit: int = 100) -> List[UUID]:
        """Retourne une liste vide."""
        return []

    async def embed_job(self, title: str, skills: List[str], description: str) -> np.ndarray:
        """Retourne un vecteur vide."""
        return np.zeros(768, dtype=np.float32)

# ==================================================================================
# ARCHIVE : ANCIENNE IMPLEMENTATION (Désactivée pour économiser les ressources Railway)
# ==================================================================================
#
# import torch
# from sentence_transformers import SentenceTransformer
# from qdrant_client import QdrantClient, models
# 
# class CVEmbeddingService:
#     """Service d'embedding avec Qdrant pour stockage et recherche."""
#     
#     # Singleton pattern pour le modèle
#     _model_instance = None
#     _model_lock = asyncio.Lock()
#     
#     def __init__(self, 
#                  model_name: str = "dangvantuan/sentence-camembert-base",
#                  qdrant_url: str = None,
#                  collection_prefix: str = "cv_jobs"):
#         self.model_name = model_name
#         self.qdrant_url = qdrant_url or os.getenv("QDRANT_URL", "http://localhost:6333")
#         self.collection_prefix = collection_prefix
#         self.job_collection = f"{collection_prefix}_jobs"
#         self.cv_collection = f"{collection_prefix}_cvs"
#         self.enabled = False
#         
#         try:
#             self.qdrant = QdrantClient(self.qdrant_url)
#             # S'assurer que les collections existent
#             self._setup_collections()
#             self.enabled = True
#         except Exception as e:
#             print(f"⚠️ AVERTISSEMENT: Impossible de se connecter à Qdrant à {self.qdrant_url}. Le service d'embedding sera désactivé. Erreur: {e}")
#             self.qdrant = None
#     
#     def _setup_collections(self):
#         """Crée les collections Qdrant si elles n'existent pas."""
#         for collection in [self.job_collection, self.cv_collection]:
#             try:
#                 self.qdrant.get_collection(collection)
#             except Exception:
#                 self.qdrant.create_collection(
#                     collection_name=collection,
#                     vectors_config=models.VectorParams(
#                         size=768,
#                         distance=models.Distance.COSINE
#                     )
#                 )
#     
#     @classmethod
#     async def get_model(cls):
#         """Singleton thread-safe du modèle."""
#         if cls._model_instance is None:
#             async with cls._model_lock:
#                 if cls._model_instance is None:
#                     device = "cuda" if torch.cuda.is_available() else "cpu"
#                     cls._model_instance = SentenceTransformer(
#                         "dangvantuan/sentence-camembert-base",
#                         device=device
#                     )
#         return cls._model_instance
#     
#     async def embed_cv(self, cv_data: CVExtractedData) -> np.ndarray:
#         """Génère l'embedding du CV avec pondération de sections."""
#         model = await self.get_model()
#         
#         # Construire le texte avec poids
#         weighted_text = self._build_weighted_text(cv_data)
#         
#         # Embedding
#         vector = model.encode(
#             weighted_text,
#             convert_to_numpy=True,
#             normalize_embeddings=True
#         )
#         
#         return vector.astype(np.float32)
#     
#     def _build_weighted_text(self, cv_data: CVExtractedData) -> str:
#         """Donne plus de poids aux sections importantes."""
#         parts = []
#         
#         # Titres de poste (poids 3x)
#         if cv_data.job_titles:
#             parts.extend(cv_data.job_titles * 3)
#         
#         # Compétences (poids 2x)
#         if cv_data.skills:
#             parts.extend(cv_data.skills * 2)
#         
#         # Expérience brute
#         parts.append(cv_data.clean_text)
#         
#         return " | ".join(parts)[:1000]  # Truncate pour performance
#     
#         return " | ".join(parts)[:1000]  # Truncate pour performance
#     
#     async def add_job_embedding(self, job_id: UUID, title: str, skills: List[str], description: str):
#         """Pré-calcul et stockage de l'embedding job (appelé par vos spiders)."""
#         if not self.enabled:
#             return
#             
#         model = await self.get_model()
#         
#         # Construire texte job
#         job_text = f"{title} {' '.join(skills[:10])} {description[:300]}"
#         
#         vector = model.encode(job_text, convert_to_numpy=True)
#         
#         # Stocker dans Qdrant
#         self.qdrant.upsert(
#             collection_name=self.job_collection,
#             points=[models.PointStruct(
#                 id=str(job_id),
#                 vector=vector.tolist(),
#                 payload={
#                     "skills": skills,
#                     "title": title,
#                     "created_at": datetime.now().isoformat()
#                 }
#             )]
#         )
#     
#     async def find_similar_jobs(self, cv_vector: np.ndarray, limit: int = 50) -> List[UUID]:
#         """Recherche les jobs similaires en <10ms."""
#         if not self.enabled:
#             return []
#             
#         search_result = self.qdrant.search(
#             collection_name=self.job_collection,
#             query_vector=cv_vector.tolist(),
#             limit=limit,
#             score_threshold=0.65  # Filtre basique
#         )
#         
#         return [UUID(point.id) for point in search_result]
#     
#     async def find_similar_cvs(self, job_embedding: np.ndarray, limit: int = 100) -> List[UUID]:
#         """Pour le côté recruteur: trouver des candidats pour un job."""
#         if not self.enabled:
#             return []
#             
#         search_result = self.qdrant.search(
#             collection_name=self.cv_collection,
#             query_vector=job_embedding.tolist(),
#             limit=limit
#         )
#         
#         return [UUID(point.id) for point in search_result]
#
#     async def embed_job(self, title: str, skills: List[str], description: str) -> np.ndarray:
#         """Génère l'embedding d'un job pour la recherche."""
#         model = await self.get_model()
#         skills = skills or []
#         job_text = f"{title} {' '.join(skills[:10])} {(description or '')[:300]}"
#         
#         vector = model.encode(job_text, convert_to_numpy=True)
#         return vector.astype(np.float32)