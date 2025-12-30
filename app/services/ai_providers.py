import os
from typing import List
from groq import Groq
import logging
from sentence_transformers import SentenceTransformer # Pour une solution 100% locale et gratuite

# Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LLMProvider:
    """
    Client pour la génération de texte via Groq (Llama3 / Mixtral).
    Très rapide et gratuit pour l'instant.
    """
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY manquante. Allez sur console.groq.com pour en obtenir une gratuite.")
        self.client = Groq(api_key=self.api_key)
        # Modèles disponibles: "llama3-70b-8192", "mixtral-8x7b-32768"
        self.model = "llama3-70b-8192" 

    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.5) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=2000
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Erreur LLM: {e}")
            return "Erreur de connexion au service IA."

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        """Force la réponse en JSON structuré."""
        response_text = self.generate(
            system_prompt=f"{system_prompt} IMPORTANT: Réponds UNIQUEMENT en JSON valide.",
            user_prompt=user_prompt,
            temperature=0.1
        )
        try:
            import json
            return json.loads(response_text)
        except:
            return {"raw_text": response_text}

class EmbeddingProvider:
    """
    Client pour transformer le texte en vecteurs.
    Utilise 'all-MiniLM-L6-v2' en local pour être 100% gratuit et rapide.
    """
    def __init__(self):
        logger.info("Chargement du modèle d'embedding local...")
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.model.encode(texts).tolist()

    def embed_query(self, text: str) -> List[float]:
        return self.model.encode(text).tolist()