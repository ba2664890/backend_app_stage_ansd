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
    
    # Query pour les talents (Candidats)
    from ..models.database_models import UserProfile, User, UserRole
    
    talent_query = db.query(
        UserProfile.location,
        func.count(UserProfile.id)
    ).join(User, UserProfile.user_id == User.id).filter(User.role == UserRole.CANDIDATE)
    
    if parent_name:
        talent_query = talent_query.filter(UserProfile.location.contains(parent_name))
        
    talent_results = talent_query.group_by(UserProfile.location).all()
    talent_map = {loc.strip(): count for loc, count in talent_results if loc}

    data = {}
    
    # Fusion des résultats (Offres + Talents)
    all_locations = set([r[0].strip() for r in results if r[0]] + [t[0].strip() for t in talent_results if t[0]])
    
    for loc in all_locations:
        offer_count = next((count for l, count in results if l and l.strip() == loc), 0)
        talent_count = talent_map.get(loc, 0)
        
        if offer_count >= min_offers or talent_count > 0:
            data[loc] = {
                "value": offer_count,
                "label": loc,
                "talent_count": talent_count
            }
            
    return data
