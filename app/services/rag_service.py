import logging
import chromadb
from chromadb.config import Settings
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
import os
from ..models.database_models import OffreEmploiBrute

logger = logging.getLogger(__name__)

class RAGService:
    """Service pour l'indexation et la recherche de documents (RAG)."""
    
    def __init__(self, persist_directory: str = "./chroma_db"):
        # Initialisation de ChromaDB (Vector DB locale)
        os.makedirs(persist_directory, exist_ok=True)
        self.client = chromadb.PersistentClient(path=persist_directory)
        self.collection_name = "rh_knowledge_base"
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        
    def get_count(self) -> int:
        """Retourne le nombre de documents indexés."""
        return self.collection.count()
        
    def index_offres_emploi(self, db: Session, limit: int = 1000):
        """Indexe les offres de la base SQL dans la base vectorielle."""
        logger.info("Début de l'indexation des offres...")
        
        # Récupération des offres
        offres = db.query(OffreEmploiBrute).limit(limit).all()
        
        documents = []
        metadatas = []
        ids = []
        
        for offre in offres:
            # Création d'un texte enrichi pour la recherche
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
            logger.info(f"Indexation de {len(documents)} offres terminée.")
        else:
            logger.warning("Aucune offre à indexer.")

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