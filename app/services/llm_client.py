import os
import json
import logging
from typing import List, Dict, Optional
import google.generativeai as genai
from google.generativeai.types import GenerationConfig

logger = logging.getLogger(__name__)

class LLMClient:
    """Client pour interagir avec les modèles Google Gemini (Génération et Vision)."""
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model or os.getenv("GEMINI_MODEL") or "gemini-1.5-flash"
        
        if not self.api_key:
            logger.warning("Aucune clé GEMINI_API_KEY définie. Le mode simulation sera utilisé.")
            self.client_ready = False
        else:
            logger.info(f"Initialisation du client LLM avec le modèle Gemini: {self.model_name}")
            genai.configure(api_key=self.api_key)
            self.client_ready = True
            self.model = genai.GenerativeModel(self.model_name)

    async def generate_response(
        self, 
        system_prompt: str, 
        user_message: str, 
        context: Optional[str] = None,
        temperature: float = 0.7
    ) -> str:
        """Génère une réponse du LLM Gemini."""
        if not self.client_ready:
            return self._mock_response(user_message)

        prompt_parts = [
            f"INSTRUCTION SYSTÈME:\n{system_prompt}\n\n"
        ]
        
        if context:
            prompt_parts.append(
                f"CONTEXTE (extrait de la base de données):\n---\n{context}\n---\n\n"
            )
            
        prompt_parts.append(f"REQUÊTE UTILISATEUR:\n{user_message}")
        full_prompt = "".join(prompt_parts)

        try:
            # Pour google-generativeai, les appels asynchrones utilisent generate_content_async
            response = await self.model.generate_content_async(
                full_prompt,
                generation_config=GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=1000
                )
            )
            return response.text
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Erreur Gemini LLM: {error_msg}")
            if "API_KEY_INVALID" in error_msg or "403" in error_msg:
                return "Erreur d'authentification avec le service IA. Veuillez vérifier la clé API."
            elif "429" in error_msg:
                return "Le service IA est actuellement surchargé. Veuillez réessayer dans quelques instants."
            return "Désolé, je rencontre une difficulté technique pour répondre actuellement."

    async def generate_json_response(self, system_prompt: str, user_message: str) -> Dict:
        """Génère une réponse structurée en JSON avec Gemini."""
        if not self.client_ready:
            logger.warning("Mode simulation activé - pas de clé API LLM")
            raise ValueError(
                "Le service d'extraction IA n'est pas configuré. "
                "Veuillez utiliser le formulaire manuel pour publier votre offre."
            )

        full_prompt = (
            f"INSTRUCTION SYSTÈME:\n{system_prompt}\n\n"
            "IMPORTANT: Réponds EXCLUSIVEMENT avec un objet JSON valide, sans balises markdown.\n\n"
            f"REQUÊTE UTILISATEUR:\n{user_message}"
        )

        try:
            response = await self.model.generate_content_async(
                full_prompt,
                generation_config=GenerationConfig(
                    temperature=0.3,
                    max_output_tokens=2000,
                    response_mime_type="application/json"
                )
            )
            
            content = response.text
            logger.info(f"Réponse LLM (JSON) brute: {content[:200]}...")
            
            # Nettoyage de sécurité
            json_text = content.strip()
            if json_text.startswith("```"):
                lines = json_text.splitlines()
                if lines[0].startswith("```"): lines = lines[1:]
                if lines and lines[-1].strip() == "```": lines = lines[:-1]
                json_text = "\n".join(lines).strip()

            parsed_data = json.loads(json_text)
            logger.info(f"JSON parsé avec succès: {list(parsed_data.keys())}")
            return parsed_data
            
        except json.JSONDecodeError as e:
            logger.error(f"Erreur de parsing JSON: {e}\nContenu: {content if 'content' in locals() else 'N/A'}")
            return None
        except Exception as e:
            logger.error(f"Erreur Gemini JSON: {type(e).__name__}: {str(e)}")
            return None

    async def generate_vision_response(self, system_prompt: str, user_message: str, base64_image: str) -> Dict:
        """Génère une réponse structurée JSON à partir d'une image (Vision) avec Gemini."""
        if not self.client_ready:
            raise ValueError("Le service Vision n'est pas configuré. Clé API manquante.")

        # Modèle spécifique si besoin, mais gemini-1.5-flash gère la vision
        vision_model = genai.GenerativeModel("gemini-1.5-flash")
        
        full_prompt = (
            f"INSTRUCTION SYSTÈME:\n{system_prompt}\n\n"
            "IMPORTANT: Réponds EXCLUSIVEMENT avec un objet JSON valide, sans balises markdown.\n\n"
            f"REQUÊTE UTILISATEUR:\n{user_message}"
        )

        # Gemini prend l'image sous forme de dict
        image_part = {
            "mime_type": "image/jpeg",
            "data": base64_image
        }

        try:
            response = await vision_model.generate_content_async(
                [full_prompt, image_part],
                generation_config=GenerationConfig(
                    temperature=0.3,
                    max_output_tokens=2000,
                    response_mime_type="application/json"
                )
            )
            
            content = response.text
            logger.info(f"Réponse Vision brute: {content[:100]}...")
            
            json_text = content.strip()
            if json_text.startswith("```"):
                lines = json_text.splitlines()
                if lines[0].startswith("```"): lines = lines[1:]
                if lines and lines[-1].strip() == "```": lines = lines[:-1]
                json_text = "\n".join(lines).strip()

            return json.loads(json_text)
            
        except Exception as e:
            logger.error(f"Erreur Gemini Vision API: {e}")
            return None

    def _mock_response(self, message: str) -> str:
        """Fallback si pas de clé API."""
        return (f"[SIMULATION] J'ai bien reçu votre message : '{message}'. "
                "En production avec Gemini, je ferais appel à l'API pour générer une réponse pertinente "
                "basée sur les offres d'emploi.")