"""
Service pour la gestion des candidatures (ATS - Applicant Tracking System).
"""

from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from uuid import UUID
from datetime import datetime, timedelta
import logging

from ..models.database_models import Application, ApplicationStatusHistory, User, OffreEmploiEnrichie, Company
from ..models.api_models import ApplicationCreate, ApplicationUpdateStatus, ApplicationUpdateNotes

logger = logging.getLogger(__name__)


class ApplicationService:
    """Service pour gérer les candidatures."""
    
    VALID_STATUSES = [
        "applied", "shortlisted", "interview_scheduled", "interview_completed",
        "offer_made", "hired", "rejected", "withdrawn"
    ]
    
    def create_application(
        self,
        db: Session,
        user_id: UUID,
        application_data: ApplicationCreate
    ) -> Application:
        """
        Crée une nouvelle candidature.
        Supporte les offres non encore enrichies en créant une coquille (skeleton).
        """
        # 1. Chercher l'offre enrichie
        job = db.query(OffreEmploiEnrichie).filter(
            OffreEmploiEnrichie.id == application_data.job_id
        ).first()
        
        # 2. Si non enrichie, chercher l'offre brute
        if not job:
            brute = db.query(OffreEmploiBrute).filter(
                OffreEmploiBrute.id == application_data.job_id
            ).first()
            
            if not brute:
                raise ValueError(f"Offre d'emploi {application_data.job_id} non trouvée")
            
            # Créer une coquille (skeleton) pour permettre la candidature
            job = OffreEmploiEnrichie(
                offre_id=brute.id,
                processed_at=None,
                confidence_score=0.0
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            logger.info(f"Skeleton enrichment créé lors de la candidature pour l'offre {brute.id}")
        else:
            brute = job.offre_brute

        # 3. Récupérer l'entreprise (via brute ou enrichie si ajoutée plus tard)
        # Note: company_id semble manquer sur OffreEmploiBrute dans le modèle, 
        # mais ApplicationService l'attendait. On vérifie si l'entreprise peut être trouvée via le nom.
        # TODO: S'assurer que le modèle OffreEmploiBrute a bien company_id ou gérer via le nom
        company_id = None
        if hasattr(brute, 'company_id') and brute.company_id:
            company_id = brute.company_id
        else:
            # Fallback : chercher l'entreprise par nom
            from ..models.database_models import Company
            company = db.query(Company).filter(Company.name == brute.company_name).first()
            if company:
                company_id = company.id
            else:
                # Créer une entreprise placeholder si nécessaire ? 
                # Pour l'instant, on lève une erreur si pas d'ID
                raise ValueError(f"L'entreprise '{brute.company_name}' n'est pas référencée dans le système")
        
        # 4. Vérifier si candidature existe déjà
        existing = db.query(Application).filter(
            Application.user_id == user_id,
            Application.job_id == job.id
        ).first()
        
        if existing:
            raise ValueError("Vous avez déjà postulé à cette offre")
        
        # 5. Créer la candidature
        application = Application(
            user_id=user_id,
            job_id=job.id,
            company_id=company_id,
            cover_letter=application_data.cover_letter,
            status="applied"
        )
        
        db.add(application)
        db.commit()
        db.refresh(application)
        
        # 6. Créer l'entrée d'historique
        history = ApplicationStatusHistory(
            application_id=application.id,
            from_status=None,
            to_status="applied",
            comment="Candidature initiale"
        )
        db.add(history)
        db.commit()
        
        logger.info(f"Candidature créée: User {user_id} → Job {job.id}")
        return application
    
    def get_application_by_id(self, db: Session, application_id: UUID) -> Optional[Application]:
        """Récupère une candidature par son ID."""
        return db.query(Application).filter(Application.id == application_id).first()
    
    def get_user_applications(
        self,
        db: Session,
        user_id: UUID,
        skip: int = 0,
        limit: int = 50
    ) -> tuple[List[Application], int]:
        """Récupère toutes les candidatures d'un utilisateur."""
        query = db.query(Application).filter(Application.user_id == user_id)
        total = query.count()
        applications = query.order_by(Application.applied_at.desc()).offset(skip).limit(limit).all()
        return applications, total
    
    def get_company_applications(
        self,
        db: Session,
        company_id: UUID,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50
    ) -> tuple[List[Application], int]:
        """Récupère toutes les candidatures d'une entreprise."""
        query = db.query(Application).filter(Application.company_id == company_id)
        
        if status:
            query = query.filter(Application.status == status)
        
        total = query.count()
        applications = query.order_by(Application.applied_at.desc()).offset(skip).limit(limit).all()
        return applications, total
    
    def get_job_applications(
        self,
        db: Session,
        job_id: UUID,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[List[Application], int]:
        """Récupère toutes les candidatures pour une offre."""
        query = db.query(Application).filter(Application.job_id == job_id)
        total = query.count()
        applications = query.order_by(Application.applied_at.desc()).offset(skip).limit(limit).all()
        return applications, total
    
    def update_status(
        self,
        db: Session,
        application_id: UUID,
        status_data: ApplicationUpdateStatus,
        changed_by: UUID
    ) -> Optional[Application]:
        """
        Met à jour le statut d'une candidature.
        
        Args:
            db: Session de base de données
            application_id: ID de la candidature
            status_data: Nouvelles données de statut
            changed_by: ID du recruteur qui fait le changement
            
        Returns:
            Optional[Application]: La candidature mise à jour
        """
        application = self.get_application_by_id(db, application_id)
        if not application:
            return None
        
        if status_data.status not in self.VALID_STATUSES:
            raise ValueError(f"Statut invalide: {status_data.status}")
        
        old_status = application.status
        application.status = status_data.status
        
        # Mettre à jour les timestamps selon le statut
        if status_data.status == "shortlisted" and not application.reviewed_at:
            application.reviewed_at = datetime.now()
        
        if status_data.interview_date:
            application.interview_date = status_data.interview_date
        
        if status_data.status in ["hired", "rejected"]:
            application.decision_date = datetime.now()
        
        db.commit()
        db.refresh(application)
        
        # Créer l'entrée d'historique
        history = ApplicationStatusHistory(
            application_id=application.id,
            from_status=old_status,
            to_status=status_data.status,
            changed_by=changed_by,
            comment=status_data.comment
        )
        db.add(history)
        db.commit()
        
        logger.info(f"Statut candidature {application_id}: {old_status} → {status_data.status}")
        return application
    
    def update_notes(
        self,
        db: Session,
        application_id: UUID,
        notes_data: ApplicationUpdateNotes
    ) -> Optional[Application]:
        """Met à jour les notes RH d'une candidature."""
        application = self.get_application_by_id(db, application_id)
        if not application:
            return None
        
        if notes_data.notes is not None:
            application.notes = notes_data.notes
        
        if notes_data.rating is not None:
            application.rating = notes_data.rating
        
        db.commit()
        db.refresh(application)
        
        return application
    
    def get_application_history(
        self,
        db: Session,
        application_id: UUID
    ) -> List[ApplicationStatusHistory]:
        """Récupère l'historique des changements de statut."""
        return db.query(ApplicationStatusHistory).filter(
            ApplicationStatusHistory.application_id == application_id
        ).order_by(ApplicationStatusHistory.created_at.asc()).all()
    
    def get_application_stats(
        self,
        db: Session,
        company_id: Optional[UUID] = None,
        job_id: Optional[UUID] = None
    ) -> Dict:
        """
        Calcule des statistiques sur les candidatures.
        
        Args:
            db: Session de base de données
            company_id: Filtrer par entreprise
            job_id: Filtrer par offre
            
        Returns:
            Dict: Statistiques
        """
        query = db.query(Application)
        
        if company_id:
            query = query.filter(Application.company_id == company_id)
        
        if job_id:
            query = query.filter(Application.job_id == job_id)
        
        total = query.count()
        
        # Comptage par statut
        by_status = {}
        for status in self.VALID_STATUSES:
            count = query.filter(Application.status == status).count()
            if count > 0:
                by_status[status] = count
        
        # Temps moyen de review (applied → reviewed_at)
        reviewed_apps = query.filter(Application.reviewed_at.isnot(None)).all()
        if reviewed_apps:
            review_times = [
                (app.reviewed_at - app.applied_at).total_seconds() / 3600
                for app in reviewed_apps
            ]
            avg_time_to_review = sum(review_times) / len(review_times)
        else:
            avg_time_to_review = None
        
        # Temps moyen d'embauche (applied → hired)
        hired_apps = query.filter(Application.status == "hired").all()
        if hired_apps:
            hire_times = [
                (app.decision_date - app.applied_at).total_seconds() / (3600 * 24)
                for app in hired_apps if app.decision_date
            ]
            avg_time_to_hire = sum(hire_times) / len(hire_times) if hire_times else None
        else:
            avg_time_to_hire = None
        
        # Taux de conversion
        hired_count = by_status.get("hired", 0)
        conversion_rate = (hired_count / total * 100) if total > 0 else 0
        
        return {
            "total": total,
            "by_status": by_status,
            "avg_time_to_review": avg_time_to_review,
            "avg_time_to_hire": avg_time_to_hire,
            "conversion_rate": conversion_rate
        }
    
    def withdraw_application(
        self,
        db: Session,
        application_id: UUID,
        user_id: UUID
    ) -> Optional[Application]:
        """Permet à un candidat de retirer sa candidature."""
        application = self.get_application_by_id(db, application_id)
        
        if not application:
            return None
        
        if application.user_id != user_id:
            raise ValueError("Vous ne pouvez retirer que vos propres candidatures")
        
        if application.status in ["hired", "rejected"]:
            raise ValueError("Impossible de retirer une candidature déjà finalisée")
        
        old_status = application.status
        application.status = "withdrawn"
        db.commit()
        db.refresh(application)
        
        # Historique
        history = ApplicationStatusHistory(
            application_id=application.id,
            from_status=old_status,
            to_status="withdrawn",
            comment="Retrait par le candidat"
        )
        db.add(history)
        db.commit()
        
        return application
