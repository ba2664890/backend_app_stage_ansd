"""
Routes API pour l'analyse salariale et benchmark.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from uuid import UUID

from ..database import get_db
from ..services.salary_benchmark_service import SalaryBenchmarkService
from ..utils.auth import get_current_user

router = APIRouter(prefix="/api/v1/salary", tags=["salary-benchmark"])
salary_service = SalaryBenchmarkService()


@router.get("/benchmark", response_model=Dict[str, Any])
async def get_salary_benchmark(
    job_category: Optional[str] = Query(None, description="Catégorie de poste"),
    sector: Optional[str] = Query(None, description="Secteur d'activité"),
    location: Optional[str] = Query(None, description="Localisation"),
    experience_years: Optional[int] = Query(None, description="Années d'expérience"),
    db: Session = Depends(get_db)
):
    """Récupère le benchmark salarial selon les critères."""
    benchmark = salary_service.get_salary_benchmark(
        db, job_category, sector, location, experience_years
    )
    return benchmark


@router.get("/equity-analysis", response_model=Dict[str, Any])
async def get_salary_equity_analysis(
    company_id: Optional[str] = Query(None, description="ID de l'entreprise"),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Analyse l'équité salariale."""
    analysis = salary_service.analyze_salary_equity(db, company_id)
    return analysis


@router.post("/simulate-budget", response_model=Dict[str, Any])
async def simulate_salary_budget(
    positions: List[Dict[str, Any]],
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Simule un budget salarial pour des postes planifiés.
    
    **Body**: Liste de positions avec job_category, sector, experience_years, count
    """
    try:
        simulation = salary_service.simulate_salary_budget(db, positions)
        return simulation
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trends/{job_category}", response_model=List[Dict[str, Any]])
async def get_salary_trends(
    job_category: str,
    months: int = Query(12, ge=1, le=24, description="Nombre de mois"),
    db: Session = Depends(get_db)
):
    """Analyse l'évolution des salaires sur une période."""
    trends = salary_service.get_salary_trends(db, job_category, months)
    return trends
