from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from ..database import get_db
from ..core.constants import AdminLevel
from ..services.admin_boundary import AdminBoundaryService, CarteService
from ..models.api_models import ChoroplethResponse

router = APIRouter(prefix="/api/v1/carte", tags=["map"])

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
