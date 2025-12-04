"""
Service pour la gestion des offres d'emploi.
"""

from typing import List, Optional, Dict, Any, Tuple, TYPE_CHECKING
from sqlalchemy.orm import Session, Query
from sqlalchemy import and_, or_, func, desc, text
from uuid import UUID
import logging
from datetime import datetime, timedelta

from ..models.database_models import OffreEmploiBrute, OffreEmploiEnrichie, UserSavedJob
from ..models.api_models import JobSearchParams, PaginatedResponse, JobOfferResponse
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    # Import pour le typage uniquement
    from sqlalchemy.engine.row import Row

class JobService:
    """Service pour gérer les opérations sur les offres d'emploi."""
    
    def __init__(self):
        """Initialise le service des offres d'emploi."""
        pass
    
    def _get_base_query(self, db: Session) -> Query:
        """
        Construit la requête de base avec jointure entre OffreEmploiBrute et OffreEmploiEnrichie.
        
        Returns:
            Query: Requête SQLAlchemy avec la jointure
        """
        return db.query(OffreEmploiBrute, OffreEmploiEnrichie).join(
            OffreEmploiEnrichie, OffreEmploiBrute.id == OffreEmploiEnrichie.offre_id, isouter=True
        )
    
    def search_jobs(self, db: Session, params: JobSearchParams) -> PaginatedResponse[JobOfferResponse]:
        """
        Recherche des offres d'emploi avec filtres.
        
        Args:
            db: Session de base de données
            params: Paramètres de recherche
            
        Returns:
            Réponse paginée avec les offres d'emploi
        """
        try:
            # Construire la requête de base
            query = self._get_base_query(db)
            
            # Appliquer les filtres
            if params.location:
                query = query.filter(
                    func.lower(OffreEmploiBrute.location).contains(func.lower(params.location))
                )
            
            if params.contract_type:
                query = query.filter(
                    or_(
                        func.lower(OffreEmploiBrute.contract_type).contains(func.lower(params.contract_type)),
                        func.lower(OffreEmploiEnrichie.extracted_contract_type).contains(func.lower(params.contract_type))
                    )
                )
            
            if params.sector:
                query = query.filter(
                    func.lower(OffreEmploiEnrichie.extracted_sector).contains(func.lower(params.sector))
                )
            
            if params.min_salary:
                query = query.filter(OffreEmploiEnrichie.extracted_salary_min >= params.min_salary)
            
            if params.max_salary:
                query = query.filter(OffreEmploiEnrichie.extracted_salary_max <= params.max_salary)
            
            if params.search:
                search_term = f"%{params.search.lower()}%"
                # Pour ARRAY, utiliser un cast en texte avec ILIKE
                query = query.filter(
                    or_(
                        func.lower(OffreEmploiBrute.title).like(search_term),
                        func.lower(OffreEmploiBrute.description).like(search_term),
                        func.lower(OffreEmploiBrute.company_name).like(search_term),
                        text("offres_emploi_enrichies.extracted_skills::text ILIKE :search").params(
                            search=f"%{params.search}%"
                        )
                    )
                )
            
            # Trier par date de publication (les plus récentes en premier)
            query = query.order_by(desc(OffreEmploiBrute.posted_date))
            
            # Compter le total
            total = query.count()
            
            # Pagination
            items = query.offset(params.skip).limit(params.limit).all()
            
            # Convertir en réponse API
            job_responses = [
                self._create_job_response(brute, enrichie) 
                for brute, enrichie in items
            ]
            
            # Calculer les métadonnées de pagination
            pages = (total + params.limit - 1) // params.limit
            current_page = params.skip // params.limit + 1
            
            return PaginatedResponse[JobOfferResponse](
                items=job_responses,
                total=total,
                page=current_page,
                size=params.limit,
                pages=pages,
                has_next=current_page < pages,
                has_prev=current_page > 1
            )
            
        except Exception as e:
            logger.error(f"Error searching jobs: {e}", exc_info=True)
            raise
    
    def get_job_by_id(self, db: Session, job_id: str) -> Optional[JobOfferResponse]:
        """
        Récupère une offre d'emploi par son ID.
        
        Args:
            db: Session de base de données
            job_id: ID de l'offre (UUID string)
            
        Returns:
            L'offre d'emploi ou None si non trouvée
        """
        try:
            # Validation UUID pour éviter l'erreur PostgreSQL
            try:
                uuid_obj = UUID(job_id)
            except ValueError:
                logger.warning(f"Invalid UUID format received: {job_id}")
                return None
            
            result = self._get_base_query(db).filter(
                OffreEmploiBrute.id == uuid_obj
            ).first()
            
            if not result:
                return None
            
            brute, enrichie = result
            return self._create_job_response(brute, enrichie)
            
        except Exception as e:
            logger.error(f"Error fetching job {job_id}: {e}", exc_info=True)
            raise
    
    def get_recent_jobs(self, db: Session, limit: int = 10) -> List[JobOfferResponse]:
        """
        Récupère les offres d'emploi les plus récentes.
        
        Args:
            db: Session de base de données
            limit: Nombre maximum d'offres
            
        Returns:
            Liste des offres récentes
        """
        try:
            results = self._get_base_query(db).order_by(
                desc(OffreEmploiBrute.posted_date)
            ).limit(limit).all()
            
            return [
                self._create_job_response(brute, enrichie) 
                for brute, enrichie in results
            ]
            
        except Exception as e:
            logger.error(f"Error fetching recent jobs: {e}", exc_info=True)
            raise
    
    def get_jobs_by_sector(self, db: Session, sector: str, limit: int = 20) -> List[JobOfferResponse]:
        """
        Récupère les offres d'emploi par secteur.
        
        Args:
            db: Session de base de données
            sector: Secteur d'activité
            limit: Nombre maximum d'offres
            
        Returns:
            Liste des offres du secteur
        """
        try:
            results = self._get_base_query(db).filter(
                func.lower(OffreEmploiEnrichie.extracted_sector).contains(func.lower(sector))
            ).limit(limit).all()
            
            return [
                self._create_job_response(brute, enrichie) 
                for brute, enrichie in results
            ]
            
        except Exception as e:
            logger.error(f"Error fetching jobs by sector {sector}: {e}", exc_info=True)
            raise
    
    def get_saved_jobs(self, db: Session, user_id: UUID) -> List[JobOfferResponse]:
        """
        Récupère les offres sauvegardées par un utilisateur.
        
        Args:
            db: Session de base de données
            user_id: UUID de l'utilisateur
            
        Returns:
            Liste des offres sauvegardées
        """
        try:
            # NOTE: Cette méthode nécessite une table user_saved_jobs dans votre DB
            # Exemple de requête avec jointure
            results = self._get_base_query(db).join(
                # Remplacer par votre vraie table de sauvegarde
                UserSavedJob, UserSavedJob.job_id == OffreEmploiBrute.id
            ).filter(
                 UserSavedJob.user_id == user_id
            ).order_by(desc(OffreEmploiBrute.posted_date)).all()
            
            return [
                self._create_job_response(brute, enrichie) 
                for brute, enrichie in results
            ]
            
        except Exception as e:
            logger.error(f"Error fetching saved jobs for user {user_id}: {e}", exc_info=True)
            raise
    
    def _create_job_response(self, brute: OffreEmploiBrute, enrichie: Optional[OffreEmploiEnrichie]) -> JobOfferResponse:
        """
        Crée une réponse JobOfferResponse à partir des modèles de base de données.
        
        Args:
            brute: Offre d'emploi brute
            enrichie: Offre d'emploi enrichie (optionnel)
            
        Returns:
            Réponse API
        """
        job_data = {
            "id": brute.id,  # Garder comme UUID, Pydantic gère la conversion
            "spider_source": brute.spider_source,
            "original_id": brute.original_id,
            "title": brute.title,
            "company_name": brute.company_name,
            "location": brute.location,
            "contract_type": brute.contract_type,
            "description": brute.description,
            "posted_date": brute.posted_date,
            "url": brute.url,
            "source": brute.source,
            "created_at": brute.created_at,
        }
        
        # Ajouter les données enrichies si disponibles
        if enrichie:
            job_data.update({
                "extracted_salary_min": enrichie.extracted_salary_min,
                "extracted_salary_max": enrichie.extracted_salary_max,
                "extracted_salary_currency": enrichie.extracted_salary_currency,
                "extracted_contract_type": enrichie.extracted_contract_type,
                "extracted_experience_years": enrichie.extracted_experience_years,
                "extracted_skills": enrichie.extracted_skills or [],  # Gérer NULL
                "extracted_sector": enrichie.extracted_sector,
                "extracted_job_category": enrichie.extracted_job_category,
                "sentiment_score": enrichie.sentiment_score,
                "key_phrases": enrichie.key_phrases or [],  # Gérer NULL
                "job_level": enrichie.job_level,
                "job_type": enrichie.job_type,
                "confidence_score": enrichie.confidence_score,
                "processed_at": enrichie.processed_at,
            })
        
        return JobOfferResponse.model_validate(job_data)
    
    def get_jobs_summary(self, db: Session) -> Dict[str, Any]:
        """
        Récupère un résumé des statistiques des offres d'emploi.
        
        Args:
            db: Session de base de données
            
        Returns:
            Dictionnaire avec les statistiques
        """
        try:
            # Utiliser func.current_timestamp() pour les comparaisons SQL
            current_time = func.current_timestamp()
            
            # Statistiques de base
            total_offers = db.query(OffreEmploiBrute).count()
            total_enriched = db.query(OffreEmploiEnrichie).count()
            
            # Offres du dernier mois
            last_month = current_time - timedelta(days=30)
            offers_last_month = db.query(OffreEmploiBrute).filter(
                OffreEmploiBrute.posted_date >= last_month
            ).count()
            
            # Offres d'aujourd'hui (comparer la date)
            offers_today = db.query(OffreEmploiBrute).filter(
                func.date(OffreEmploiBrute.created_at) == func.current_date()
            ).count()
            
            # Entreprises uniques
            unique_companies = db.query(OffreEmploiBrute.company_name).distinct().count()
            
            # Localisations uniques
            unique_locations = db.query(OffreEmploiBrute.location).distinct().count()
            
            # Salaires moyens
            salary_stats = db.query(
                func.avg(OffreEmploiEnrichie.extracted_salary_min).label('avg_min'),
                func.avg(OffreEmploiEnrichie.extracted_salary_max).label('avg_max')
            ).filter(
                OffreEmploiEnrichie.extracted_salary_min.isnot(None),
                OffreEmploiEnrichie.extracted_salary_max.isnot(None)
            ).first()
            
            return {
                "total_offers": total_offers,
                "total_enriched": total_enriched,
                "offers_last_month": offers_last_month,
                "offers_today": offers_today,
                "unique_companies": unique_companies,
                "unique_locations": unique_locations,
                "avg_salary_min": float(salary_stats.avg_min) if salary_stats and salary_stats.avg_min else None,
                "avg_salary_max": float(salary_stats.avg_max) if salary_stats and salary_stats.avg_max else None,
            }
            
        except Exception as e:
            logger.error(f"Error getting jobs summary: {e}", exc_info=True)
            raise


    def save_job(self, db: Session, user_id: UUID, job_id: UUID):
        # Trouver l'offre enrichie correspondant à l'offre brute
        enrichie = db.query(OffreEmploiEnrichie).filter(
            OffreEmploiEnrichie.offre_id == job_id
        ).first()
        if not enrichie:
            raise ValueError(f"Job {job_id} n'a pas été enrichi, impossible de sauvegarder")
        
        saved = UserSavedJob(user_id=user_id, job_id=enrichie.id)
        db.add(saved)
        db.commit()
        db.refresh(saved)
        return saved
