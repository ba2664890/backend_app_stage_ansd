import os
import logging
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from pinecone import Pinecone, ServerlessSpec
from ..models.database_models import OffreEmploiBrute

logger = logging.getLogger(__name__)

class RAGService:
    """Service pour l'indexation et la recherche de documents (RAG) via Pinecone Inference."""
    
    def __init__(self):
        # Configuration Pinecone
        self.pinecone_api_key = os.getenv("PINECONE_API_KEY")
        self.index_name = os.getenv("PINECONE_INDEX_NAME") or "sunusouba"
        self.namespace = "rh_knowledge_base"
        self.pinecone_model = "llama-text-embed-v2"
        self.embedding_dimension = 768 # llama-text-embed-v2 peut être 1024, mais souvent 768 selon la configuration. Nous l'utilisons via inference.
        
        self.pc = None
        self.index = None
        
        if not self.pinecone_api_key:
            logger.warning("PINECONE_API_KEY non définie. Le RAG est désactivé.")
        else:
            try:
                self.pc = Pinecone(api_key=self.pinecone_api_key)
                # Note: nous ne créons pas l'index automatiquement ici car l'utilisateur a indiqué un index existant (sunusouba-g3a1r11)
                self.index = self.pc.Index(self.index_name)
                logger.info(f"RAGService connecté à l'index Pinecone: {self.index_name}, namespace: {self.namespace}")
            except Exception as e:
                logger.error(f"Erreur d'initialisation de Pinecone: {e}")
                self.pc = None
                self.index = None

    def _get_embedding(self, text: str, input_type: str = "passage") -> List[float]:
        """Génère l'embedding du texte via l'API Inférence Pinecone."""
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

    def get_count(self) -> int:
        """Retourne le nombre de documents indexés dans le namespace courant."""
        if not self.index:
            return 0
        stats = self.index.describe_index_stats()
        return stats.namespaces.get(self.namespace, {}).get("vector_count", 0)
        
    def index_offres_emploi(self, db: Session, limit: int = 1000, batch_size: int = 50):
        """Indexe les offres de la base SQL dans Pinecone par lots."""
        if not self.index:
            logger.warning("RAGService non initialisé, annulation de l'indexation.")
            return

        logger.info(f"Début de l'indexation des offres (limite: {limit}, lot: {batch_size})...")
        
        offres = db.query(OffreEmploiBrute).limit(limit).all()
        total_offres = len(offres)
        
        if total_offres == 0:
            logger.warning("Aucune offre à indexer.")
            return

        for i in range(0, total_offres, batch_size):
            batch = offres[i : i + batch_size]
            vectors_to_upsert = []
            
            for offre in batch:
                skills = offre.enrichie.extracted_skills if offre.enrichie and offre.enrichie.extracted_skills else []
                
                text_content = (
                    f"Titre: {offre.title}\n"
                    f"Entreprise: {offre.company_name}\n"
                    f"Description: {offre.description or ''}\n"
                    f"Compétences: {', '.join(skills) if skills else 'N/A'}\n"
                    f"Secteur: {offre.sector or 'Général'}\n"
                    f"Lieu: {offre.location or 'Sénégal'}\n"
                    f"Salaire: {offre.salary or 'Non spécifié'}"
                )
                
                try:
                    embedding = self._get_embedding(text_content, input_type="passage")
                    vectors_to_upsert.append({
                        "id": str(offre.id),
                        "values": embedding,
                        "metadata": {
                            "job_id": str(offre.id),
                            "title": offre.title or "Sans titre",
                            "company": offre.company_name or "Entreprise inconnue",
                            "sector": offre.sector or "Général",
                            "text_content": text_content
                        }
                    })
                except Exception as e:
                    logger.error(f"Erreur embedding offre {offre.id}: {e}")
            
            if vectors_to_upsert:
                try:
                    self.index.upsert(vectors=vectors_to_upsert, namespace=self.namespace)
                    logger.info(f"Lot indexé: {min(i + len(vectors_to_upsert), total_offres)}/{total_offres}")
                except Exception as e:
                    logger.error(f"Erreur d'upsert Pinecone: {e}")
        
        logger.info(f"Indexation terminée.")

    def search_context(self, query: str, n_results: int = 3) -> str:
        """Recherche des documents pertinents pour la requête."""
        if not self.index:
            return ""

        try:
            # Pour la requête, on utilise input_type="query"
            query_embedding = self._get_embedding(query, input_type="query")
            
            results = self.index.query(
                vector=query_embedding,
                top_k=n_results,
                include_metadata=True,
                namespace=self.namespace
            )
            
            if not results.matches:
                return ""
                
            context_parts = []
            for match in results.matches:
                meta = match.metadata
                doc_text = meta.get("text_content", "")
                context_parts.append(
                    f"Référence (Score: {match.score:.2f} | ID: {meta.get('job_id')} - {meta.get('title')} chez {meta.get('company')}):\n{doc_text}"
                )
            
            return "\n\n".join(context_parts)
            
        except Exception as e:
            logger.error(f"Erreur lors de la recherche RAG Pinecone: {e}")
            return ""