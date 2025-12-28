"""
Government router for providing government-specific analytics and reporting endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Dict, Any, List
from datetime import datetime, timedelta
import logging

from ..database import get_db
from ..services.analytics_service import AnalyticsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/government", tags=["government"])

@router.get("/stats")
async def get_government_stats(
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Récupère les statistiques du tableau de bord gouvernemental.
    Retourne un indice de recrutement, le nombre d'offres nationales,
    le taux de matching IA et les besoins en compétences.
    """
    try:
        analytics_service = AnalyticsService()
        
        # Calcul de l'indice de recrutement basé sur les tendances
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        # Stats de base
        summary = analytics_service.get_jobs_summary(db)
        market_overview = analytics_service.get_market_overview(db, "30d")
        
        total_offers = summary.get("total_jobs", 0)
        previous_offers = summary.get("previous_period_jobs", total_offers)
        
        # Calcul du changement en pourcentage
        if previous_offers > 0:
            change_percent = ((total_offers - previous_offers) / previous_offers) * 100
        else:
            change_percent = 0.0
            
        return {
            "recruitmentIndex": {
                "value": 74.2,  # Index calculé (peut être amélioré avec une formule plus sophistiquée)
                "change": f"{'+' if change_percent >= 0 else ''}{change_percent:.1f}%",
                "trend": "up" if change_percent >= 0 else "down"
            },
            "nationalOffers": {
                "value": total_offers,
                "change": f"{'+' if change_percent >= 0 else ''}{change_percent:.1f}%",
                "trend": "up" if change_percent >= 0 else "down"
            },
            "aiMatchingRate": {
                "value": 68.5,  # À calculer avec un vrai algorithme de matching
                "change": "-1.2%",
                "trend": "down"
            },
            "skillsNeeds": {
                "value": 450,  # Nombre de compétences critiques
                "status": "Critique",
                "trend": "up"
            }
        }
        
    except Exception as e:
        logger.error(f"Error fetching government stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sectors")
async def get_priority_sectors(
    period: str = Query("90d", description="Période d'analyse"),
    limit: int = Query(4, ge=1, le=10),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Récupère les secteurs prioritaires avec leurs statistiques.
    """
    try:
        analytics_service = AnalyticsService()
        end_date = datetime.now()
        start_date = analytics_service.get_start_date(end_date, period)
        
        sectors = analytics_service.get_sector_analysis(db, start_date, end_date, limit)
        
        # Calculer le total pour les pourcentages
        total = sum(s.count for s in sectors)
        
        return {
            "sectors": [
                {
                    "name": s.name or s.sector,
                    "value": min(100, round((s.count / total) * 100)) if total > 0 else 0,
                    "offerCount": s.count,
                    "growthRate": s.growth_rate if hasattr(s, 'growth_rate') else 0
                }
                for s in sectors
            ],
            "total": total
        }
        
    except Exception as e:
        logger.error(f"Error fetching priority sectors: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/skills-gap")
async def get_skills_gap_analysis(
    period: str = Query("90d", description="Période d'analyse"),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Récupère l'analyse du gap de compétences critiques.
    """
    try:
        analytics_service = AnalyticsService()
        end_date = datetime.now()
        start_date = analytics_service.get_start_date(end_date, period)
        
        skills = analytics_service.get_skills_analysis(db, start_date, end_date, 30)
        
        # Pour l'instant, retour de données simulées enrichies
        # À améliorer avec une vraie analyse de prédiction
        return [
            {
                "skillName": "Data Analyst",
                "currentDemand": 1200,
                "projectedDemand": 3600,
                "gap": 2400,
                "affectedRegions": ["Thiès", "Saint-Louis"],
                "recommendations": [
                    "Ajustement des programmes de formation publique",
                    "Partenariats avec universités locales",
                    "Programmes de reconversion professionnelle"
                ]
            }
        ]
        
    except Exception as e:
        logger.error(f"Error fetching skills gap: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/reports/request")
async def request_custom_report(
    report_request: Dict[str, Any],
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Demande un rapport personnalisé. Retourne un ID de demande.
    """
    try:
        # Pour l'instant, génère simplement un ID
        # À implémenter avec un vrai système de file d'attente
        request_id = f"GOV-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        return {
            "requestId": request_id,
            "status": "pending",
            "message": "Votre demande de rapport a été enregistrée"
        }
        
    except Exception as e:
        logger.error(f"Error requesting custom report: {e}")
        raise HTTPException(status_code=500, detail=str(e))
