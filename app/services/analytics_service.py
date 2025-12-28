"""
Service pour l'analyse des données du marché de l'emploi.
"""

from typing import List, Dict, Any, Optional, Union
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, extract, case, cast, Float
from datetime import datetime, timedelta
import logging

from ..models.database_models import OffreEmploiBrute, OffreEmploiEnrichie, JobStatistics
from ..models.api_models import JobAnalyticsResponse

logger = logging.getLogger(__name__)

class AnalyticsService:
    """Service pour l'analyse des données d'emploi."""
    
    def __init__(self):
        """Initialise le service d'analytics."""
        self.date_format = '%Y-%m'
    
    def _safe_get(self, obj, attr, default=None):
        """Récupère un attribut en toute sécurité."""
        try:
            return getattr(obj, attr, default)
        except:
            return default

    def _safe_float(self, value: Any) -> Optional[float]:
        """Convert value to float safely."""
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def get_jobs_summary(self, db: Session) -> dict:
        """Récupère un résumé des statistiques des offres d'emploi."""
        try:
            thirty_days_ago = datetime.now() - timedelta(days=30)
            
            # Updated query with proper type casting
            stats = db.query(
                cast(func.count(OffreEmploiEnrichie.id), Float).label('total_jobs'),
                cast(func.count(case(
                    [(OffreEmploiBrute.posted_date >= thirty_days_ago, 1)]
                )), Float).label('recent_jobs')
            ).join(
                OffreEmploiBrute,
                OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).first()
            
            # Top 5 secteurs avec cast des counts
            top_sectors = (
                db.query(
                    OffreEmploiEnrichie.extracted_sector,
                    cast(func.count(OffreEmploiEnrichie.id), Float).label('count')
                )
                .join(
                    OffreEmploiBrute,
                    OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                )
                .filter(OffreEmploiEnrichie.extracted_sector.isnot(None))
                .group_by(OffreEmploiEnrichie.extracted_sector)
                .order_by(desc('count'))
                .limit(5)
                .all()
            )
            
            return {
                "total_jobs": self._safe_float(getattr(stats, 'total_jobs', 0)),
                "recent_jobs": self._safe_float(getattr(stats, 'recent_jobs', 0)),
                "top_sectors": [
                    {
                        "sector": sector,
                        "count": self._safe_float(count)
                    }
                    for sector, count in top_sectors if sector
                ],
                "last_updated": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du résumé: {str(e)}")
            raise
    
    def get_market_overview(self, db: Session, period: str = "30d") -> Dict[str, Any]:
        """Récupère une vue d'ensemble du marché de l'emploi."""
        try:
            end_date = datetime.now()
            start_date = self._get_start_date(end_date, period)
            
            # Statistiques générales avec une seule requête
            stats = db.query(
                func.count(OffreEmploiBrute.id).label('total_offers'),
                func.count(func.distinct(OffreEmploiBrute.company_name)).label('total_companies'),
                func.count(func.distinct(OffreEmploiBrute.location)).label('total_locations')
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date)
            ).first()
            
            return {
                "period": period,
                "total_offers": getattr(stats, 'total_offers', 0),
                "total_companies": getattr(stats, 'total_companies', 0),
                "total_locations": getattr(stats, 'total_locations', 0),
                "market_trends": self._get_monthly_trends(db, start_date, end_date),
                "sector_analysis": self._get_sector_analysis(db, start_date, end_date),
                "skills_analysis": self._get_skills_analysis(db, start_date, end_date),
                "salary_trends": self._get_salary_trends(db, start_date, end_date),
                "generated_at": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de l'aperçu du marché: {str(e)}")
            raise

    def _get_monthly_trends(self, db: Session, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Récupère les tendances mensuelles."""
        try:
            trends = db.query(
                func.date_trunc('month', OffreEmploiBrute.posted_date).label('month'),
                func.count(OffreEmploiBrute.id).label('total_offers'),
                func.count(OffreEmploiBrute.company_name.distinct()).label('unique_companies'),
                func.count(OffreEmploiBrute.location.distinct()).label('unique_locations')
            ).filter(
                OffreEmploiBrute.posted_date >= start_date,
                OffreEmploiBrute.posted_date <= end_date
            ).group_by(
                func.date_trunc('month', OffreEmploiBrute.posted_date)
            ).order_by(
                func.date_trunc('month', OffreEmploiBrute.posted_date)
            ).all()
            
            result = []
            for trend in trends:
                month = self._safe_get(trend, 'month')
                month_str = month.strftime(self.date_format) if month else None
                
                # Salaires moyens pour cette période
                salary_stats = db.query(
                    func.avg(OffreEmploiEnrichie.extracted_salary_min).label('avg_min'),
                    func.avg(OffreEmploiEnrichie.extracted_salary_max).label('avg_max')
                ).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    func.date_trunc('month', OffreEmploiBrute.posted_date) == trend.month,
                    OffreEmploiEnrichie.extracted_salary_min.isnot(None),
                    OffreEmploiEnrichie.extracted_salary_max.isnot(None)
                ).first()
                
                # Top secteurs pour cette période
                top_sectors = db.query(
                    OffreEmploiEnrichie.extracted_sector,
                    func.count(OffreEmploiEnrichie.id).label('count')
                ).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    func.date_trunc('month', OffreEmploiBrute.posted_date) == trend.month,
                    OffreEmploiEnrichie.extracted_sector.isnot(None)
                ).group_by(
                    OffreEmploiEnrichie.extracted_sector
                ).order_by(desc('count')).limit(5).all()
                
                # Top compétences pour cette période
                top_skills = db.query(
                    func.unnest(OffreEmploiEnrichie.extracted_skills).label('skill'),
                    func.count(OffreEmploiEnrichie.id).label('count')
                ).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    func.date_trunc('month', OffreEmploiBrute.posted_date) == trend.month,
                    OffreEmploiEnrichie.extracted_skills.isnot(None)
                ).group_by('skill').order_by(desc('count')).limit(10).all()
                
                result.append({
                    "period": month_str,
                    "total_offers": self._safe_get(trend, 'total_offers', 0),
                    "new_offers": self._safe_get(trend, 'total_offers', 0),
                    "unique_companies": self._safe_get(trend, 'unique_companies', 0),
                    "unique_locations": self._safe_get(trend, 'unique_locations', 0),
                    "avg_salary_min": float(self._safe_get(salary_stats, 'avg_min')) if salary_stats and self._safe_get(salary_stats, 'avg_min') is not None else None, # type: ignore
                    "avg_salary_max": float(self._safe_get(salary_stats, 'avg_max')) if salary_stats and self._safe_get(salary_stats, 'avg_max') is not None else None,
                    "top_sectors": [
                        {"sector": self._safe_get(s, '0'), "count": self._safe_get(s, '1', 0)}
                        for s in top_sectors
                    ],
                    "top_skills": [
                        {"skill": self._safe_get(s, '0'), "count": self._safe_get(s, '1', 0)}
                        for s in top_skills
                    ]
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting monthly trends: {e}")
            raise
    
    def _get_sector_analysis(self, db: Session, start_date: datetime, end_date: datetime, limit: int = 10) -> List[Dict[str, Any]]:
        """Analyse optimisée des secteurs d'activité."""
        try:
            # Requête optimisée avec CTE
            sectors_cte = db.query(
                OffreEmploiEnrichie.extracted_sector.label('sector'),
                func.count(OffreEmploiEnrichie.id).label('count'),
                func.avg(OffreEmploiEnrichie.extracted_salary_min).label('avg_min'),
                func.avg(OffreEmploiEnrichie.extracted_salary_max).label('avg_max')
            ).join(
                OffreEmploiBrute,
                OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.extracted_sector.isnot(None)
            ).group_by(
                OffreEmploiEnrichie.extracted_sector
            ).cte()
            
            # Requête principale
            sectors = db.query(sectors_cte).order_by(desc('count')).limit(limit).all()
            
            total_offers = sum(s.count for s in sectors)
            
            return [{
                "sector": self._safe_get(s, 'sector'),
                "count": self._safe_get(s, 'count', 0),
                "percentage": round(((self._safe_get(s, 'count', 0) or 0) / total_offers * 100), 2) if total_offers > 0 else 0,
                "avg_salary_min": float(self._safe_get(s, 'avg_min')) if self._safe_get(s, 'avg_min') is not None else None,
                "avg_salary_max": float(self._safe_get(s, 'avg_max')) if self._safe_get(s, 'avg_max') is not None else None
            } for s in sectors]
            
        except Exception as e:
            logger.error(f"Erreur lors de l'analyse des secteurs: {str(e)}")
            raise
    
    def _get_skills_analysis(self, db: Session, start_date: datetime, end_date: datetime, limit: int = 20) -> List[Dict[str, Any]]:
        """Analyse des compétences demandées."""
        try:
            skills = db.query(
                func.unnest(OffreEmploiEnrichie.extracted_skills).label('skill'),
                func.count(OffreEmploiEnrichie.id).label('count')
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date >= start_date,
                OffreEmploiBrute.posted_date <= end_date,
                OffreEmploiEnrichie.extracted_skills.isnot(None)
            ).group_by('skill').order_by(desc('count')).limit(limit).all()
            
            total_offers = db.query(OffreEmploiBrute).filter(
                OffreEmploiBrute.posted_date >= start_date,
                OffreEmploiBrute.posted_date <= end_date
            ).count()
            
            result = []
            for skill in skills:
                percentage = (skill.count / total_offers * 100) if total_offers > 0 else 0
                
                # Secteurs associés à cette compétence
                related_sectors = db.query(
                    OffreEmploiEnrichie.extracted_sector
                ).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    OffreEmploiBrute.posted_date >= start_date,
                    OffreEmploiBrute.posted_date <= end_date,
                    OffreEmploiEnrichie.extracted_skills.any(skill.skill),
                    OffreEmploiEnrichie.extracted_sector.isnot(None)
                ).distinct().limit(5).all()
                
                result.append({
                    "skill": skill.skill,
                    "count": skill.count,
                    "percentage": round(percentage, 2),
                    "related_sectors": [s[0] for s in related_sectors if s[0]],
                    "salary_impact": None  # TODO: Calculer l'impact sur les salaires
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting skills analysis: {e}")
            raise
    
    def _get_salary_trends(self, db: Session, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Analyse des tendances salariales."""
        try:
            monthly_salaries = db.query(
                func.date_trunc('month', OffreEmploiBrute.posted_date).label('month'),
                cast(func.avg(OffreEmploiEnrichie.extracted_salary_min), Float).label('avg_min'),
                cast(func.avg(OffreEmploiEnrichie.extracted_salary_max), Float).label('avg_max'),
                cast(func.percentile_cont(0.5).within_group(OffreEmploiEnrichie.extracted_salary_min), Float).label('median_min'),
                cast(func.percentile_cont(0.25).within_group(OffreEmploiEnrichie.extracted_salary_min), Float).label('percentile_25'),
                cast(func.percentile_cont(0.75).within_group(OffreEmploiEnrichie.extracted_salary_min), Float).label('percentile_75')
            ).join(
                OffreEmploiEnrichie, OffreEmploiBrute.id == OffreEmploiEnrichie.offre_id
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.extracted_salary_min.isnot(None),
                OffreEmploiEnrichie.extracted_salary_max.isnot(None)
            ).group_by(
                func.date_trunc('month', OffreEmploiBrute.posted_date)
            ).order_by(
                func.date_trunc('month', OffreEmploiBrute.posted_date)
            ).all()

            return [{
                "period": salary.month.strftime('%Y-%m') if salary.month else None,
                "avg_salary_min": self._safe_float(salary.avg_min),
                "avg_salary_max": self._safe_float(salary.avg_max),
                "median_salary": self._safe_float(salary.median_min),
                "percentile_25": self._safe_float(salary.percentile_25),
                "percentile_75": self._safe_float(salary.percentile_75)
            } for salary in monthly_salaries]
            
        except Exception as e:
            logger.error(f"Error getting salary trends: {e}")
            raise
    
    def get_dashboard_stats(self, db: Session) -> Dict[str, Any]:
        """
        Récupère les statistiques pour le tableau de bord.
        
        Args:
            db: Session de base de données
            
        Returns:
            Statistiques du tableau de bord
        """
        try:
            # Statistiques générales
            total_offers = db.query(OffreEmploiBrute).count()
            total_companies = db.query(OffreEmploiBrute.company_name).distinct().count()
            total_locations = db.query(OffreEmploiBrute.location).distinct().count()
            
            # Offres du mois en cours
            current_month = datetime.now().replace(day=1)
            offers_this_month = db.query(OffreEmploiBrute).filter(
                OffreEmploiBrute.posted_date >= current_month
            ).count()
            
            # Offres d'aujourd'hui
            today = datetime.now().date()
            offers_today = db.query(OffreEmploiBrute).filter(
                func.date(OffreEmploiBrute.created_at) == today
            ).count()
            
            # Salaires moyens
            salary_stats = db.query(
                func.avg(OffreEmploiEnrichie.extracted_salary_min).label('avg_min'),
                func.avg(OffreEmploiEnrichie.extracted_salary_max).label('avg_max')
            ).filter(
                OffreEmploiEnrichie.extracted_salary_min.isnot(None),
                OffreEmploiEnrichie.extracted_salary_max.isnot(None)
            ).first()
            
            # Top secteurs
            top_sectors = db.query(
                OffreEmploiEnrichie.extracted_sector,
                func.count(OffreEmploiEnrichie.id).label('count')
            ).filter(
                OffreEmploiEnrichie.extracted_sector.isnot(None)
            ).group_by(
                OffreEmploiEnrichie.extracted_sector
            ).order_by(desc('count')).limit(10).all()
            
            # Top compétences
            top_skills = db.query(
                func.unnest(OffreEmploiEnrichie.extracted_skills).label('skill'),
                func.count(OffreEmploiEnrichie.id).label('count')
            ).filter(
                OffreEmploiEnrichie.extracted_skills.isnot(None)
            ).group_by('skill').order_by(desc('count')).limit(20).all()
            
            # Répartition par type de contrat
            contract_distribution = db.query(
                OffreEmploiEnrichie.extracted_contract_type,
                func.count(OffreEmploiEnrichie.id).label('count')
            ).filter(
                OffreEmploiEnrichie.extracted_contract_type.isnot(None)
            ).group_by(
                OffreEmploiEnrichie.extracted_contract_type
            ).all()
            
            # Répartition par niveau d'expérience
            experience_distribution = db.query(
                OffreEmploiEnrichie.job_level,
                func.count(OffreEmploiEnrichie.id).label('count')
            ).filter(
                OffreEmploiEnrichie.job_level.isnot(None)
            ).group_by(
                OffreEmploiEnrichie.job_level
            ).all()
            
            # Tendance mensuelle des 12 derniers mois
            monthly_trend = db.query(
                func.date_trunc('month', OffreEmploiBrute.posted_date).label('month'),
                func.count(OffreEmploiBrute.id).label('count')
            ).filter(
                OffreEmploiBrute.posted_date >= datetime.now() - timedelta(days=365)
            ).group_by(
                func.date_trunc('month', OffreEmploiBrute.posted_date)
            ).order_by(
                func.date_trunc('month', OffreEmploiBrute.posted_date)
            ).all()
            
            # Tendance par tranches de 5 heures sur les dernières 24h
            hourly_trend = db.query(
                func.date_trunc('hour', OffreEmploiBrute.created_at).label('hour'),
                func.count(OffreEmploiBrute.id).label('count')
            ).filter(
                OffreEmploiBrute.created_at >= datetime.now() - timedelta(days=1)
            ).group_by(
                func.date_trunc('hour', OffreEmploiBrute.created_at)
            ).order_by(
                func.date_trunc('hour', OffreEmploiBrute.created_at)
            ).all()

            # Regrouper par tranches de 5 heures
            hourly_data = {}
            for item in hourly_trend:
                hour = item.hour.replace(minute=0, second=0, microsecond=0)
                time_slot = hour.replace(hour=(hour.hour // 5) * 5)
                if time_slot not in hourly_data:
                    hourly_data[time_slot] = 0
                hourly_data[time_slot] += item.count

            # Formater les données pour le graphique
            trend_data = [
                {
                    "time": slot.strftime('%H:00'),
                    "count": count,
                    "datetime": slot.isoformat()
                }
                for slot, count in sorted(hourly_data.items())
            ]

            return {
                "total_offers": total_offers,
                "total_companies": total_companies,
                "total_locations": total_locations,
                "offers_this_month": offers_this_month,
                "offers_today": offers_today,
                "avg_salary_min": float(salary_stats.avg_min) if salary_stats.avg_min else None,
                "avg_salary_max": float(salary_stats.avg_max) if salary_stats.avg_max else None,
                "top_sectors": [{"sector": s[0], "count": s[1]} for s in top_sectors],
                "top_skills": [{"skill": s[0], "count": s[1]} for s in top_skills],
                "contract_type_distribution": [{"type": d[0], "count": d[1]} for d in contract_distribution],
                "experience_level_distribution": [{"level": d[0], "count": d[1]} for d in experience_distribution],
                "monthly_trend": [{"month": t.month.strftime('%Y-%m'), "count": t.count} for t in monthly_trend],
                "hourly_trend": trend_data  # Nouvelle donnée pour le graphique par 5h
            }
            
        except Exception as e:
            logger.error(f"Error getting dashboard stats: {e}")
            raise
    
    def get_geographic_distribution(self, db: Session) -> List[Dict[str, Any]]:
        """
        Récupère la répartition géographique des offres d'emploi.
        
        Args:
            db: Session de base de données
            
        Returns:
            Répartition géographique
        """
        try:
            # Simplifier les noms de villes/régions
            locations = db.query(
                func.trim(OffreEmploiBrute.location).label('location'),
                func.count(OffreEmploiBrute.id).label('count')
            ).filter(
                OffreEmploiBrute.location.isnot(None),
                OffreEmploiBrute.location != ''
            ).group_by(
                func.trim(OffreEmploiBrute.location)
            ).order_by(desc('count')).limit(20).all()
            
            total_offers = sum(loc.count for loc in locations)
            
            result = []
            for location in locations:
                percentage = (location.count / total_offers * 100) if total_offers > 0 else 0
                
                # Salaires moyens pour cette localisation
                salary_stats = db.query(
                    func.avg(OffreEmploiEnrichie.extracted_salary_min).label('avg_min'),
                    func.avg(OffreEmploiEnrichie.extracted_salary_max).label('avg_max')
                ).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    func.trim(OffreEmploiBrute.location) == location.location,
                    OffreEmploiEnrichie.extracted_salary_min.isnot(None),
                    OffreEmploiEnrichie.extracted_salary_max.isnot(None)
                ).first()
                
                # Secteurs principaux pour cette localisation
                top_sectors = db.query(
                    OffreEmploiEnrichie.extracted_sector
                ).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    func.trim(OffreEmploiBrute.location) == location.location,
                    OffreEmploiEnrichie.extracted_sector.isnot(None)
                ).distinct().limit(5).all()
                
                result.append({
                    "region": location.location,
                    "count": location.count,
                    "percentage": round(percentage, 2),
                    "avg_salary_min": float(salary_stats.avg_min) if salary_stats.avg_min else None,
                    "avg_salary_max": float(salary_stats.avg_max) if salary_stats.avg_max else None,
                    "top_sectors": [s[0] for s in top_sectors if s[0]],
                    "coordinates": self._get_coordinates(location.location)
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting geographic distribution: {e}")
            raise
    
    def _get_coordinates(self, location: str) -> Optional[Dict[str, float]]:
        """Récupère les coordonnées GPS pour une localisation."""
        # Coordonnées pour les principales villes du Sénégal
        coordinates_map = {
            "dakar": {"lat": 14.7167, "lng": -17.4677},
            "thies": {"lat": 14.8056, "lng": -16.9447},
            "saint-louis": {"lat": 16.0179, "lng": -16.4896},
            "kaolack": {"lat": 14.1828, "lng": -16.2533},
            "ziguinchor": {"lat": 12.5570, "lng": -16.2677},
            "tambacounda": {"lat": 13.7700, "lng": -13.6733},
            "louga": {"lat": 15.6167, "lng": -16.2333},
            "diourbel": {"lat": 14.6533, "lng": -16.2369},
            "fatick": {"lat": 14.3550, "lng": -16.4111},
            "kaffrine": {"lat": 14.8500, "lng": -15.5500},
            "kedougou": {"lat": 12.5570, "lng": -12.1800},
            "kolda": {"lat": 12.8833, "lng": -14.8000},
            "matam": {"lat": 15.6500, "lng": -13.2500},
            "sedhiou": {"lat": 12.7081, "lng": -15.5569}
        }
        
        location_lower = location.lower().strip()
        return coordinates_map.get(location_lower, None)
    
    def _get_start_date(self, end_date: datetime, period: str) -> datetime:
        """Calcule la date de début en fonction de la période."""
        period_map = {
            "7d": 7,
            "30d": 30,
            "90d": 90,
            "1y": 365
        }
        days = period_map.get(period, 30)
        return end_date - timedelta(days=days)



    # Ajoutez ces méthodes à la classe AnalyticsService

    def get_jobs_by_day(self, db: Session, days: int = 30) -> List[Dict[str, Any]]:
        """Récupère le nombre d'offres par jour."""
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            daily_stats = db.query(
                func.date(OffreEmploiBrute.posted_date).label('date'),
                func.count(OffreEmploiBrute.id).label('count')
            ).filter(
                OffreEmploiBrute.posted_date >= start_date,
                OffreEmploiBrute.posted_date <= end_date
            ).group_by(
                func.date(OffreEmploiBrute.posted_date)
            ).order_by(
                func.date(OffreEmploiBrute.posted_date)
            ).all()
            
            return [{
                "date": stat.date.isoformat() if stat.date else None,
                "count": stat.count,
                "day_name": stat.date.strftime('%A') if stat.date else None
            } for stat in daily_stats]
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des offres par jour: {str(e)}")
            raise

    def get_top_jobs(self, db: Session, period: str = "30d", limit: int = 20) -> List[Dict[str, Any]]:
        """Récupère les métiers qui recrutent le plus."""
        try:
            end_date = datetime.now()
            start_date = self._get_start_date(end_date, period)
            
            jobs = db.query(
                OffreEmploiEnrichie.extracted_job_title.label('job_title'),
                func.count(OffreEmploiEnrichie.id).label('count'),
                func.avg(OffreEmploiEnrichie.extracted_salary_min).label('avg_salary_min'),
                func.avg(OffreEmploiEnrichie.extracted_salary_max).label('avg_salary_max'),
                func.count(OffreEmploiBrute.company_name.distinct()).label('unique_companies')
            ).join(
                OffreEmploiBrute,
                OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.extracted_job_title.isnot(None)
            ).group_by(
                OffreEmploiEnrichie.extracted_job_title
            ).order_by(
                desc('count')
            ).limit(limit).all()
            
            total_offers = sum(job.count for job in jobs)
            
            return [{
                "job_title": self._safe_get(job, 'job_title'),
                "count": self._safe_get(job, 'count', 0),
                "percentage": round((job.count / total_offers * 100), 2) if total_offers > 0 else 0,
                "avg_salary_min": float(self._safe_get(job, 'avg_salary_min')) if self._safe_get(job, 'avg_salary_min') else None,
                "avg_salary_max": float(self._safe_get(job, 'avg_salary_max')) if self._safe_get(job, 'avg_salary_max') else None,
                "unique_companies": self._safe_get(job, 'unique_companies', 0)
            } for job in jobs]
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des top métiers: {str(e)}")
            raise

    def get_education_level_distribution(self, db: Session, period: str = "30d") -> List[Dict[str, Any]]:
        """Récupère la répartition par niveau d'étude."""
        try:
            end_date = datetime.now()
            start_date = self._get_start_date(end_date, period)
            
            education_levels = db.query(
                OffreEmploiEnrichie.education_level,
                func.count(OffreEmploiEnrichie.id).label('count')
            ).join(
                OffreEmploiBrute,
                OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.education_level.isnot(None)
            ).group_by(
                OffreEmploiEnrichie.education_level
            ).order_by(
                desc('count')
            ).all()
            
            total = sum(level.count for level in education_levels)
            
            return [{
                "level": self._safe_get(level, 'education_level'),
                "count": self._safe_get(level, 'count', 0),
                "percentage": round((level.count / total * 100), 2) if total > 0 else 0
            } for level in education_levels]
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des niveaux d'étude: {str(e)}")
            raise

    def get_hierarchical_data(self, db: Session, period: str = "90d") -> Dict[str, Any]:
        """Prépare les données pour la visualisation en TreeMap (secteur > métier > compétence)."""
        try:
            end_date = datetime.now()
            start_date = self._get_start_date(end_date, period)
            
            # Récupération des secteurs avec leurs métiers
            sector_job_query = db.query(
                OffreEmploiEnrichie.extracted_sector,
                OffreEmploiEnrichie.extracted_job_title,
                func.count(OffreEmploiEnrichie.id).label('job_count')
            ).join(
                OffreEmploiBrute,
                OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.extracted_sector.isnot(None),
                OffreEmploiEnrichie.extracted_job_title.isnot(None)
            ).group_by(
                OffreEmploiEnrichie.extracted_sector,
                OffreEmploiEnrichie.extracted_job_title
            ).order_by(
                OffreEmploiEnrichie.extracted_sector,
                desc('job_count')
            ).all()
            
            # Construction de la hiérarchie
            hierarchy = {}
            for row in sector_job_query:
                sector = row.extracted_sector
                job = row.extracted_job_title
                
                if sector not in hierarchy:
                    hierarchy[sector] = {}
                
                if job not in hierarchy[sector]:
                    hierarchy[sector][job] = row.job_count
            
            # Formatage pour TreeMap
            treemap_data = {
                "name": "Marché",
                "children": []
            }
            
            for sector, jobs in hierarchy.items():
                sector_node = {
                    "name": sector,
                    "children": []
                }
                
                for job, count in jobs.items():
                    # Récupération des compétences principales pour ce métier
                    top_skills = db.query(
                        func.unnest(OffreEmploiEnrichie.extracted_skills).label('skill'),
                        func.count(OffreEmploiEnrichie.id).label('skill_count')
                    ).join(
                        OffreEmploiBrute,
                        OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                    ).filter(
                        OffreEmploiBrute.posted_date.between(start_date, end_date),
                        OffreEmploiEnrichie.extracted_sector == sector,
                        OffreEmploiEnrichie.extracted_job_title == job,
                        OffreEmploiEnrichie.extracted_skills.isnot(None)
                    ).group_by(
                        'skill'
                    ).order_by(
                        desc('skill_count')
                    ).limit(5).all()
                    
                    job_node = {
                        "name": job,
                        "value": count,
                        "children": [{"name": skill.skill, "value": skill.skill_count} for skill in top_skills]
                    }
                    sector_node["children"].append(job_node)
                
                treemap_data["children"].append(sector_node)
            
            return treemap_data
            
        except Exception as e:
            logger.error(f"Erreur lors de la génération des données hiérarchiques: {str(e)}")
            raise