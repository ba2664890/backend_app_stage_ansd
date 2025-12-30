import chromadb
from chromadb.config import Settings
from typing import List, Dict, Optional
import uuid
import logging

logger = logging.getLogger(__name__)

class RAGManager:
    """Gère la mémoire à long terme de l'entreprise (RAG)."""
    
    def __init__(self, persist_directory="./chroma_db"):
        self.client = chromadb.PersistentClient(path=persist_directory)
        
        # Collection pour les documents internes (RH, Légal)
        self.col_kb = self.client.get_or_create_collection(
            name="company_knowledge",
            metadata={"hnsw:space": "cosine"}
        )
        
        # Collection pour les CVs des candidats
        self.col_cv = self.client.get_or_create_collection(
            name="candidate_cvs",
            metadata={"hnsw:space": "cosine"}
        )
        
    def add_internal_document(self, text: str, metadata: dict, doc_id: Optional[str] = None):
        """Ajoute un document interne (ex: extrait de code du travail)."""
        if not doc_id:
            doc_id = str(uuid.uuid4())
        # Note: Les embeddings doivent être calculés avant si on utilise Chroma direct sans fonction custom
        # Ici on suppose l'utilisation d'une fonction d'embedding passée à chromadb ou calculée en amont.
        # Pour simplifier cet exemple, on utilise 'add' sans embedding explicite si le client Chroma est configuré pour,
        # mais en prod on passe les vecteurs calculés par EmbeddingProvider.
        pass 

    def search_knowledge(self, query_embedding: List[float], n_results: int = 3) -> List[Dict]:
        """Cherche dans la base de connaissance interne."""
        results = self.col_kb.query(
            query_embeddings=[query_embedding],
            n_results=n_results
        )
        
        formatted_results = []
        if results['documents']:
            for i in range(len(results['documents'][0])):
                formatted_results.append({
                    "content": results['documents'][0][i],
                    "metadata": results['metadatas'][0][i]
                })
        return formatted_results

    def index_cv(self, cv_id: str, text_content: str, metadata: dict, embedding: List[float]):
        """Indexe un CV dans la base vectorielle."""
        self.col_cv.add(
            ids=[cv_id],
            embeddings=[embedding],
            documents=[text_content],
            metadatas=[metadata]
        )

    def find_candidates_for_job(self, job_description_embedding: List[float], limit: int = 5) -> List[Dict]:
        """Trouve les meilleurs candidats pour une offre donnée."""
        results = self.col_cv.query(
            query_embeddings=[job_description_embedding],
            n_results=limit
        )
        
        candidates = []
        if results['documents']:
            for i in range(len(results['documents'][0])):
                # Calcul d'un score de distance simple (Cosine distance inversée)
                # Chroma renvoie la distance, plus c'est bas, mieux c'est
                candidates.append({
                    "cv_id": results['ids'][0][i],
                    "content_snippet": results['documents'][0][i][:200] + "...",
                    "metadata": results['metadatas'][0][i],
                    "distance": results['distances'][0][i]
                })
        return candidates