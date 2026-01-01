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