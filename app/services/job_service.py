"""
Service pour la gestion des offres d'emploi.
"""

from typing import List, Optional, Dict, Any, Tuple, Union, TYPE_CHECKING
from sqlalchemy.orm import Session, Query
from sqlalchemy import and_, or_, func, desc, text
import uuid
from uuid import UUID
import logging
from datetime import datetime, timedelta

from ..models.database_models import OffreEmploiBrute, OffreEmploiEnrichie, UserSavedJob
from ..models.api_models import JobSearchParams, PaginatedResponse, JobOfferResponse, JobCreate
from ..utils.job_title_extraction import extract_job_title
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
    
    def search_jobs(self, db: Session, params: JobSearchParams, user_category: Optional[str] = None) -> PaginatedResponse[JobOfferResponse]:
        """
        Recherche des offres d'emploi avec filtres.
        
        Args:
            db: Session de base de données
            params: Paramètres de recherche
            user_category: Catégorie de l'utilisateur (optionnel)
            
        Returns:
            Réponse paginée avec les offres d'emploi
        """
        try:
            # Construire la requête de base
            query = self._get_base_query(db)
            
            # --- FILTRAGE STRICT PAR CATÉGORIE ---
            if user_category == 'pupil':
                # Les élèves ne voient que les Concours, Bourses, Ecoles/Examens (PAS les stages -> réservés étudiants/pro)
                query = query.filter(
                    or_(
                        func.lower(OffreEmploiBrute.title).contains('concours'),
                        func.lower(OffreEmploiBrute.title).contains('bourse'),
                        func.lower(OffreEmploiBrute.title).contains('examen'),
                        func.lower(OffreEmploiBrute.title).contains('ecole'),
                        OffreEmploiEnrichie.job_type == 'scholarship_exam'
                    )
                )
            
            elif user_category == 'informal':
                # Les profils informels/sans diplôme voient :
                # - Offres explicitement "Sans diplôme"
                # - Apprentissages, Ateliers, Formations pratiques
                query = query.filter(
                    or_(
                        func.lower(OffreEmploiBrute.education_level).contains('sans diplôme'),
                        func.lower(OffreEmploiBrute.education_level).contains('aucun'),
                        func.lower(OffreEmploiBrute.title).contains('apprenti'),
                        func.lower(OffreEmploiBrute.title).contains('atelier'),
                        func.lower(OffreEmploiBrute.title).contains('formation'),
                        OffreEmploiEnrichie.job_type == 'workshop_training'
                    )
                )

            # Appliquer les filtres standards
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
            
            if hasattr(params, 'job_title') and params.job_title:
                query = query.filter(
                    func.lower(OffreEmploiEnrichie.extracted_job_title).contains(func.lower(params.job_title))
                )
            
            if hasattr(params, 'source_type') and params.source_type:
                if params.source_type == 'direct':
                    query = query.filter(OffreEmploiBrute.recruiter_id.isnot(None))
                elif params.source_type == 'indirect':
                    query = query.filter(OffreEmploiBrute.recruiter_id.is_(None))
                # Ancienne compatibilité
                elif params.source_type == 'recruiter':
                    query = query.filter(OffreEmploiBrute.recruiter_id.isnot(None))
                elif params.source_type == 'advertiser':
                    query = query.filter(OffreEmploiBrute.contributor_id.isnot(None))
                elif params.source_type == 'scraped':
                    query = query.filter(
                        and_(
                            OffreEmploiBrute.recruiter_id.is_(None),
                            OffreEmploiBrute.contributor_id.is_(None)
                        )
                    )
            
            if params.search:
                # Nettoyer et séparer les termes de recherche
                search_terms = params.search.strip().split()
                if search_terms:
                    # Créer une liste de conditions pour chaque terme
                    search_conditions = []
                    for term in search_terms:
                        term_pattern = f"%{term.lower()}%"
                        term_condition = or_(
                            func.lower(OffreEmploiBrute.title).like(term_pattern),
                            func.lower(OffreEmploiBrute.description).like(term_pattern),
                            func.lower(OffreEmploiBrute.company_name).like(term_pattern),
                            text("offres_emploi_enrichies.extracted_skills::text ILIKE :term").params(term=term_pattern)
                        )
                        search_conditions.append(term_condition)
                    
                    # Combiner avec OR : au moins un terme doit matcher
                    # (Pour une recherche plus stricte, utiliser and_(*search_conditions))
                    query = query.filter(or_(*search_conditions))
            
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
            "education_level": brute.education_level,
            "nb_positions": brute.nb_positions,
            "expiration_date": brute.expiration_date,
            "remote_type": brute.remote_type,
            "is_urgent": brute.is_urgent,
            "languages": brute.languages or [],
            "benefits": brute.benefits or [],
            "recruiter_id": brute.recruiter_id,
            "contributor_id": brute.contributor_id
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
                "extracted_job_title": enrichie.extracted_job_title,
                "sentiment_score": enrichie.sentiment_score,
                "key_phrases": enrichie.key_phrases or [],  # Gérer NULL
                "job_level": enrichie.job_level,
                "job_type": enrichie.job_type,
                "confidence_score": enrichie.confidence_score,
                "processed_at": enrichie.processed_at,
        })
        
        # Identifier le type d'offre basé sur les mots clés si non présent
        if not job_data.get("job_type"):
            title_lower = brute.title.lower()
            if any(k in title_lower for k in ['bourse', 'concours', 'examen', 'scolaire']):
                job_data["job_type"] = "scholarship_exam"
            elif any(k in title_lower for k in ['atelier', 'apprentissage', 'technique', 'artisan']):
                job_data["job_type"] = "workshop_training"
            else:
                job_data["job_type"] = "employment"
        
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


    def save_job(self, db: Session, user_id: UUID, job_id: Any):
        """
        Sauvegarde une offre pour un utilisateur.
        Utilise directement l'ID de l'offre brute (plus stable).
        """
        try:
            # Conversion robuste de l'ID en UUID
            if isinstance(job_id, str):
                try:
                    job_uuid = UUID(job_id)
                except ValueError:
                    raise ValueError(f"Format d'ID invalide : {job_id}")
            else:
                job_uuid = job_id

            # 1. Vérifier que l'offre brute existe
            brute = db.query(OffreEmploiBrute).filter(OffreEmploiBrute.id == job_uuid).first()
            if not brute:
                raise ValueError(f"Offre d'emploi {job_id} introuvable dans la base de données")

            # 2. Vérifier si déjà sauvegardé
            existing = db.query(UserSavedJob).filter(
                UserSavedJob.user_id == user_id,
                UserSavedJob.job_id == brute.id
            ).first()
            
            if existing:
                return existing

            # 3. Sauvegarder
            saved = UserSavedJob(user_id=user_id, job_id=brute.id)
            db.add(saved)
            db.commit()
            db.refresh(saved)
            return saved

        except Exception as e:
            if isinstance(e, ValueError):
                raise
            logger.error(f"Erreur lors de la sauvegarde de l'offre: {e}", exc_info=True)
            raise RuntimeError(f"Erreur interne lors de la sauvegarde : {str(e)}")

    def remove_saved_job(self, db: Session, user_id: UUID, job_id: UUID) -> bool:
        """
        Supprime une offre des favoris d'un utilisateur.
        job_id est l'ID de l'offre brute.
        """
        saved = db.query(UserSavedJob).filter(
            UserSavedJob.user_id == user_id,
            UserSavedJob.job_id == job_id
        ).first()

        if not saved:
            return False

        db.delete(saved)
        db.commit()
        return True

    def create_job(self, db: Session, job_data: Union[Dict[str, Any], JobCreate], recruiter_id: UUID, company_id: UUID) -> JobOfferResponse:
        """
        Crée une nouvelle offre d'emploi postée par un recruteur.
        """
        try:
            # Normaliser en dictionnaire si c'est un objet Pydantic
            if hasattr(job_data, "model_dump"):
                data = job_data.model_dump()
            else:
                data = job_data

            # 1. Créer l'offre brute
            brute = OffreEmploiBrute(
                spider_source="platform",
                original_id=f"PLAT-{uuid.uuid4().hex[:8]}",
                title=data.get("title"),
                company_name=data.get("company_name"),
                location=data.get("location"),
                contract_type=data.get("contract_type"),
                description=data.get("description"),
                url=data.get("url", ""),
                source="Internal Platform",
                posted_date=datetime.utcnow(),
                recruiter_id=recruiter_id,
                company_id=company_id,
                
                # Nouveaux champs
                education_level=data.get("education_level"),
                nb_positions=data.get("nb_positions", 1),
                expiration_date=data.get("expiration_date"),  # Déjà datetime si Pydantic
                remote_type=data.get("remote_type"),
                is_urgent=data.get("is_urgent", False),
                languages=data.get("languages", []),
                benefits=data.get("benefits", [])
            )
            db.add(brute)
            db.flush() # Récupérer l'ID pour l'enrichissement

            # 2. Créer l'enrichissement par défaut (pour que les jointures fonctionnent)
            enrichie = OffreEmploiEnrichie(
                offre_id=brute.id,
                extracted_contract_type=brute.contract_type,
                extracted_sector=data.get("sector"),
                extracted_salary_min=data.get("min_salary"),
                extracted_salary_max=data.get("max_salary"),
                extracted_skills=data.get("skills", []),
                extracted_experience_years=data.get("experience_years"),
                extracted_job_title=extract_job_title(brute.title),
                confidence_score=1.0, # Donnée manuelle = 100% confiance
                processed_at=datetime.utcnow()
            )
            db.add(enrichie)
            db.commit()
            db.refresh(brute)
            
            return self._create_job_response(brute, enrichie)
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating job: {e}")
            raise

    def get_recruiter_jobs(self, db: Session, recruiter_id: UUID) -> List[JobOfferResponse]:
        """
        Récupère toutes les offres postées par un recruteur spécifique.
        """
        try:
            results = self._get_base_query(db).filter(
                OffreEmploiBrute.recruiter_id == recruiter_id
            ).order_by(desc(OffreEmploiBrute.posted_date)).all()
            
            return [
                self._create_job_response(brute, enrichie) 
                for brute, enrichie in results
            ]
        except Exception as e:
            logger.error(f"Error fetching recruiter jobs: {e}")
            raise

    def delete_job(self, db: Session, job_id: UUID, recruiter_id: UUID) -> bool:
        """
        Supprime physiquement une offre d'emploi si elle appartient au recruteur.
        """
        try:
            job = db.query(OffreEmploiBrute).filter(
                OffreEmploiBrute.id == job_id,
                OffreEmploiBrute.recruiter_id == recruiter_id
            ).first()
            
            if not job:
                return False
                
            db.delete(job)
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"Error deleting job {job_id}: {e}")
            raise

    def enrich_job_title(self, db: Session, job_id: UUID) -> bool:
        """
        Enrichit le titre du poste pour une offre existante.
        """
        try:
            # Récupérer l'offre brute
            brute = db.query(OffreEmploiBrute).filter(OffreEmploiBrute.id == job_id).first()
            if not brute:
                return False
            
            # Récupérer ou créer l'enrichissement
            enrichie = db.query(OffreEmploiEnrichie).filter(OffreEmploiEnrichie.offre_id == job_id).first()
            if not enrichie:
                # Créer un enrichissement basique
                enrichie = OffreEmploiEnrichie(
                    offre_id=job_id,
                    extracted_job_title=extract_job_title(brute.title),
                    confidence_score=0.8,  # Score par défaut pour extraction automatique
                    processed_at=datetime.utcnow()
                )
                db.add(enrichie)
            else:
                # Mettre à jour le titre extrait
                enrichie.extracted_job_title = extract_job_title(brute.title)
                enrichie.processed_at = datetime.utcnow()
            
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"Error enriching job title for {job_id}: {e}")
            return False

    def enrich_all_jobs_titles(self, db: Session) -> int:
        """
        Enrichit les titres de poste pour toutes les offres sans titre extrait.
        Retourne le nombre d'offres enrichies.
        """
        try:
            # Récupérer les offres sans titre extrait
            jobs_to_enrich = db.query(OffreEmploiBrute).join(
                OffreEmploiEnrichie, 
                OffreEmploiBrute.id == OffreEmploiEnrichie.offre_id,
                isouter=True
            ).filter(
                or_(
                    OffreEmploiEnrichie.extracted_job_title.is_(None),
                    OffreEmploiEnrichie.id.is_(None)
                )
            ).all()
            
            enriched_count = 0
            for brute in jobs_to_enrich:
                success = self.enrich_job_title(db, brute.id)
                if success:
                    enriched_count += 1
            
            logger.info(f"Enriched {enriched_count} job titles")
            return enriched_count
        except Exception as e:
            db.rollback()
            logger.error(f"Error enriching all job titles: {e}")
            raise

