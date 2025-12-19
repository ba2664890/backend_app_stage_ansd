"""
Service avancé pour l'analyse multidimensionnelle du marché de l'emploi au Sénégal.
Version enrichie avec analyses complètes et visualisations innovantes.
"""

from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, case, and_, or_, text, distinct
from datetime import datetime, timedelta
from collections import Counter, defaultdict
import logging

from ..models.database_models import OffreEmploiBrute, OffreEmploiEnrichie, JobStatistics
from ..models.api_models import (
    JobAnalyticsResponse, JobStatisticsResponse, DashboardStats,
    GeographicStats, HeatmapData, SalaryByExperience, 
    CompanyHiringStats, ContractTypeEvolution, FullAnalyticsResponse
)

logger = logging.getLogger(__name__)

class AdvancedAnalyticsService:
    """Service avancé pour l'analyse multidimensionnelle du marché de l'emploi."""
    
    def __init__(self):
        """Initialise le service d'analytics avancé."""
        self.date_format = '%Y-%m'
        self.senegal_regions = {
            "dakar": {"lat": 14.7167, "lng": -17.4677, "region": "Dakar"},
            "thies": {"lat": 14.8056, "lng": -16.9447, "region": "Thiès"},
            "thiès": {"lat": 14.8056, "lng": -16.9447, "region": "Thiès"},
            "saint-louis": {"lat": 16.0179, "lng": -16.4896, "region": "Saint-Louis"},
            "kaolack": {"lat": 14.1828, "lng": -16.2533, "region": "Kaolack"},
            "ziguinchor": {"lat": 12.5570, "lng": -16.2677, "region": "Ziguinchor"},
            "tambacounda": {"lat": 13.7700, "lng": -13.6733, "region": "Tambacounda"},
            "louga": {"lat": 15.6167, "lng": -16.2333, "region": "Louga"},
            "diourbel": {"lat": 14.6533, "lng": -16.2369, "region": "Diourbel"},
            "fatick": {"lat": 14.3550, "lng": -16.4111, "region": "Fatick"},
            "kaffrine": {"lat": 14.8500, "lng": -15.5500, "region": "Kaffrine"},
            "kedougou": {"lat": 12.5570, "lng": -12.1800, "region": "Kédougou"},
            "kolda": {"lat": 12.8833, "lng": -14.8000, "region": "Kolda"},
            "matam": {"lat": 15.6500, "lng": -13.2500, "region": "Matam"},
            "sedhiou": {"lat": 12.7081, "lng": -15.5569, "region": "Sédhiou"},
        }

    def _safe_get(self, obj, attr, default=None):
        """Récupère un attribut en toute sécurité."""
        try:
            return getattr(obj, attr, default)
        except:
            return default

    def _get_period_bounds(self, period: str = "30d") -> Tuple[datetime, datetime]:
        """Convertit une période en dates de début/fin."""
        end_date = datetime.now()
        period_map = {
            "1d": 1, "3d": 3, "7d": 7, "14d": 14,
            "30d": 30, "90d": 90, "180d": 180, "365d": 365,
            "1y": 365, "2y": 730
        }
        days = period_map.get(period.lower(), 30)
        start_date = end_date - timedelta(days=days)
        return start_date, end_date

    def _execute_salary_query(self, db: Session, query_filter) -> Dict[str, Optional[float]]:
        """Exécute une requête de statistiques salariales de manière sûre."""
        try:
            stats = db.query(
                func.avg(OffreEmploiEnrichie.extracted_salary_min).label('avg_min'),
                func.avg(OffreEmploiEnrichie.extracted_salary_max).label('avg_max')
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                query_filter,
                OffreEmploiEnrichie.extracted_salary_min.isnot(None)
            ).first()

            return {
                'avg_min': float(stats.avg_min) if stats and stats.avg_min else None,
                'avg_max': float(stats.avg_max) if stats and stats.avg_max else None
            }
        except:
            return {'avg_min': None, 'avg_max': None}

    # ==================== ANALYSES PRINCIPALES ====================

    def get_complete_analytics(self, db: Session, period: str = "90d") -> Dict[str, Any]:
        """Récupère une analyse complète et multidimensionnelle du marché."""
        try:
            start_date, end_date = self._get_period_bounds(period)
            
            return FullAnalyticsResponse(
                dashboard=self.get_enhanced_dashboard(db, start_date, end_date),
                geographic=self.get_geographic_analysis(db, start_date, end_date),
                heatmap=self.get_skills_sector_heatmap(db, start_date, end_date),
                salary_by_experience=self.get_salary_by_experience(db, start_date, end_date),
                top_companies=self.get_top_hiring_companies(db, start_date, end_date),
                contract_evolution=self.get_contract_type_evolution(db, start_date, end_date),
                evolution_rates=self.get_market_evolution_rates(db, start_date, end_date),
                generated_at=datetime.now()
            )
        except Exception as e:
            logger.error(f"Erreur analyse complète: {e}", exc_info=True)
            raise

    # ==================== TABLEAU DE BORD ENRICHI ====================

    def get_enhanced_dashboard(self, db: Session, start_date: datetime, end_date: datetime) -> DashboardStats:
        """Tableau de bord enrichi avec métriques clés et tendances."""
        try:
            base_stats = db.query(
                func.count(distinct(OffreEmploiBrute.id)).label('total_offers'),
                func.count(distinct(OffreEmploiBrute.company_name)).label('total_companies'),
                func.count(distinct(OffreEmploiBrute.location)).label('total_locations')
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date)
            ).first()

            today_start = datetime.now().replace(hour=0, minute=0, second=0)
            offers_today = db.query(func.count(OffreEmploiBrute.id)).filter(
                OffreEmploiBrute.created_at >= today_start
            ).scalar() or 0

            offers_yesterday = db.query(func.count(OffreEmploiBrute.id)).filter(
                OffreEmploiBrute.created_at >= today_start - timedelta(days=1),
                OffreEmploiBrute.created_at < today_start
            ).scalar() or 0

            salary_stats = self._execute_salary_query(
                db, 
                OffreEmploiBrute.posted_date.between(start_date, end_date)
            )

            return DashboardStats(
                total_offers=base_stats.total_offers or 0,
                total_companies=base_stats.total_companies or 0,
                total_locations=base_stats.total_locations or 0,
                offers_this_month=offers_yesterday,
                offers_today=offers_today,
                avg_salary_min=salary_stats.get('avg_min'),
                avg_salary_max=salary_stats.get('avg_max'),
                top_sectors=self._get_top_sectors_with_growth(db, start_date, end_date),
                top_skills=self._get_top_skills_with_trend(db, start_date, end_date),
                contract_type_distribution=self._get_distribution(db, start_date, end_date, 'contract'),
                experience_level_distribution=self._get_distribution(db, start_date, end_date, 'experience'),
                monthly_trend=self._get_daily_trend(db, 90)
            )
        except Exception as e:
            logger.error(f"Erreur dashboard enrichi: {e}", exc_info=True)
            raise

    def _get_distribution(self, db: Session, start_date: datetime, end_date: datetime, dist_type: str) -> List[Dict[str, Any]]:
        """Récupère la distribution pour un type donné (contract ou experience)."""
        try:
            if dist_type == 'contract':
                query = db.query(
                    OffreEmploiEnrichie.extracted_contract_type.label('key'),
                    func.count(OffreEmploiEnrichie.id).label('count')
                ).filter(
                    OffreEmploiEnrichie.extracted_contract_type.isnot(None)
                )
            else:
                query = db.query(
                    OffreEmploiEnrichie.job_level.label('key'),
                    func.count(OffreEmploiEnrichie.id).label('count')
                ).filter(
                    OffreEmploiEnrichie.job_level.isnot(None)
                )

            results = query.join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date)
            ).group_by('key').all()

            total = sum(r.count for r in results)
            return [
                {
                    "type" if dist_type == 'contract' else "level": r.key or "Non spécifié",
                    "count": r.count,
                    "percentage": round((r.count / total * 100), 2) if total > 0 else 0
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"Erreur distribution {dist_type}: {e}")
            return []

    # ==================== TAUX D'ÉVOLUTION DU MARCHÉ ====================

    def get_market_evolution_rates(self, db: Session, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Calcule les taux d'évolution clés du marché."""
        try:
            period_duration = (end_date - start_date).days
            if period_duration == 0:
                period_duration = 1
            previous_start = start_date - timedelta(days=period_duration)
            previous_end = start_date

            metrics = ['offers', 'companies', 'locations', 'sectors', 'skills']
            evolution_data = {}

            for metric in metrics:
                current, previous = self._get_metric_count(db, metric, start_date, end_date, previous_start, previous_end)
                growth = self._calculate_growth(current, previous)
                
                trend_map = {
                    'offers': "positive" if growth > 0 else "negative" if growth < 0 else "stable",
                    'companies': "positive" if growth > 0 else "negative" if growth < 0 else "stable",
                    'locations': "expanding" if growth > 0 else "contracting" if growth < 0 else "stable",
                    'sectors': "diversifying" if growth > 0 else "consolidating" if growth < 0 else "stable",
                    'skills': "expanding" if growth > 0 else "contracting" if growth < 0 else "stable"
                }

                evolution_data[f'{metric}_growth'] = {
                    "current": current,
                    "previous": previous,
                    "rate": growth,
                    "trend": trend_map[metric]
                }

            evolution_data["market_health"] = self._calculate_market_health(
                evolution_data['offers_growth']['rate'],
                evolution_data['companies_growth']['rate'],
                evolution_data['sectors_growth']['rate']
            )

            return evolution_data
        except Exception as e:
            logger.error(f"Erreur taux d'évolution: {e}")
            return {}

    def _get_metric_count(self, db: Session, metric: str, start_date: datetime, end_date: datetime, 
                         previous_start: datetime, previous_end: datetime) -> Tuple[int, int]:
        """Récupère le compte pour une métrique donnée sur deux périodes."""
        try:
            if metric == 'offers':
                current = db.query(func.count(OffreEmploiBrute.id)).filter(
                    OffreEmploiBrute.posted_date.between(start_date, end_date)
                ).scalar() or 0
                previous = db.query(func.count(OffreEmploiBrute.id)).filter(
                    OffreEmploiBrute.posted_date.between(previous_start, previous_end)
                ).scalar() or 0
            elif metric == 'companies':
                current = db.query(func.count(distinct(OffreEmploiBrute.company_name))).filter(
                    OffreEmploiBrute.posted_date.between(start_date, end_date),
                    OffreEmploiBrute.company_name.isnot(None)
                ).scalar() or 0
                previous = db.query(func.count(distinct(OffreEmploiBrute.company_name))).filter(
                    OffreEmploiBrute.posted_date.between(previous_start, previous_end),
                    OffreEmploiBrute.company_name.isnot(None)
                ).scalar() or 0
            elif metric == 'locations':
                current = db.query(func.count(distinct(OffreEmploiBrute.location))).filter(
                    OffreEmploiBrute.posted_date.between(start_date, end_date),
                    OffreEmploiBrute.location.isnot(None)
                ).scalar() or 0
                previous = db.query(func.count(distinct(OffreEmploiBrute.location))).filter(
                    OffreEmploiBrute.posted_date.between(previous_start, previous_end),
                    OffreEmploiBrute.location.isnot(None)
                ).scalar() or 0
            elif metric == 'sectors':
                current = db.query(func.count(distinct(OffreEmploiEnrichie.extracted_sector))).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    OffreEmploiBrute.posted_date.between(start_date, end_date),
                    OffreEmploiEnrichie.extracted_sector.isnot(None)
                ).scalar() or 0
                previous = db.query(func.count(distinct(OffreEmploiEnrichie.extracted_sector))).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    OffreEmploiBrute.posted_date.between(previous_start, previous_end),
                    OffreEmploiEnrichie.extracted_sector.isnot(None)
                ).scalar() or 0
            else:  # skills
                current = self._count_unique_skills(db, start_date, end_date)
                previous = self._count_unique_skills(db, previous_start, previous_end)

            return current, previous
        except:
            return 0, 0

    def _calculate_growth(self, current: int, previous: int) -> float:
        """Calcule le taux de croissance en pourcentage."""
        if previous == 0:
            return 100.0 if current > 0 else 0.0
        return round(((current - previous) / previous) * 100, 2)

    def _count_unique_skills(self, db: Session, start_date: datetime, end_date: datetime) -> int:
        """Compte le nombre de compétences uniques."""
        try:
            result = db.query(
                func.count(distinct(func.unnest(OffreEmploiEnrichie.extracted_skills)))
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.extracted_skills.isnot(None)
            ).scalar()
            return result or 0
        except:
            return 0

    def _calculate_market_health(self, offers_growth: float, companies_growth: float, sectors_growth: float) -> str:
        """Détermine la santé globale du marché."""
        avg_growth = (offers_growth + companies_growth + sectors_growth) / 3
        
        if avg_growth > 15:
            return "excellent"
        elif avg_growth > 5:
            return "good"
        elif avg_growth > -5:
            return "stable"
        elif avg_growth > -15:
            return "declining"
        else:
            return "concerning"

    # ==================== ANALYSES AVANCÉES SUPPLÉMENTAIRES ====================

    def get_skills_co_occurrence(self, db: Session, start_date: datetime, end_date: datetime, min_count: int = 5) -> List[Dict[str, Any]]:
        """Analyse de co-occurrence des compétences."""
        try:
            offers_skills = db.query(
                OffreEmploiEnrichie.extracted_skills
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.extracted_skills.isnot(None),
                func.array_length(OffreEmploiEnrichie.extracted_skills, 1) >= 2
            ).all()

            co_occurrences = Counter()
            for (skills,) in offers_skills:
                if skills and len(skills) >= 2:
                    for i, skill1 in enumerate(skills):
                        for skill2 in skills[i+1:]:
                            pair = tuple(sorted([skill1, skill2]))
                            co_occurrences[pair] += 1

            return [
                {
                    "skill_1": skill1,
                    "skill_2": skill2,
                    "co_occurrence_count": count,
                    "strength": "high" if count > 20 else "medium" if count > 10 else "low"
                }
                for (skill1, skill2), count in co_occurrences.most_common(50)
                if count >= min_count
            ]
        except Exception as e:
            logger.error(f"Erreur co-occurrence compétences: {e}")
            return []

    def get_sector_skills_matrix(self, db: Session, start_date: datetime, end_date: datetime) -> Dict[str, Dict[str, int]]:
        """Matrice complète secteurs x compétences."""
        try:
            top_sectors = db.query(
                OffreEmploiEnrichie.extracted_sector
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.extracted_sector.isnot(None)
            ).group_by(
                OffreEmploiEnrichie.extracted_sector
            ).order_by(func.count(OffreEmploiEnrichie.id).desc()).limit(20).all()

            matrix = {}
            for (sector,) in top_sectors:
                skills = db.query(
                    func.unnest(OffreEmploiEnrichie.extracted_skills).label('skill'),
                    func.count(OffreEmploiEnrichie.id).label('count')
                ).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    OffreEmploiBrute.posted_date.between(start_date, end_date),
                    OffreEmploiEnrichie.extracted_sector == sector,
                    OffreEmploiEnrichie.extracted_skills.isnot(None)
                ).group_by('skill').all()

                matrix[sector] = {s.skill: s.count for s in skills}

            return matrix
        except Exception as e:
            logger.error(f"Erreur matrice secteurs-compétences: {e}")
            return {}

    def get_job_posting_velocity(self, db: Session, period: str = "90d") -> Dict[str, Any]:
        """Vélocité de publication des offres par jour/semaine."""
        try:
            start_date, end_date = self._get_period_bounds(period)

            daily = db.query(
                func.date(OffreEmploiBrute.posted_date).label('date'),
                func.count(OffreEmploiBrute.id).label('count')
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date)
            ).group_by(func.date(OffreEmploiBrute.posted_date)).order_by(func.date(OffreEmploiBrute.posted_date)).all()

            daily_data = [{"date": d.date.isoformat(), "count": d.count} for d in daily if d.date]

            weekly = db.query(
                func.date_trunc('week', OffreEmploiBrute.posted_date).label('week'),
                func.count(OffreEmploiBrute.id).label('count')
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date)
            ).group_by(func.date_trunc('week', OffreEmploiBrute.posted_date)).order_by(func.date_trunc('week', OffreEmploiBrute.posted_date)).all()

            weekly_data = [{"week": w.week.strftime('%Y-W%W'), "count": w.count} for w in weekly if w.week]

            counts = [d.count for d in daily]
            avg_daily = sum(counts) / len(counts) if counts else 0
            peak_day = max(daily, key=lambda x: x.count) if daily else None

            return {
                "daily": daily_data,
                "weekly": weekly_data,
                "statistics": {
                    "avg_daily": round(avg_daily, 2),
                    "peak_day": {
                        "date": peak_day.date.isoformat() if peak_day and peak_day.date else None,
                        "count": peak_day.count if peak_day else 0
                    },
                    "total_days": len(daily_data),
                    "total_offers": sum(counts)
                }
            }
        except Exception as e:
            logger.error(f"Erreur vélocité publications: {e}")
            return {}

    def get_emerging_skills(self, db: Session, period: str = "90d", growth_threshold: float = 50.0) -> List[Dict[str, Any]]:
        """Identifie les compétences émergentes."""
        try:
            start_date, end_date = self._get_period_bounds(period)
            mid_date = start_date + (end_date - start_date) / 2

            first_half = db.query(
                func.unnest(OffreEmploiEnrichie.extracted_skills).label('skill'),
                func.count(OffreEmploiEnrichie.id).label('count')
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, mid_date),
                OffreEmploiEnrichie.extracted_skills.isnot(None)
            ).group_by('skill').all()

            second_half = db.query(
                func.unnest(OffreEmploiEnrichie.extracted_skills).label('skill'),
                func.count(OffreEmploiEnrichie.id).label('count')
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date.between(mid_date, end_date),
                OffreEmploiEnrichie.extracted_skills.isnot(None)
            ).group_by('skill').all()

            first_half_dict = {s.skill: s.count for s in first_half}

            emerging = []
            for s in second_half:
                first_count = first_half_dict.get(s.skill, 0)
                growth = self._calculate_growth(s.count, first_count)
                
                if growth >= growth_threshold:
                    emerging.append({
                        "skill": s.skill,
                        "first_period_count": first_count,
                        "second_period_count": s.count,
                        "growth_rate": growth,
                        "status": "new" if first_count == 0 else "growing"
                    })

            emerging.sort(key=lambda x: x['growth_rate'], reverse=True)
            return emerging[:30]
        except Exception as e:
            logger.error(f"Erreur compétences émergentes: {e}")
            return []

    def get_contract_type_by_sector(self, db: Session, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Distribution des types de contrat par secteur."""
        try:
            data = db.query(
                OffreEmploiEnrichie.extracted_sector.label('sector'),
                OffreEmploiEnrichie.extracted_contract_type.label('contract'),
                func.count(OffreEmploiEnrichie.id).label('count')
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.extracted_sector.isnot(None),
                OffreEmploiEnrichie.extracted_contract_type.isnot(None)
            ).group_by(
                OffreEmploiEnrichie.extracted_sector,
                OffreEmploiEnrichie.extracted_contract_type
            ).order_by(desc('count')).all()

            sectors_data = defaultdict(lambda: {"sector": "", "contracts": {}, "total": 0})
            for row in data:
                sectors_data[row.sector]["sector"] = row.sector
                sectors_data[row.sector]["contracts"][row.contract] = row.count
                sectors_data[row.sector]["total"] += row.count

            result = []
            for sector_name, sector_data in sectors_data.items():
                contracts_with_pct = {
                    contract: {
                        "count": count,
                        "percentage": round((count / sector_data["total"] * 100), 2)
                    }
                    for contract, count in sector_data["contracts"].items()
                }
                
                result.append({
                    "sector": sector_name,
                    "contracts": contracts_with_pct,
                    "total_offers": sector_data["total"]
                })

            result.sort(key=lambda x: x['total_offers'], reverse=True)
            return result[:15]
        except Exception as e:
            logger.error(f"Erreur contrats par secteur: {e}")
            return []

    def get_experience_level_distribution_by_sector(self, db: Session, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Distribution des niveaux d'expérience par secteur."""
        try:
            data = db.query(
                OffreEmploiEnrichie.extracted_sector.label('sector'),
                OffreEmploiEnrichie.job_level.label('level'),
                func.count(OffreEmploiEnrichie.id).label('count')
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.extracted_sector.isnot(None),
                OffreEmploiEnrichie.job_level.isnot(None)
            ).group_by(
                OffreEmploiEnrichie.extracted_sector,
                OffreEmploiEnrichie.job_level
            ).all()

            sectors_data = defaultdict(lambda: {"sector": "", "levels": {}, "total": 0})
            for row in data:
                sectors_data[row.sector]["sector"] = row.sector
                sectors_data[row.sector]["levels"][row.level] = row.count
                sectors_data[row.sector]["total"] += row.count

            result = []
            for sector_name, sector_data in sectors_data.items():
                levels_with_pct = {
                    level: {
                        "count": count,
                        "percentage": round((count / sector_data["total"] * 100), 2)
                    }
                    for level, count in sector_data["levels"].items()
                }
                
                result.append({
                    "sector": sector_name,
                    "experience_levels": levels_with_pct,
                    "total_offers": sector_data["total"]
                })

            result.sort(key=lambda x: x['total_offers'], reverse=True)
            return result[:15]
        except Exception as e:
            logger.error(f"Erreur niveaux d'expérience par secteur: {e}")
            return []

    def get_source_performance(self, db: Session, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Performance des différentes sources de scraping."""
        try:
            sources = db.query(
                OffreEmploiBrute.spider_source.label('source'),
                func.count(OffreEmploiBrute.id).label('total_offers'),
                func.count(distinct(OffreEmploiBrute.company_name)).label('unique_companies'),
                func.count(case((OffreEmploiBrute.description.isnot(None), 1))).label('offers_with_description'),
                func.count(case((OffreEmploiBrute.salary.isnot(None), 1))).label('offers_with_salary')
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date)
            ).group_by(
                OffreEmploiBrute.spider_source
            ).all()

            result = []
            for s in sources:
                quality_score = 0
                if s.total_offers > 0:
                    desc_rate = (s.offers_with_description / s.total_offers) * 100
                    salary_rate = (s.offers_with_salary / s.total_offers) * 100
                    quality_score = round((desc_rate + salary_rate) / 2, 2)

                result.append({
                    "source": s.source,
                    "total_offers": s.total_offers,
                    "unique_companies": s.unique_companies,
                    "data_completeness": {
                        "description_rate": round((s.offers_with_description / s.total_offers * 100), 2) if s.total_offers > 0 else 0,
                        "salary_rate": round((s.offers_with_salary / s.total_offers * 100), 2) if s.total_offers > 0 else 0
                    },
                    "quality_score": quality_score
                })

            result.sort(key=lambda x: x['total_offers'], reverse=True)
            return result
        except Exception as e:
            logger.error(f"Erreur performance sources: {e}")
            return []

    # ==================== ANALYSES TEMPORELLES AVANCÉES ====================

    def get_seasonal_trends(self, db: Session, days: int = 730) -> Dict[str, Any]:
        """Analyse des tendances quotidiennes (patterns hebdomadaires)."""
        try:
            start_date = datetime.now() - timedelta(days=days)
            
            # Analyse par jour de la semaine
            dow_patterns = db.query(
                func.extract('dow', OffreEmploiBrute.posted_date).label('day_of_week'),
                func.count(OffreEmploiBrute.id).label('avg_count')
            ).filter(
                OffreEmploiBrute.posted_date >= start_date
            ).group_by(
                func.extract('dow', OffreEmploiBrute.posted_date)
            ).order_by('day_of_week').all()

            day_names = ['Dimanche', 'Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi']
            
            total_days = len(set(db.query(func.date(OffreEmploiBrute.posted_date)).filter(
                OffreEmploiBrute.posted_date >= start_date
            ).all()))
            
            seasonal_data = []
            max_count = max((m.avg_count for m in dow_patterns), default=0)
            
            for pattern in dow_patterns:
                day_idx = int(pattern.day_of_week)
                avg_daily = pattern.avg_count / (total_days / 7) if total_days > 0 else 0
                intensity = "high" if pattern.avg_count > max_count * 0.8 else "medium" if pattern.avg_count > max_count * 0.5 else "low"
                
                seasonal_data.append({
                    "day_number": int(pattern.day_of_week),
                    "day_name": day_names[day_idx],
                    "avg_offers": round(avg_daily, 2),
                    "total_offers": pattern.avg_count,
                    "intensity": intensity
                })

            peak_days = sorted(seasonal_data, key=lambda x: x['total_offers'], reverse=True)[:3]
            low_days = sorted(seasonal_data, key=lambda x: x['total_offers'])[:3]

            return {
                "daily_pattern": seasonal_data,
                "peak_days": [d['day_name'] for d in peak_days],
                "low_days": [d['day_name'] for d in low_days],
                "pattern_strength": self._calculate_pattern_strength(seasonal_data)
            }
        except Exception as e:
            logger.error(f"Erreur tendances saisonnières: {e}")
            return {}

    def _calculate_pattern_strength(self, pattern_data: List[Dict]) -> str:
        """Calcule la force du pattern quotidien."""
        if not pattern_data:
            return "unknown"
        
        counts = [d['total_offers'] for d in pattern_data]
        avg = sum(counts) / len(counts)
        variance = sum((x - avg) ** 2 for x in counts) / len(counts)
        std_dev = variance ** 0.5
        cv = (std_dev / avg) if avg > 0 else 0

        if cv > 0.3:
            return "strong"
        elif cv > 0.15:
            return "moderate"
        else:
            return "weak"

    def get_day_of_week_patterns(self, db: Session, period: str = "90d") -> List[Dict[str, Any]]:
        """Analyse les patterns par jour de la semaine."""
        try:
            start_date, end_date = self._get_period_bounds(period)

            dow_data = db.query(
                func.extract('dow', OffreEmploiBrute.posted_date).label('day_of_week'),
                func.count(OffreEmploiBrute.id).label('count')
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date)
            ).group_by(
                func.extract('dow', OffreEmploiBrute.posted_date)
            ).order_by('day_of_week').all()

            day_names = ['Dimanche', 'Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi']
            
            total = sum(d.count for d in dow_data)
            result = []
            
            for dow in dow_data:
                day_idx = int(dow.day_of_week)
                percentage = round((dow.count / total * 100), 2) if total > 0 else 0
                
                result.append({
                    "day_number": day_idx,
                    "day_name": day_names[day_idx],
                    "count": dow.count,
                    "percentage": percentage,
                    "is_weekend": day_idx in [0, 6]
                })

            return result
        except Exception as e:
            logger.error(f"Erreur patterns jour de la semaine: {e}")
            return []

    def get_sector_momentum(self, db: Session, period: str = "180d") -> List[Dict[str, Any]]:
        """Calcule le 'momentum' de chaque secteur."""
        try:
            start_date, end_date = self._get_period_bounds(period)
            total_days = max((end_date - start_date).days, 1)
            
            period_1_end = start_date + timedelta(days=total_days // 3)
            period_2_end = period_1_end + timedelta(days=total_days // 3)

            sectors = db.query(
                OffreEmploiEnrichie.extracted_sector
            ).filter(
                OffreEmploiEnrichie.extracted_sector.isnot(None)
            ).distinct().all()

            result = []
            for (sector,) in sectors:
                p1_count = db.query(func.count(OffreEmploiEnrichie.id)).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    OffreEmploiBrute.posted_date.between(start_date, period_1_end),
                    OffreEmploiEnrichie.extracted_sector == sector
                ).scalar() or 0

                p2_count = db.query(func.count(OffreEmploiEnrichie.id)).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    OffreEmploiBrute.posted_date.between(period_1_end, period_2_end),
                    OffreEmploiEnrichie.extracted_sector == sector
                ).scalar() or 0

                p3_count = db.query(func.count(OffreEmploiEnrichie.id)).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    OffreEmploiBrute.posted_date.between(period_2_end, end_date),
                    OffreEmploiEnrichie.extracted_sector == sector
                ).scalar() or 0

                if p1_count > 0 and p2_count > 0:
                    growth_1_2 = ((p2_count - p1_count) / p1_count) * 100
                    growth_2_3 = ((p3_count - p2_count) / p2_count) * 100
                    momentum = growth_2_3 - growth_1_2
                    
                    total = p1_count + p2_count + p3_count
                    if total >= 5:
                        result.append({
                            "sector": sector,
                            "period_1_count": p1_count,
                            "period_2_count": p2_count,
                            "period_3_count": p3_count,
                            "total_count": total,
                            "momentum": round(momentum, 2),
                            "trend": "accelerating" if momentum > 10 else "decelerating" if momentum < -10 else "stable"
                        })

            result.sort(key=lambda x: abs(x['momentum']), reverse=True)
            return result[:20]
        except Exception as e:
            logger.error(f"Erreur momentum secteurs: {e}")
            return []

    def get_skill_saturation_index(self, db: Session, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Indice de saturation des compétences."""
        try:
            total_offers = db.query(func.count(OffreEmploiBrute.id)).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date)
            ).scalar() or 1

            skills = db.query(
                func.unnest(OffreEmploiEnrichie.extracted_skills).label('skill'),
                func.count(OffreEmploiEnrichie.id).label('count')
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.extracted_skills.isnot(None)
            ).group_by('skill').all()

            result = []
            for skill in skills:
                penetration = (skill.count / total_offers) * 100
                
                if penetration > 50:
                    saturation = "very_high"
                elif penetration > 30:
                    saturation = "high"
                elif penetration > 15:
                    saturation = "medium"
                elif penetration > 5:
                    saturation = "low"
                else:
                    saturation = "very_low"

                result.append({
                    "skill": skill.skill,
                    "demand_count": skill.count,
                    "market_penetration": round(penetration, 2),
                    "saturation_level": saturation,
                    "opportunity_score": round((100 - penetration) / 10, 2)
                })

            result.sort(key=lambda x: x['demand_count'], reverse=True)
            return result[:50]
        except Exception as e:
            logger.error(f"Erreur indice saturation: {e}")
            return []

    # ==================== ANALYSES COMPARATIVES ====================

    def get_sector_comparison(self, db: Session, sectors: List[str], start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Compare plusieurs secteurs sur différentes dimensions."""
        try:
            comparison = {}
            for sector in sectors:
                offer_count = db.query(func.count(OffreEmploiEnrichie.id)).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    OffreEmploiBrute.posted_date.between(start_date, end_date),
                    OffreEmploiEnrichie.extracted_sector == sector
                ).scalar() or 0

                company_count = db.query(func.count(distinct(OffreEmploiBrute.company_name))).join(
                    OffreEmploiEnrichie, OffreEmploiBrute.id == OffreEmploiEnrichie.offre_id
                ).filter(
                    OffreEmploiBrute.posted_date.between(start_date, end_date),
                    OffreEmploiEnrichie.extracted_sector == sector,
                    OffreEmploiBrute.company_name.isnot(None)
                ).scalar() or 0

                top_skills = db.query(
                    func.unnest(OffreEmploiEnrichie.extracted_skills).label('skill')
                ).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    OffreEmploiBrute.posted_date.between(start_date, end_date),
                    OffreEmploiEnrichie.extracted_sector == sector,
                    OffreEmploiEnrichie.extracted_skills.isnot(None)
                ).group_by('skill').order_by(func.count(OffreEmploiEnrichie.id).desc()).limit(5).all()

                contract_types = db.query(
                    OffreEmploiEnrichie.extracted_contract_type,
                    func.count(OffreEmploiEnrichie.id).label('count')
                ).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    OffreEmploiBrute.posted_date.between(start_date, end_date),
                    OffreEmploiEnrichie.extracted_sector == sector,
                    OffreEmploiEnrichie.extracted_contract_type.isnot(None)
                ).group_by(OffreEmploiEnrichie.extracted_contract_type).all()

                salary_stats = self._execute_salary_query(
                    db,
                    and_(
                        OffreEmploiBrute.posted_date.between(start_date, end_date),
                        OffreEmploiEnrichie.extracted_sector == sector
                    )
                )

                comparison[sector] = {
                    "total_offers": offer_count,
                    "active_companies": company_count,
                    "avg_offers_per_company": round(offer_count / company_count, 2) if company_count > 0 else 0,
                    "top_skills": [s[0] for s in top_skills],
                    "contract_distribution": {ct[0]: ct[1] for ct in contract_types},
                    "avg_salary_min": salary_stats.get('avg_min'),
                    "avg_salary_max": salary_stats.get('avg_max')
                }

            return comparison
        except Exception as e:
            logger.error(f"Erreur comparaison secteurs: {e}")
            return {}

    # ==================== ANALYSES POUR RECOMMANDATIONS ====================

    def get_similar_job_clusters(self, db: Session, start_date: datetime, end_date: datetime, min_cluster_size: int = 3) -> List[Dict[str, Any]]:
        """Identifie des clusters d'emplois similaires."""
        try:
            offers = db.query(
                OffreEmploiEnrichie.id,
                OffreEmploiEnrichie.extracted_sector,
                OffreEmploiEnrichie.extracted_skills,
                OffreEmploiEnrichie.job_level
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.extracted_skills.isnot(None),
                func.array_length(OffreEmploiEnrichie.extracted_skills, 1) >= 2
            ).limit(1000).all()

            clusters = defaultdict(list)
            for offer in offers:
                if offer.extracted_sector and offer.job_level:
                    key = f"{offer.extracted_sector}_{offer.job_level}"
                    clusters[key].append({
                        "id": str(offer.id),
                        "skills": set(offer.extracted_skills or [])
                    })

            result = []
            for cluster_key, jobs in clusters.items():
                if len(jobs) >= min_cluster_size:
                    all_skills = [s for job in jobs for s in job["skills"]]
                    skill_counts = Counter(all_skills)
                    common_skills = [skill for skill, count in skill_counts.most_common(10) 
                                   if count >= len(jobs) * 0.3]

                    sector, level = cluster_key.split('_', 1)
                    
                    result.append({
                        "cluster_id": cluster_key,
                        "sector": sector,
                        "job_level": level,
                        "size": len(jobs),
                        "common_skills": common_skills,
                        "skill_diversity": len(skill_counts),
                        "cohesion_score": round(len(common_skills) / len(skill_counts), 2) if skill_counts else 0
                    })

            result.sort(key=lambda x: x['size'], reverse=True)
            return result[:30]
        except Exception as e:
            logger.error(f"Erreur clusters emplois similaires: {e}")
            return []

    # ==================== ANALYSES POUR ENTREPRISES ====================

    def get_company_insights(self, db: Session, company_name: str, period: str = "365d") -> Dict[str, Any]:
        """Analyse approfondie d'une entreprise spécifique."""
        try:
            start_date, end_date = self._get_period_bounds(period)

            total_offers = db.query(func.count(OffreEmploiBrute.id)).filter(
                OffreEmploiBrute.company_name.ilike(f"%{company_name}%"),
                OffreEmploiBrute.posted_date.between(start_date, end_date)
            ).scalar() or 0

            if total_offers == 0:
                return {"error": "Aucune offre trouvée pour cette entreprise"}

            sectors = db.query(
                OffreEmploiEnrichie.extracted_sector,
                func.count(OffreEmploiEnrichie.id).label('count')
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.company_name.ilike(f"%{company_name}%"),
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.extracted_sector.isnot(None)
            ).group_by(OffreEmploiEnrichie.extracted_sector).all()

            skills = db.query(
                func.unnest(OffreEmploiEnrichie.extracted_skills).label('skill'),
                func.count(OffreEmploiEnrichie.id).label('count')
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.company_name.ilike(f"%{company_name}%"),
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.extracted_skills.isnot(None)
            ).group_by('skill').order_by(desc('count')).limit(15).all()

            contracts = db.query(
                OffreEmploiEnrichie.extracted_contract_type,
                func.count(OffreEmploiEnrichie.id).label('count')
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.company_name.ilike(f"%{company_name}%"),
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.extracted_contract_type.isnot(None)
            ).group_by(OffreEmploiEnrichie.extracted_contract_type).all()

            levels = db.query(
                OffreEmploiEnrichie.job_level,
                func.count(OffreEmploiEnrichie.id).label('count')
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.company_name.ilike(f"%{company_name}%"),
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.job_level.isnot(None)
            ).group_by(OffreEmploiEnrichie.job_level).all()

            monthly = db.query(
                func.date_trunc('month', OffreEmploiBrute.posted_date).label('month'),
                func.count(OffreEmploiBrute.id).label('count')
            ).filter(
                OffreEmploiBrute.company_name.ilike(f"%{company_name}%"),
                OffreEmploiBrute.posted_date.between(start_date, end_date)
            ).group_by(func.date_trunc('month', OffreEmploiBrute.posted_date)).order_by(func.date_trunc('month', OffreEmploiBrute.posted_date)).all()

            return {
                "company_name": company_name,
                "period": period,
                "total_offers": total_offers,
                "sectors": [{"sector": s[0], "count": s[1]} for s in sectors],
                "top_skills": [{"skill": s[0], "count": s[1]} for s in skills],
                "contract_types": [{"type": c[0], "count": c[1]} for c in contracts],
                "experience_levels": [{"level": l[0], "count": l[1]} for l in levels],
                "hiring_trend": [{"month": m[0].strftime('%Y-%m'), "count": m[1]} for m in monthly if m[0]],
                "avg_offers_per_month": round(total_offers / 12, 2) if period == "365d" else None
            }
        except Exception as e:
            logger.error(f"Erreur insights entreprise: {e}")
            return {}

    # ==================== EXPORTS ET RAPPORTS ====================

    def generate_executive_summary(self, db: Session, period: str = "90d") -> Dict[str, Any]:
        """Génère un résumé exécutif complet du marché."""
        try:
            start_date, end_date = self._get_period_bounds(period)
            stats = self.get_enhanced_dashboard(db, start_date, end_date)
            evolution = self.get_market_evolution_rates(db, start_date, end_date)
            emerging = self.get_emerging_skills(db, period, 50.0)
            momentum = self.get_sector_momentum(db, period)

            top_growing_sector = momentum[0] if momentum else None
            top_emerging_skill = emerging[0] if emerging else None

            return {
                "period": period,
                "report_date": datetime.now().isoformat(),
                "executive_summary": {
                    "total_offers": stats.total_offers,
                    "market_health": evolution.get('market_health', 'unknown'),
                    "offers_growth_rate": evolution.get('offers_growth', {}).get('rate', 0),
                    "key_insight": self._generate_key_insight(evolution, momentum, emerging)
                },
                "market_overview": {
                    "total_companies": stats.total_companies,
                    "total_locations": stats.total_locations,
                    "sector_diversity": evolution.get('sectors_diversity', {}),
                    "skill_diversity": evolution.get('skills_diversity', {})
                },
                "top_opportunities": {
                    "hottest_sector": {
                        "name": top_growing_sector['sector'] if top_growing_sector else None,
                        "momentum": top_growing_sector['momentum'] if top_growing_sector else None
                    },
                    "emerging_skill": {
                        "name": top_emerging_skill['skill'] if top_emerging_skill else None,
                        "growth_rate": top_emerging_skill['growth_rate'] if top_emerging_skill else None
                    },
                    "top_hiring_companies": [c.dict() for c in self.get_top_hiring_companies(db, start_date, end_date, 5)]
                },
                "trends": {
                    "seasonal": self.get_seasonal_trends(db, 2),
                    "contract_types": stats.contract_type_distribution[:5],
                    "experience_levels": stats.experience_level_distribution
                },
                "recommendations": self._generate_recommendations(evolution, momentum, emerging)
            }
        except Exception as e:
            logger.error(f"Erreur résumé exécutif: {e}")
            return {}

    def _generate_key_insight(self, evolution: Dict, momentum: List, emerging: List) -> str:
        """Génère un insight clé automatique."""
        try:
            market_health = evolution.get('market_health', 'stable')
            offers_growth = evolution.get('offers_growth', {}).get('rate', 0)

            if market_health in ['excellent', 'good'] and offers_growth > 10:
                return f"Le marché est en excellente santé avec une croissance de {offers_growth}% des offres d'emploi."
            elif market_health == 'declining':
                return f"Le marché montre des signes de ralentissement avec une évolution de {offers_growth}%."
            else:
                return f"Le marché reste stable avec une évolution de {offers_growth}% des opportunités."
        except:
            return "Analyse du marché en cours."

    def _generate_recommendations(self, evolution: Dict, momentum: List, emerging: List) -> List[str]:
        """Génère des recommandations automatiques."""
        recommendations = []

        offers_growth = evolution.get('offers_growth', {}).get('rate', 0)
        if offers_growth > 15:
            recommendations.append("Période favorable pour la recherche d'emploi avec une forte croissance des opportunités.")
        elif offers_growth < -10:
            recommendations.append("Marché en contraction : privilégier les secteurs en croissance et la diversification des compétences.")

        if momentum:
            top_sector = momentum[0]
            if top_sector['momentum'] > 20:
                recommendations.append(f"Le secteur {top_sector['sector']} affiche une forte accélération : opportunités prometteuses.")

        if emerging:
            top_skills = [s['skill'] for s in emerging[:3]]
            recommendations.append(f"Compétences émergentes à développer : {', '.join(top_skills)}.")

        sector_diversity = evolution.get('sectors_diversity', {})
        if sector_diversity.get('trend') == 'diversifying':
            recommendations.append("Le marché se diversifie : explorer de nouveaux secteurs d'activité.")

        return recommendations if recommendations else ["Continuer le monitoring du marché."]

    # ==================== ANALYSES POUR CANDIDATS ====================

    def get_career_path_analysis(self, db: Session, current_skills: List[str], target_sector: Optional[str] = None) -> Dict[str, Any]:
        """Analyse de parcours de carrière basée sur les compétences actuelles."""
        try:
            matching_jobs = db.query(
                OffreEmploiEnrichie.extracted_sector,
                OffreEmploiEnrichie.job_level,
                OffreEmploiEnrichie.extracted_skills
            ).filter(
                OffreEmploiEnrichie.extracted_skills.overlap(current_skills)
            ).limit(500).all()

            if not matching_jobs:
                return {"error": "Aucune correspondance trouvée"}

            level_distribution = Counter()
            sector_distribution = Counter()
            complementary_skills = Counter()

            for job in matching_jobs:
                if job.job_level:
                    level_distribution[job.job_level] += 1
                if job.extracted_sector:
                    sector_distribution[job.extracted_sector] += 1
                if job.extracted_skills:
                    for skill in job.extracted_skills:
                        if skill not in current_skills:
                            complementary_skills[skill] += 1

            skill_gaps = complementary_skills.most_common(15)

            level_order = ['Junior', 'Confirmé', 'Senior', 'Expert', 'Lead', 'Manager', 'Director']
            current_level_idx = -1
            for idx, level in enumerate(level_order):
                if level in [l for l, _ in level_distribution.most_common(1)]:
                    current_level_idx = idx
                    break

            next_levels = []
            if current_level_idx >= 0 and current_level_idx < len(level_order) - 1:
                next_levels = level_order[current_level_idx + 1:current_level_idx + 3]

            return {
                "current_profile": {
                    "skills": current_skills,
                    "matching_jobs_count": len(matching_jobs),
                    "likely_level": level_distribution.most_common(1)[0][0] if level_distribution else "Unknown",
                    "primary_sectors": [s for s, _ in sector_distribution.most_common(3)]
                },
                "skill_gaps": [
                    {"skill": skill, "demand_frequency": count, "priority": "high" if count > 20 else "medium" if count > 10 else "low"}
                    for skill, count in skill_gaps
                ],
                "career_progression": {
                    "next_levels": next_levels,
                    "recommended_skills_by_level": self._get_skills_by_level(db, next_levels, current_skills)
                },
                "sector_opportunities": [
                    {"sector": sector, "job_count": count}
                    for sector, count in sector_distribution.most_common(5)
                ],
                "recommendations": self._generate_career_recommendations(skill_gaps, sector_distribution)
            }
        except Exception as e:
            logger.error(f"Erreur analyse parcours carrière: {e}")
            return {}

    def _get_skills_by_level(self, db: Session, levels: List[str], exclude_skills: List[str]) -> Dict[str, List[str]]:
        """Récupère les compétences typiques par niveau."""
        result = {}
        for level in levels:
            skills = db.query(
                func.unnest(OffreEmploiEnrichie.extracted_skills).label('skill'),
                func.count(OffreEmploiEnrichie.id).label('count')
            ).filter(
                OffreEmploiEnrichie.job_level == level,
                OffreEmploiEnrichie.extracted_skills.isnot(None)
            ).group_by('skill').order_by(desc('count')).limit(10).all()

            result[level] = [s.skill for s in skills if s.skill not in exclude_skills]

        return result

    def _generate_career_recommendations(self, skill_gaps: List[Tuple], sector_distribution: Counter) -> List[str]:
        """Génère des recommandations de carrière."""
        recommendations = []
        if skill_gaps:
            top_gap = skill_gaps[0][0]
            recommendations.append(f"Priorité : développer la compétence '{top_gap}' très demandée sur le marché.")
        if sector_distribution:
            top_sector = sector_distribution.most_common(1)[0][0]
            recommendations.append(f"Le secteur '{top_sector}' offre le plus d'opportunités pour votre profil.")
        if len(skill_gaps) >= 3:
            recommendations.append(f"Focus sur 2-3 compétences clés parmi : {', '.join([s[0] for s in skill_gaps[:3]])}.")
        return recommendations

    def get_skill_value_analysis(self, db: Session, skills: List[str], period: str = "180d") -> Dict[str, Any]:
        """Analyse la valeur marchande des compétences."""
        try:
            start_date, end_date = self._get_period_bounds(period)

            skill_analysis = []
            for skill in skills:
                demand = db.query(func.count(OffreEmploiEnrichie.id)).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    OffreEmploiBrute.posted_date.between(start_date, end_date),
                    OffreEmploiEnrichie.extracted_skills.any(skill)
                ).scalar() or 0

                sectors = db.query(
                    OffreEmploiEnrichie.extracted_sector
                ).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    OffreEmploiBrute.posted_date.between(start_date, end_date),
                    OffreEmploiEnrichie.extracted_skills.any(skill),
                    OffreEmploiEnrichie.extracted_sector.isnot(None)
                ).distinct().all()

                avg_salary = db.query(
                    func.avg((OffreEmploiEnrichie.extracted_salary_min + OffreEmploiEnrichie.extracted_salary_max) / 2)
                ).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    OffreEmploiBrute.posted_date.between(start_date, end_date),
                    OffreEmploiEnrichie.extracted_skills.any(skill),
                    OffreEmploiEnrichie.extracted_salary_min.isnot(None),
                    OffreEmploiEnrichie.extracted_salary_max.isnot(None)
                ).scalar()

                value_score = min(100, (demand / 10) * 10)

                saturation = "high" if demand < 10 else "medium" if demand < 50 else "common"

                skill_analysis.append({
                    "skill": skill,
                    "market_demand": demand,
                    "value_score": round(value_score, 2),
                    "sector_diversity": len(sectors),
                    "sectors": [s[0] for s in sectors[:5]],
                    "avg_salary": float(avg_salary) if avg_salary else None,
                    "rarity": saturation
                })

            skill_analysis.sort(key=lambda x: x['value_score'], reverse=True)

            return {
                "skills_analysis": skill_analysis,
                "portfolio_value": sum(s['value_score'] for s in skill_analysis) / len(skill_analysis) if skill_analysis else 0,
                "strongest_skill": skill_analysis[0]['skill'] if skill_analysis else None,
                "diversification_score": len(set([s for sa in skill_analysis for s in sa['sectors']])) * 10
            }
        except Exception as e:
            logger.error(f"Erreur analyse valeur compétences: {e}")
            return {}

    # ==================== BENCHMARK ET COMPARAISONS ====================

    def get_regional_benchmark(self, db: Session, period: str = "180d") -> Dict[str, Any]:
        """Benchmark inter-régional du marché de l'emploi."""
        try:
            start_date, end_date = self._get_period_bounds(period)

            regions = {}
            for city_key, city_data in self.senegal_regions.items():
                region_name = city_data['region']
                if region_name in regions:
                    continue

                offers = db.query(func.count(OffreEmploiBrute.id)).filter(
                    func.lower(OffreEmploiBrute.location).like(f"%{city_key}%"),
                    OffreEmploiBrute.posted_date.between(start_date, end_date)
                ).scalar() or 0

                companies = db.query(func.count(distinct(OffreEmploiBrute.company_name))).filter(
                    func.lower(OffreEmploiBrute.location).like(f"%{city_key}%"),
                    OffreEmploiBrute.posted_date.between(start_date, end_date),
                    OffreEmploiBrute.company_name.isnot(None)
                ).scalar() or 0

                top_sector = db.query(
                    OffreEmploiEnrichie.extracted_sector
                ).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    func.lower(OffreEmploiBrute.location).like(f"%{city_key}%"),
                    OffreEmploiBrute.posted_date.between(start_date, end_date),
                    OffreEmploiEnrichie.extracted_sector.isnot(None)
                ).group_by(OffreEmploiEnrichie.extracted_sector).order_by(func.count(OffreEmploiEnrichie.id).desc()).first()

                if offers > 0:
                    regions[region_name] = {
                        "total_offers": offers,
                        "active_companies": companies,
                        "offers_per_company": round(offers / companies, 2) if companies > 0 else 0,
                        "dominant_sector": top_sector[0] if top_sector else None,
                        "main_cities": [city_key]
                    }

            total_offers = sum(r['total_offers'] for r in regions.values())
            for region_data in regions.values():
                region_data['market_share'] = round((region_data['total_offers'] / total_offers * 100), 2) if total_offers > 0 else 0

            ranked = sorted(regions.items(), key=lambda x: x[1]['total_offers'], reverse=True)

            return {
                "regions": dict(ranked),
                "leading_region": ranked[0][0] if ranked else None,
                "most_diversified": max(regions.items(), key=lambda x: x[1]['active_companies'])[0] if regions else None,
                "concentration_index": round(regions[ranked[0][0]]['market_share'], 2) if ranked else 0
            }
        except Exception as e:
            logger.error(f"Erreur benchmark régional: {e}")
            return {}

    def get_time_series_comparison(self, db: Session, metrics: List[str] = ['offers', 'companies', 'sectors'], 
                                   periods: List[str] = ['30d', '90d', '180d', '365d']) -> Dict[str, Any]:
        """Compare l'évolution de différentes métriques sur plusieurs périodes."""
        try:
            comparison = {metric: [] for metric in metrics}

            for period in periods:
                start_date, end_date = self._get_period_bounds(period)

                if 'offers' in metrics:
                    offers_count = db.query(func.count(OffreEmploiBrute.id)).filter(
                        OffreEmploiBrute.posted_date.between(start_date, end_date)
                    ).scalar() or 0
                    comparison['offers'].append({"period": period, "value": offers_count})

                if 'companies' in metrics:
                    companies_count = db.query(func.count(distinct(OffreEmploiBrute.company_name))).filter(
                        OffreEmploiBrute.posted_date.between(start_date, end_date),
                        OffreEmploiBrute.company_name.isnot(None)
                    ).scalar() or 0
                    comparison['companies'].append({"period": period, "value": companies_count})

                if 'sectors' in metrics:
                    sectors_count = db.query(func.count(distinct(OffreEmploiEnrichie.extracted_sector))).join(
                        OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                    ).filter(
                        OffreEmploiBrute.posted_date.between(start_date, end_date),
                        OffreEmploiEnrichie.extracted_sector.isnot(None)
                    ).scalar() or 0
                    comparison['sectors'].append({"period": period, "value": sectors_count})

                if 'skills' in metrics:
                    skills_count = self._count_unique_skills(db, start_date, end_date)
                    comparison['skills'].append({"period": period, "value": skills_count})

            return {
                "metrics": comparison,
                "periods_analyzed": periods,
                "trends": self._identify_trends(comparison)
            }
        except Exception as e:
            logger.error(f"Erreur comparaison séries temporelles: {e}")
            return {}

    def _identify_trends(self, comparison: Dict) -> Dict[str, str]:
        """Identifie les tendances dans les séries temporelles."""
        trends = {}
        for metric, data in comparison.items():
            if len(data) >= 2:
                values = [d['value'] for d in data]
                if all(values[i] <= values[i+1] for i in range(len(values)-1)):
                    trends[metric] = "increasing"
                elif all(values[i] >= values[i+1] for i in range(len(values)-1)):
                    trends[metric] = "decreasing"
                else:
                    trends[metric] = "fluctuating"
        return trends

    # ==================== ANALYSE GÉOGRAPHIQUE ====================

    def get_geographic_analysis(self, db: Session, start_date: datetime, end_date: datetime) -> List[GeographicStats]:
        """Analyse géographique détaillée."""
        try:
            locations = db.query(
                func.lower(func.trim(OffreEmploiBrute.location)).label('location'),
                func.count(OffreEmploiBrute.id).label('count')
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiBrute.location.isnot(None),
                OffreEmploiBrute.location != ''
            ).group_by(
                func.lower(func.trim(OffreEmploiBrute.location))
            ).order_by(desc('count')).limit(20).all()

            total_offers = sum(loc.count for loc in locations)

            result = []
            for location in locations:
                top_sectors = db.query(
                    OffreEmploiEnrichie.extracted_sector
                ).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    func.lower(func.trim(OffreEmploiBrute.location)) == location.location,
                    OffreEmploiBrute.posted_date.between(start_date, end_date),
                    OffreEmploiEnrichie.extracted_sector.isnot(None)
                ).group_by(OffreEmploiEnrichie.extracted_sector).order_by(func.count(OffreEmploiEnrichie.id).desc()).limit(5).all()

                salary_stats = self._execute_salary_query(
                    db,
                    and_(
                        func.lower(func.trim(OffreEmploiBrute.location)) == location.location,
                        OffreEmploiBrute.posted_date.between(start_date, end_date)
                    )
                )

                coords = self._find_coordinates(location.location)

                result.append(GeographicStats(
                    region=location.location.title(),
                    count=location.count,
                    percentage=round((location.count / total_offers * 100), 2) if total_offers > 0 else 0,
                    avg_salary_min=salary_stats.get('avg_min'),
                    avg_salary_max=salary_stats.get('avg_max'),
                    top_sectors=[s[0] for s in top_sectors if s[0]],
                    coordinates=coords
                ))

            return result
        except Exception as e:
            logger.error(f"Erreur analyse géographique: {e}", exc_info=True)
            return []

    def _find_coordinates(self, location: str) -> Optional[Dict[str, float]]:
        """Trouve les coordonnées GPS d'une localisation."""
        location_clean = location.lower().strip()
        
        if location_clean in self.senegal_regions:
            coords = self.senegal_regions[location_clean]
            return {"lat": coords["lat"], "lng": coords["lng"]}
        
        for city, coords in self.senegal_regions.items():
            if city in location_clean or location_clean in city:
                return {"lat": coords["lat"], "lng": coords["lng"]}
        
        return None

    # ==================== HEATMAP COMPÉTENCES x SECTEURS ====================

    def get_skills_sector_heatmap(self, db: Session, start_date: datetime, end_date: datetime) -> List[HeatmapData]:
        """Crée une heatmap des compétences par secteur."""
        try:
            top_sectors = db.query(
                OffreEmploiEnrichie.extracted_sector
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.extracted_sector.isnot(None)
            ).group_by(OffreEmploiEnrichie.extracted_sector).order_by(func.count(OffreEmploiEnrichie.id).desc()).limit(15).all()

            result = []
            for (sector,) in top_sectors:
                skills = db.query(
                    func.unnest(OffreEmploiEnrichie.extracted_skills).label('skill'),
                    func.count(OffreEmploiEnrichie.id).label('count')
                ).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    OffreEmploiBrute.posted_date.between(start_date, end_date),
                    OffreEmploiEnrichie.extracted_sector == sector,
                    OffreEmploiEnrichie.extracted_skills.isnot(None)
                ).group_by('skill').order_by(desc('count')).limit(10).all()

                result.append(HeatmapData(
                    sector=sector,
                    skills={s.skill: s.count for s in skills}
                ))

            return result
        except Exception as e:
            logger.error(f"Erreur heatmap: {e}", exc_info=True)
            return []

    # ==================== SALAIRES PAR EXPÉRIENCE ====================

    def get_salary_by_experience(self, db: Session, start_date: datetime, end_date: datetime) -> List[SalaryByExperience]:
        """Analyse des salaires par niveau d'expérience."""
        try:
            levels = db.query(
                OffreEmploiEnrichie.job_level.label('level'),
                func.avg(OffreEmploiEnrichie.extracted_salary_min).label('avg_min'),
                func.avg(OffreEmploiEnrichie.extracted_salary_max).label('avg_max'),
                func.count(OffreEmploiEnrichie.id).label('count')
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.job_level.isnot(None)
            ).group_by(OffreEmploiEnrichie.job_level).all()

            return [
                SalaryByExperience(
                    level=l.level or "Non spécifié",
                    avg_min=float(l.avg_min) if l.avg_min else None,
                    avg_max=float(l.avg_max) if l.avg_max else None,
                    count=l.count
                )
                for l in levels
            ]
        except Exception as e:
            logger.error(f"Erreur salaires par expérience: {e}")
            return []

    # ==================== TOP ENTREPRISES ====================

    def get_top_hiring_companies(self, db: Session, start_date: datetime, end_date: datetime, limit: int = 20) -> List[CompanyHiringStats]:
        """Top des entreprises qui recrutent le plus."""
        try:
            companies = db.query(
                OffreEmploiBrute.company_name.label('company'),
                func.count(OffreEmploiBrute.id).label('offers')
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiBrute.company_name.isnot(None),
                OffreEmploiBrute.company_name != ''
            ).group_by(OffreEmploiBrute.company_name).order_by(desc('offers')).limit(limit).all()

            return [
                CompanyHiringStats(
                    company=c.company,
                    offers=c.offers
                )
                for c in companies
            ]
        except Exception as e:
            logger.error(f"Erreur top entreprises: {e}")
            return []

    # ==================== ÉVOLUTION DES TYPES DE CONTRAT (UNIQUE) ====================

    def get_contract_type_evolution(self, db: Session, start_date: datetime, end_date: datetime) -> List[ContractTypeEvolution]:
        """Évolution des types de contrat par jour."""
        try:
            contract_types = db.query(distinct(OffreEmploiEnrichie.extracted_contract_type)).filter(
                OffreEmploiEnrichie.extracted_contract_type.isnot(None)
            ).all()
            
            contract_types_list = [ct[0] for ct in contract_types if ct[0]]

            daily_data = db.query(
                func.date(OffreEmploiBrute.posted_date).label('date'),
                OffreEmploiEnrichie.extracted_contract_type.label('contract_type'),
                func.count(OffreEmploiEnrichie.id).label('count')
            ).join(OffreEmploiEnrichie, OffreEmploiBrute.id == OffreEmploiEnrichie.offre_id).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.extracted_contract_type.isnot(None)
            ).group_by(func.date(OffreEmploiBrute.posted_date), OffreEmploiEnrichie.extracted_contract_type).order_by(func.date(OffreEmploiBrute.posted_date)).all()

            days_data = defaultdict(dict)
            for row in daily_data:
                date_str = row.date.isoformat() if row.date else None
                if date_str:
                    days_data[date_str][row.contract_type] = row.count

            result = []
            for date, contracts in sorted(days_data.items()):
                contracts_complete = {ct: contracts.get(ct, 0) for ct in contract_types_list}
                result.append(ContractTypeEvolution(month=date, contracts=contracts_complete))
            return result
        except Exception as e:
            logger.error(f"Erreur évolution contrats quotidienne: {e}", exc_info=True)
            return []

    # ==================== MÉTHODES HÉRITÉES (compatibilité) ====================

    def get_jobs_summary(self, db: Session) -> dict:
        """Méthode de compatibilité avec l'ancien service."""
        try:
            start_date = datetime.now() - timedelta(days=30)
            end_date = datetime.now()
            
            dashboard = self.get_enhanced_dashboard(db, start_date, end_date)
            
            return {
                "total_jobs": dashboard.total_offers,
                "recent_jobs": dashboard.offers_this_month,
                "top_sectors": dashboard.top_sectors[:5],
                "last_updated": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Erreur jobs summary: {e}")
            raise

    def _get_top_skills_with_trend(self, db: Session, start_date: datetime, end_date: datetime, limit: int = 20) -> List[Dict[str, Any]]:
        """Top compétences avec tendance de demande."""
        try:
            skills = db.query(
                func.unnest(OffreEmploiEnrichie.extracted_skills).label('skill'),
                func.count(OffreEmploiEnrichie.id).label('count')
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.extracted_skills.isnot(None)
            ).group_by('skill').order_by(desc('count')).limit(limit).all()

            period_duration = max((end_date - start_date).days, 1)
            previous_start = start_date - timedelta(days=period_duration)

            result = []
            for skill in skills:
                previous_count = db.query(func.count(OffreEmploiEnrichie.id)).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    OffreEmploiBrute.posted_date.between(previous_start, start_date),
                    OffreEmploiEnrichie.extracted_skills.any(skill.skill)
                ).scalar() or 0

                growth = 0
                if previous_count > 0:
                    growth = round(((skill.count - previous_count) / previous_count) * 100, 2)
                elif skill.count > 0:
                    growth = 100

                result.append({
                    "skill": skill.skill,
                    "count": skill.count,
                    "trend": "rising" if growth > 10 else "falling" if growth < -10 else "stable",
                    "growth_rate": growth
                })

            return result
        except Exception as e:
            logger.error(f"Erreur top compétences: {e}")
            return []

    def _get_top_sectors_with_growth(self, db: Session, start_date: datetime, end_date: datetime, limit: int = 10) -> List[Dict[str, Any]]:
        """Retourne les top secteurs avec taux de croissance."""
        try:
            current_sectors = db.query(
                OffreEmploiEnrichie.extracted_sector.label("sector"),
                func.count(OffreEmploiEnrichie.id).label("count")
            ).join(
                OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
            ).filter(
                OffreEmploiBrute.posted_date.between(start_date, end_date),
                OffreEmploiEnrichie.extracted_sector.isnot(None)
            ).group_by(OffreEmploiEnrichie.extracted_sector).order_by(desc("count")).limit(limit).all()

            period_duration = max((end_date - start_date).days, 1)
            previous_start = start_date - timedelta(days=period_duration)

            result = []
            for sector in current_sectors:
                previous_count = db.query(func.count(OffreEmploiEnrichie.id)).join(
                    OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
                ).filter(
                    OffreEmploiBrute.posted_date.between(previous_start, start_date),
                    OffreEmploiEnrichie.extracted_sector == sector.sector
                ).scalar() or 0

                growth = 0
                if previous_count > 0:
                    growth = round(((sector.count - previous_count) / previous_count) * 100, 2)
                elif sector.count > 0:
                    growth = 100

                result.append({
                    "sector": sector.sector,
                    "current_count": sector.count,
                    "previous_count": previous_count,
                    "growth": growth
                })

            return result
        except Exception as e:
            logger.error(f"Erreur top sectors avec croissance: {e}")
            return []

    def _get_daily_trend(self, db: Session, days: int) -> List[Dict[str, Any]]:
        """Tendance quotidienne sur N jours."""
        try:
            start_date = datetime.now() - timedelta(days=days)
            
            trends = db.query(
                func.date(OffreEmploiBrute.posted_date).label('date'),
                func.count(OffreEmploiBrute.id).label('count')
            ).filter(OffreEmploiBrute.posted_date >= start_date).group_by(
                func.date(OffreEmploiBrute.posted_date)
            ).order_by(func.date(OffreEmploiBrute.posted_date)).all()

            return [
                {
                    "date": t.date.isoformat() if t.date else None,
                    "count": t.count
                }
                for t in trends if t.date
            ]
        except Exception as e:
            logger.error(f"Erreur tendance quotidienne: {e}")
            return []

    def get_data_quality_report(self, db: Session) -> Dict[str, Any]:
        """Rapport sur la qualité des données collectées."""
        try:
            total_offers = db.query(func.count(OffreEmploiBrute.id)).scalar() or 0
            
            fields_completeness = {
                "title": db.query(func.count(OffreEmploiBrute.id)).filter(OffreEmploiBrute.title.isnot(None)).scalar() or 0,
                "description": db.query(func.count(OffreEmploiBrute.id)).filter(OffreEmploiBrute.description.isnot(None)).scalar() or 0,
                "company_name": db.query(func.count(OffreEmploiBrute.id)).filter(OffreEmploiBrute.company_name.isnot(None)).scalar() or 0,
                "location": db.query(func.count(OffreEmploiBrute.id)).filter(OffreEmploiBrute.location.isnot(None)).scalar() or 0,
                "salary": db.query(func.count(OffreEmploiBrute.id)).filter(OffreEmploiBrute.salary.isnot(None)).scalar() or 0,
            }

            total_enriched = db.query(func.count(OffreEmploiEnrichie.id)).scalar() or 0
            enrichment_rate = round((total_enriched / total_offers * 100), 2) if total_offers > 0 else 0

            enriched_fields = {
                "skills": db.query(func.count(OffreEmploiEnrichie.id)).filter(OffreEmploiEnrichie.extracted_skills.isnot(None)).scalar() or 0,
                "sector": db.query(func.count(OffreEmploiEnrichie.id)).filter(OffreEmploiEnrichie.extracted_sector.isnot(None)).scalar() or 0,
                "contract_type": db.query(func.count(OffreEmploiEnrichie.id)).filter(OffreEmploiEnrichie.extracted_contract_type.isnot(None)).scalar() or 0,
                "job_level": db.query(func.count(OffreEmploiEnrichie.id)).filter(OffreEmploiEnrichie.job_level.isnot(None)).scalar() or 0,
            }

            return {
                "total_offers": total_offers,
                "total_enriched": total_enriched,
                "enrichment_rate": enrichment_rate,
                "fields_completeness": {
                    field: {
                        "count": count,
                        "rate": round((count / total_offers * 100), 2) if total_offers > 0 else 0
                    }
                    for field, count in fields_completeness.items()
                },
                "enriched_fields": {
                    field: {
                        "count": count,
                        "rate": round((count / total_enriched * 100), 2) if total_enriched > 0 else 0
                    }
                    for field, count in enriched_fields.items()
                },
                "generated_at": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Erreur rapport qualité: {e}")
            return {}