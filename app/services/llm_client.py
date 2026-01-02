import os
from typing import List, Dict, Optional
from openai import AsyncOpenAI
import logging

logger = logging.getLogger(__name__)

class LLMClient:
    """Client pour interagir avec les LLM (OpenAI, Groq, etc)."""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None):
        # Priorité : Argument -> OPENAI_API_KEY -> XAI_API_KEY
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("XAI_API_KEY")
        
        # Configuration de l'URL et du modèle
        env_base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("XAI_BASE_URL")
        env_model = os.getenv("OPENAI_MODEL") or os.getenv("XAI_MODEL")
        
        if self.api_key and self.api_key.startswith("xai-"):
            self.base_url = base_url or env_base_url or "https://api.x.ai/v1"
            self.model = model or env_model or "grok-beta"
        else:
            self.base_url = base_url or env_base_url
            self.model = model or env_model or "gpt-4o-mini"
            
        if not self.api_key:
            logger.warning("Aucune clé API LLM définie. Le mode simulation sera utilisé.")
            self.client = None
        else:
            logger.info(f"Initialisation du client LLM avec le modèle: {self.model} sur {self.base_url}")
            self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    async def generate_response(
        self, 
        system_prompt: str, 
        user_message: str, 
        context: Optional[str] = None,
        temperature: float = 0.7
    ) -> str:
        """Génère une réponse du LLM."""
        
        # Construction du prompt
        messages = [{"role": "system", "content": system_prompt}]
        
        if context:
            # Injection du contexte RAG
            messages.append({
                "role": "system", 
                "content": f"Voici des informations contextuelles extraites de notre base de données pour t'aider :\n\n---\n{context}\n---"
            })
            
        messages.append({"role": "user", "content": user_message})

        # Mode simulation si pas de clé API
        if not self.client:
            return self._mock_response(user_message)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=1000
            )
            return response.choices[0].message.content
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Erreur LLM ({self.model}): {error_msg}")
            
            if "Incorrect API key" in error_msg:
                return "Erreur d'authentification avec le service IA. Veuillez vérifier la clé API."
            elif "rate_limit" in error_msg:
                return "Le service IA est actuellement surchargé. Veuillez réessayer dans quelques instants."
            
            return "Désolé, je rencontre une difficulté technique pour répondre actuellement. Essayez de reformuler votre question."

    async def generate_json_response(self, system_prompt: str, user_message: str) -> Dict:
        """Génère une réponse structurée en JSON avec gestion d'erreur robuste."""
        messages = [
            {"role": "system", "content": f"{system_prompt} Réponds UNIQUEMENT en JSON valide."},
            {"role": "user", "content": user_message}
        ]
        
        if not self.client:
            logger.warning("Mode simulation activé - pas de clé API LLM")
            return None

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=2000
            )
            
            content = response.choices[0].message.content
            logger.info(f"Réponse LLM brute: {content[:200]}...")
            
            import json
            parsed_data = json.loads(content)
            logger.info(f"JSON parsé avec succès: {list(parsed_data.keys())}")
            return parsed_data
            
        except json.JSONDecodeError as e:
            logger.error(f"Erreur de parsing JSON: {e}")
            logger.error(f"Contenu reçu: {content if 'content' in locals() else 'N/A'}")
            return None
        except Exception as e:
            logger.error(f"Erreur LLM JSON: {type(e).__name__}: {str(e)}")
            if hasattr(e, 'response'):
                logger.error(f"Détails de la réponse: {e.response}")
            return None

    def _mock_response(self, message: str) -> str:
        """Fallback si pas de clé API."""
        return (f"[SIMULATION] J'ai bien reçu votre message : '{message}'. "
                "En production, je ferais appel à l'API pour générer une réponse pertinente "
                "basée sur les offres d'emploi.")