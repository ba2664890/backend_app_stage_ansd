import os
import logging
from typing import List, Dict, Optional
import uuid
from pinecone import Pinecone

logger = logging.getLogger(__name__)

class RAGManager:
    """Gère la mémoire à long terme (RAG) avec Pinecone Inference."""
    
    def __init__(self):
        # Configuration Pinecone
        self.pinecone_api_key = os.getenv("PINECONE_API_KEY")
        self.index_name = os.getenv("PINECONE_INDEX_NAME") or "sunusouba"
        self.pinecone_model = "llama-text-embed-v2"
        
        # Namespaces séparés au sein du même index
        self.ns_knowledge = "company_knowledge"
        self.ns_cv = "candidate_cvs"
        
        self.pc = None
        self.index = None
        if self.pinecone_api_key:
            try:
                self.pc = Pinecone(api_key=self.pinecone_api_key)
                self.index = self.pc.Index(self.index_name)
            except Exception as e:
                logger.error(f"RAGManager: Erreur connexion Pinecone: {e}")

    def _get_embedding(self, text: str, input_type: str = "passage") -> List[float]:
        if not self.pc:
            raise ValueError("API Key Pinecone manquante pour l'inférence.")
            
        try:
            response = self.pc.inference.embed(
                model=self.pinecone_model,
                inputs=[text],
                parameters={"input_type": input_type}
            )
            return response.data[0].values
        except Exception as e:
            logger.error(f"Erreur lors de l'embedding Pinecone: {e}")
            raise e
        
    def add_internal_document(self, text: str, metadata: dict, doc_id: Optional[str] = None):
        """Ajoute un document interne (ex: extrait de code du travail)."""
        if not self.index:
            return
            
        if not doc_id:
            doc_id = str(uuid.uuid4())
            
        try:
            embedding = self._get_embedding(text, input_type="passage")
            meta = metadata.copy()
            meta["text_content"] = text
            self.index.upsert(
                vectors=[{
                    "id": doc_id,
                    "values": embedding,
                    "metadata": meta
                }],
                namespace=self.ns_knowledge
            )
        except Exception as e:
            logger.error(f"Erreur ajout document interne: {e}")

    def search_knowledge(self, query_text: str, n_results: int = 3) -> List[Dict]:
        """Cherche dans la base de connaissance interne."""
        if not self.index:
            return []
            
        try:
            query_embedding = self._get_embedding(query_text, input_type="query")
            results = self.index.query(
                vector=query_embedding,
                top_k=n_results,
                include_metadata=True,
                namespace=self.ns_knowledge
            )
            
            formatted_results = []
            for match in results.matches:
                formatted_results.append({
                    "content": match.metadata.get("text_content", ""),
                    "metadata": match.metadata,
                    "score": match.score
                })
            return formatted_results
        except Exception as e:
            logger.error(f"Erreur recherche knowledge: {e}")
            return []

    def index_cv(self, cv_id: str, text_content: str, metadata: dict, embedding: Optional[List[float]] = None):
        """Indexe un CV dans la base vectorielle."""
        if not self.index:
            return
            
        try:
            if not embedding:
                embedding = self._get_embedding(text_content, input_type="passage")
                
            meta = metadata.copy()
            meta["text_content"] = text_content
            self.index.upsert(
                vectors=[{
                    "id": cv_id,
                    "values": embedding,
                    "metadata": meta
                }],
                namespace=self.ns_cv
            )
        except Exception as e:
            logger.error(f"Erreur indexation CV {cv_id}: {e}")

    def find_candidates_for_job(self, job_description_text: str, limit: int = 5) -> List[Dict]:
        """Trouve les meilleurs candidats pour une offre donnée."""
        if not self.index:
            return []
            
        try:
            job_embedding = self._get_embedding(job_description_text, input_type="query")
            results = self.index.query(
                vector=job_embedding,
                top_k=limit,
                include_metadata=True,
                namespace=self.ns_cv
            )
            
            candidates = []
            for match in results.matches:
                content = match.metadata.get("text_content", "")
                candidates.append({
                    "cv_id": match.id,
                    "content_snippet": content[:200] + "..." if content else "",
                    "metadata": match.metadata,
                    "distance": 1.0 - match.score # Approximation de distance si score est cosine similarity
                })
            return candidates
        except Exception as e:
            logger.error(f"Erreur find_candidates: {e}")
            return []