from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Dict, Any, Optional

from ..database import get_db
from ..models.database_models import OffreEmploiBrute

router = APIRouter(prefix="/api/v1/carte", tags=["map"])

@router.get("/{level}", response_model=Dict[str, Any])
async def get_choropleth_data(
    level: str,
    min_offers: int = 0,
    parent_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Récupère les données pour la carte choroplèthe.
    Groupe les offres par localisation.
    """
    # Simplification: On groupe par 'location' brute.
    # Idéalement il faudrait mapper vers les régions/départements selon 'level'
    
    query = db.query(
        OffreEmploiBrute.location, 
        func.count(OffreEmploiBrute.id)
    )
    
    # Filtres optionnels basiques si nécessaire
    if parent_name:
         # Supposons que location contient "Region, Pays"
         query = query.filter(OffreEmploiBrute.location.contains(parent_name))

    results = query.group_by(OffreEmploiBrute.location).all()
    
    data = {}
    for loc, count in results:
        if loc and count >= min_offers:
            # On nettoie un peu la location pour servir de clé
            key = loc.strip()
            data[key] = {
                "value": count,
                "label": key
            }
            
    return data
