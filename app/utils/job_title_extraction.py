"""
Utilitaires pour l'extraction de titres de poste.
"""

import re
from typing import Optional


def extraire_metier_ultra_simple(titre: str) -> Optional[str]:
    """
    Extraction métier ultra-simple :
    - Cherche les patterns de recrutement (recrute, recrutement, avis...)
    - Nettoie les quantités (01, 10, plusieurs...)
    - Retourne le métier net
    """
    if not titre or not isinstance(titre, str):
        return None

    titre = titre.strip()
    
    # 1. Nettoyage des préfixes d'action et quantités
    # Pattern large pour attraper "Recrutement de 10...", "Recrute plusieurs...", "05 Coordonnateurs..."
    pattern = re.compile(
        r'^(?:(?:recrute[ds]?|recrutement|avis de recrutement|recherche)\s+(?:de\s+)?(?:0?\d+|plusieurs|des|un|une|massivement)?\s*|0?\d+\s+)(.+?)(?:\s*[\(\[]|\s+-\s+|\s+[àa]\s+|\s+et\s+|\s+/\s+|\s+h/f|\s+m/f|\s+f/h|\s+bilingue|\s+cdi|\s+cdd|\s+stage|\s+freelance|$)',
        re.IGNORECASE
    )

    match = pattern.search(titre)
    if match:
        metier = match.group(1).strip()
        # Sécurité supplémentaire : si le métier extrait commence encore par un chiffre (cas complexes)
        metier = re.sub(r'^\b\d+\b\s*', '', metier)
        # Nettoyage final : enlever "pour/en/chez..."
        metier = re.split(r'\s+(pour|en|chez|dans|au|à la|de la|dans le secteur)\s+', metier)[0]
        return metier

    # ⚠️ FALLBACK FINAL : tout le titre sans chiffres au début
    clean_title = re.sub(r'^\d+\s+', '', titre)
    return clean_title


def normaliser_titre_metier(metier: str) -> Optional[str]:
    """Normalisation très minimale (sans mapping complexe)"""
    if not metier:
        return None

    # Supprimer les espaces multiples
    metier = ' '.join(metier.split())

    # Capitaliser la première lettre
    return metier.capitalize()


def extract_job_title(title: str) -> Optional[str]:
    """
    Fonction principale pour extraire le titre du poste.
    Combine l'extraction et la normalisation.
    """
    raw_title = extraire_metier_ultra_simple(title)
    return normaliser_titre_metier(raw_title)


def backfill_job_titles(db):
    """
    Parcourt les offres existantes pour remplir extracted_job_title si vide.
    Conçu pour être lancé en tâche de fond au démarrage.
    """
    import logging
    from ..models.database_models import OffreEmploiEnrichie
    
    logger = logging.getLogger(__name__)
    
    try:
        # On ne traite que les records vides
        enrichies = db.query(OffreEmploiEnrichie).filter(
            OffreEmploiEnrichie.extracted_job_title.is_(None)
        ).all()
        
        if not enrichies:
            logger.info("✅ Aucun backfill nécessaire pour les titres de poste.")
            return

        logger.info(f"⏳ Début du backfill pour {len(enrichies)} titres de poste...")
        
        count = 0
        for enrichie in enrichies:
            brute = enrichie.offre_brute
            if brute and brute.title:
                try:
                    title = extract_job_title(brute.title)
                    if title:
                        enrichie.extracted_job_title = title
                        count += 1
                except Exception as e:
                    logger.error(f"Erreur extraction pour record {enrichie.id} : {e}")
            
            # Commit par blocs
            if count % 50 == 0:
                db.commit()
                
        db.commit()
        logger.info(f"✨ Backfill terminé : {count} titres mis à jour.")
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Échec du backfill des titres de poste : {str(e)}")