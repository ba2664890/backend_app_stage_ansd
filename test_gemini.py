import asyncio
import os
from app.services.llm_client import LLMClient

async def main():
    # Make sure we load env variables if they exist
    # Let's initialize LLMClient
    print("Env GEMINI_API_KEY:", os.getenv("GEMINI_API_KEY"))
    client = LLMClient()
    print("Client ready:", client.client_ready)
    if not client.client_ready:
        print("Mock response would be returned.")
    
    prompt = """
    Rédige une offre d'emploi complète pour le poste de : Responsable Comptable.
    Secteur : Santé & Social.
    Niveau d'expérience : Non spécifié.
    Contexte additionnel : .
    
    Inclus les sections suivantes :
    1. Titre du poste
    2. À propos de nous
    3. Mission principale
    4. Responsabilités
    5. Compétences requises (Hard & Soft skills)
    6. Avantages
    """
    
    response = await client.generate_response(
        system_prompt="Tu es un expert en rédaction de RH.",
        user_message=prompt
    )
    print("Response:")
    print(response)

if __name__ == "__main__":
    asyncio.run(main())
