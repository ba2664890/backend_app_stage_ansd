"""
Service pour l'analyse salariale et benchmark.
"""

from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
import logging

from ..models.database_models import OffreEmploiEnrichie, OffreEmploiBrute, Application

logger = logging.getLogger(__name__)


class SalaryBenchmarkService:
    """Service pour l'analyse et le benchmark salarial."""
    
    def get_salary_benchmark(
        self,
        db: Session,
        job_category: Optional[str] = None,
        job_title: Optional[str] = None,
        sector: Optional[str] = None,
        location: Optional[str] = None,
        experience_years: Optional[int] = None
    ) -> Dict:
        """
        Récupère le benchmark salarial selon les critères.
        
        Returns:
            Dict: Statistiques salariales (min, max, médiane, percentiles)
        """
        query = db.query(OffreEmploiEnrichie).filter(
            OffreEmploiEnrichie.extracted_salary_min.isnot(None),
            OffreEmploiEnrichie.extracted_salary_max.isnot(None)
        )
        
        # Appliquer les filtres
        if job_category:
            query = query.filter(OffreEmploiEnrichie.extracted_job_category == job_category)
        
        if job_title:
            query = query.filter(
                func.lower(OffreEmploiEnrichie.extracted_job_title).contains(func.lower(job_title))
            )
        
        if sector:
            query = query.filter(OffreEmploiEnrichie.extracted_sector == sector)
        
        if location:
            query = query.join(OffreEmploiBrute).filter(
                OffreEmploiBrute.location.ilike(f"%{location}%")
            )
        
        if experience_years is not None:
            query = query.filter(OffreEmploiEnrichie.extracted_experience_years == experience_years)
        
        offers = query.all()
        
        if not offers:
            return {
                "count": 0,
                "salary_min": {"avg": None, "median": None, "p25": None, "p75": None},
                "salary_max": {"avg": None, "median": None, "p25": None, "p75": None},
                "message": "Pas de données disponibles pour ces critères"
            }
        
        # Calculer les statistiques
        salary_mins = sorted([o.extracted_salary_min for o in offers if o.extracted_salary_min])
        salary_maxs = sorted([o.extracted_salary_max for o in offers if o.extracted_salary_max])
        
        def calculate_stats(values: List[int]) -> Dict:
            if not values:
                return {"avg": None, "median": None, "p25": None, "p75": None}
            
            n = len(values)
            return {
                "avg": int(sum(values) / n),
                "median": values[n // 2],
                "p25": values[n // 4],
                "p75": values[3 * n // 4]
            }
        
        stats_min = calculate_stats(salary_mins)
        stats_max = calculate_stats(salary_maxs)
        
        # Consolidation pour le frontend (moyenne des mins et maxs pour une vision globale)
        res = {
            "count": len(offers),
            "sample_size": len(offers),
            "min_salary": stats_min["p25"] or 0,
            "max_salary": stats_max["p75"] or 0,
            "median_salary": (stats_min["median"] + stats_max["median"]) // 2 if stats_min["median"] and stats_max["median"] else 0,
            "avg_salary": (stats_min["avg"] + stats_max["avg"]) // 2 if stats_min["avg"] and stats_max["avg"] else 0,
            "job_category": job_category or "Général",
            "job_title": job_title,
            "salary_min": stats_min,
            "salary_max": stats_max,
            "filters_applied": {
                "job_category": job_category,
                "job_title": job_title,
                "sector": sector,
                "location": location,
                "experience_years": experience_years
            }
        }
        return res
    
    def analyze_salary_equity(
        self,
        db: Session,
        company_id: Optional[str] = None
    ) -> Dict:
        """
        Analyse l'équité salariale.
        
        Returns:
            Dict: Analyse d'équité avec écarts détectés
        """
        # Cette fonctionnalité nécessiterait des données internes de l'entreprise
        # Pour l'instant, retourne une structure de base
        
        return {
            "overall_equity_score": 0.85,  # Score sur 1
            "gender_pay_gap": {
                "detected": False,
                "gap_percentage": 0.0,
                "recommendation": "Données insuffisantes pour l'analyse"
            },
            "experience_pay_correlation": {
                "correlation": 0.75,
                "status": "normal",
                "outliers": []
            },
            "recommendations": [
                "Collecter plus de données démographiques",
                "Standardiser les grilles salariales",
                "Réviser annuellement les salaires"
            ]
        }
    
    def simulate_salary_budget(
        self,
        db: Session,
        positions: List[Dict]
    ) -> Dict:
        """
        Simule un budget salarial pour des postes planifiés.
        
        Args:
            positions: Liste de {job_category, sector, experience_years, count}
            
        Returns:
            Dict: Budget estimé avec fourchettes
        """
        total_min = 0
        total_max = 0
        position_details = []
        
        for position in positions:
            benchmark = self.get_salary_benchmark(
                db,
                job_category=position.get("job_category"),
                sector=position.get("sector"),
                experience_years=position.get("experience_years")
            )
            
            count = position.get("count", 1)
            
            if benchmark["count"] > 0:
                pos_min = benchmark["salary_min"]["median"] * count
                pos_max = benchmark["salary_max"]["median"] * count
            else:
                # Valeurs par défaut si pas de données
                pos_min = 500000 * count
                pos_max = 1000000 * count
            
            total_min += pos_min
            total_max += pos_max
            
            position_details.append({
                "position": position.get("job_category", "Non spécifié"),
                "count": count,
                "unit_salary_range": {
                    "min": pos_min // count,
                    "max": pos_max // count
                },
                "total_cost": {
                    "min": pos_min,
                    "max": pos_max
                }
            })
        
        return {
            "total_budget": {
                "min": total_min,
                "max": total_max,
                "average": (total_min + total_max) // 2
            },
            "monthly_budget": {
                "min": total_min,
                "max": total_max
            },
            "annual_budget": {
                "min": total_min * 12,
                "max": total_max * 12
            },
            "positions": position_details,
            "recommendations": [
                "Prévoir une marge de 10-15% pour les négociations",
                "Inclure les charges sociales (environ 20-25%)",
                "Considérer les avantages non-salariaux"
            ]
        }
    
    def get_salary_trends(
        self,
        db: Session,
        job_category: str,
        months: int = 12
    ) -> List[Dict]:
        """
        Analyse l'évolution des salaires sur une période.
        
        Returns:
            List[Dict]: Tendances mensuelles
        """
        start_date = datetime.now() - timedelta(days=months * 30)
        
        offers = db.query(OffreEmploiEnrichie).join(
            OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
        ).filter(
            OffreEmploiEnrichie.extracted_job_category == job_category,
            OffreEmploiEnrichie.extracted_salary_min.isnot(None),
            OffreEmploiBrute.posted_date >= start_date
        ).all()
        
        # Grouper par mois
        monthly_data = {}
        for offer in offers:
            if offer.offre_brute and offer.offre_brute.posted_date:
                month_key = offer.offre_brute.posted_date.strftime("%Y-%m")
                if month_key not in monthly_data:
                    monthly_data[month_key] = []
                monthly_data[month_key].append({
                    "min": offer.extracted_salary_min,
                    "max": offer.extracted_salary_max
                })
        
        # Calculer les moyennes mensuelles
        trends = []
        for month, salaries in sorted(monthly_data.items()):
            avg_min = sum(s["min"] for s in salaries if s["min"]) / len(salaries)
            avg_max = sum(s["max"] for s in salaries if s["max"]) / len(salaries)
            
            trends.append({
                "month": month,
                "avg_salary_min": int(avg_min),
                "avg_salary_max": int(avg_max),
                "offer_count": len(salaries)
            })
        
        return trends
