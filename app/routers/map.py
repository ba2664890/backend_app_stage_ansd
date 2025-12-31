from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from ..database import get_db
from ..core.constants import AdminLevel
from ..services.admin_boundary import AdminBoundaryService, CarteService
from ..models.api_models import ChoroplethResponse

router = APIRouter(prefix="/api/v1/carte", tags=["map"])

# ⚠️ IMPORTANT: Specific routes MUST come before generic path parameters
# Otherwise FastAPI will match "/insights" as level="insights"

@router.get("/insights", response_model=dict)
async def get_map_insights(db: Session = Depends(get_db)):
    """
    Récupère les insights IA et les alertes de pénurie.
    """
    admin_service = AdminBoundaryService()
    carte_service = CarteService(admin_service)
    
    return await carte_service.get_map_insights(db)

@router.get("/locations/{level}", response_model=list[dict])
async def get_locations(
    level: str,
    parent_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Récupère une liste simple des lieux pour un niveau donné (pour les dropdowns).
    """
    try:
        admin_level = AdminLevel(level)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid level: {level}")

    admin_service = AdminBoundaryService()
    carte_service = CarteService(admin_service)
    
    return carte_service.get_locations_list(db, level=admin_level, parent_name=parent_name)

@router.get("/{level}", response_model=ChoroplethResponse)
async def get_choropleth_data(
    level: str,
    min_offers: int = 0,
    parent_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Récupère les données pour la carte choroplèthe.
    Utilise le service optimisé avec PostGIS et compteurs pré-calculés.
    """
    try:
        # Conversion du string level en Enum
        admin_level = AdminLevel(level)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid level: {level}. Must be one of {[l.value for l in AdminLevel]}")

    admin_service = AdminBoundaryService()
    carte_service = CarteService(admin_service)
    
    return carte_service.get_choropleth_data(
        db, 
        level=admin_level, 
        min_offers=min_offers, 
        parent_name=parent_name
    )

