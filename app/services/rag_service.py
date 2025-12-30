import logging
import chromadb
from chromadb.config import Settings
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from chromadb.utils import embedding_functions
import os
from ..models.database_models import OffreEmploiBrute

logger = logging.getLogger(__name__)

class RAGService:
    """Service pour l'indexation et la recherche de documents (RAG)."""
    
    def __init__(self, persist_directory: str = "./chroma_db"):
        # Initialisation de ChromaDB
        os.makedirs(persist_directory, exist_ok=True)
        self.client = chromadb.PersistentClient(path=persist_directory)
        
        # Utilisation des embeddings OpenAI (via proxy) pour économiser la RAM
        # On utilise les mêmes clés que le LLM
        api_key = os.getenv("XAI_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("XAI_BASE_URL", "https://api.openai.com/v1")
        
        self.embedding_fn = embedding_functions.OpenAIEmbeddingFunction(
            api_key=api_key,
            api_base=base_url,
            model_name="text-embedding-3-small"
        )
        
        self.collection_name = "rh_knowledge_base_v2" # Nouveau nom car dimension différente
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_fn,
            metadata={"hnsw:space": "cosine"}
        )
        
    def get_count(self) -> int:
        """Retourne le nombre de documents indexés."""
        return self.collection.count()
        
    def index_offres_emploi(self, db: Session, limit: int = 1000, batch_size: int = 50):
        """Indexe les offres de la base SQL dans la base vectorielle par lots."""
        logger.info(f"Début de l'indexation des offres (limite: {limit}, lot: {batch_size})...")
        
        # Récupération des offres
        offres = db.query(OffreEmploiBrute).limit(limit).all()
        total_offres = len(offres)
        
        if total_offres == 0:
            logger.warning("Aucune offre à indexer.")
            return

        for i in range(0, total_offres, batch_size):
            batch = offres[i : i + batch_size]
            documents = []
            metadatas = []
            ids = []
            
            for offre in batch:
                # Accès aux compétences via la relation enrichie si elle existe
                skills = offre.enrichie.extracted_skills if offre.enrichie and offre.enrichie.extracted_skills else []
                
                text_content = f"""
                Titre: {offre.title}
                Entreprise: {offre.company_name}
                Description: {offre.description or ''}
                Compétences: {', '.join(skills) if skills else 'N/A'}
                Secteur: {offre.sector or 'Général'}
                Lieu: {offre.location or 'Sénégal'}
                Salaire: {offre.salary or 'Non spécifié'}
                """
                
                documents.append(text_content)
                metadatas.append({
                    "job_id": str(offre.id),
                    "title": offre.title,
                    "company": offre.company_name,
                    "sector": offre.sector
                })
                ids.append(str(offre.id))
            
            if documents:
                self.collection.add(
                    documents=documents,
                    metadatas=metadatas,
                    ids=ids
                )
                logger.info(f"Lot indexé: {min(i + batch_size, total_offres)}/{total_offres}")
        
        logger.info(f"Indexation de {total_offres} offres terminée.")

    def search_context(self, query: str, n_results: int = 3) -> str:
        """Recherche des documents pertinents pour la requête."""
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results
            )
            
            if not results['documents'] or not results['documents'][0]:
                return ""
                
            context_parts = []
            for i, doc in enumerate(results['documents'][0]):
                meta = results['metadatas'][0][i]
                context_parts.append(
                    f"Référence (Offre ID: {meta['job_id']} - {meta['title']} chez {meta['company']}):\n{doc}"
                )
            
            return "\n\n".join(context_parts)
            
        except Exception as e:
            logger.error(f"Erreur lors de la recherche RAG: {e}")
            return ""