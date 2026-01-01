"""
Utilitaires pour l'extraction de titres de poste.
"""

import re
from typing import Optional


def extraire_metier_ultra_simple(titre: str) -> Optional[str]:
    """
    Extraction métier ultra-simple :
    - Cherche "recrute [nombre/quantifieur]"
    - Si trouvé : prend ce qui vient après
    - Sinon : prend le titre ENTIER
    """
    if not titre or not isinstance(titre, str):
        return None

    # Pattern 1 : "recrute 01/des/plusieurs/un/une MÉTIER"
    pattern_recrute = re.compile(
        r'recrute[ds]?\s+(?:0?\d+|plusieurs|des|un|une|massivement)\s+(.+?)(?:\s*[\(\[]|\s+-\s+|\s+[àa]\s+|\s+et\s+|\s+/\s+|\s+h/f|\s+m/f|\s+f/h|\s+bilingue|\s+cdi|\s+cdd|\s+stage|\s+freelance|$)',
        re.IGNORECASE
    )

    match = pattern_recrute.search(titre)
    if match:
        metier = match.group(1).strip()
        # Nettoyage léger : enlever "pour/en/chez..." à la fin
        metier = re.split(r'\s+(pour|en|chez|dans|au|à la|de la|dans le secteur)\s+', metier)[0]
        return metier if len(metier) >= 3 else titre.strip()

    # Pattern 2 : "recrute MÉTIER" (sans nombre)
    pattern_recrute_sans_nb = re.compile(
        r'recrute[ds]?\s+(.+?)(?:\s*[\(\[]|\s+-\s+|\s+[àa]\s+|\s+et\s+|\s+/\s+|\s+h/f|\s+m/f|\s+f/h|\s+bilingue|\s+cdi|\s+cdd|\s+freelance|$)',
        re.IGNORECASE
    )

    match = pattern_recrute_sans_nb.search(titre)
    if match:
        metier = match.group(1).strip()
        metier = re.split(r'\s+(pour|en|chez|dans|au|à la|de la)\s+', metier)[0]
        return metier if len(metier) >= 3 else titre.strip()

    # ⚠️ FALLBACK : prendre tout le titre
    return titre.strip()


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