"""
Service pour la gestion des candidatures (ATS - Applicant Tracking System).
"""

from typing import List, Optional, Dict
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_
from uuid import UUID
from datetime import datetime, timedelta
import logging

from ..models.database_models import Application, ApplicationStatusHistory, User, UserProfile, OffreEmploiEnrichie, Company
from ..models.api_models import ApplicationCreate, ApplicationUpdateStatus, ApplicationUpdateNotes

logger = logging.getLogger(__name__)


class ApplicationService:
    """Service pour gérer les candidatures."""
    
    VALID_STATUSES = [
        "applied", "shortlisted", "interview_scheduled", "interview_completed",
        "offer_made", "hired", "rejected", "withdrawn"
    ]
    
    async def create_application(
        self,
        db: Session,
        user_id: UUID,
        application_data: ApplicationCreate,
        cv_file: Optional[any] = None  # Using any to avoid UploadFile import issues if needed, but it's FastAPI's UploadFile
    ) -> Application:
        """
        Crée une nouvelle candidature avec support optionnel pour l'upload d'un CV.
        Gère les doublons de documents (met à jour si le CV existe déjà).
        """
        import os
        import uuid
        import shutil
        from datetime import datetime
        from ..models.database_models import Document
        from .file_service import FileService
        
        # 1. Chercher l'offre enrichie
        job = db.query(OffreEmploiEnrichie).filter(
            OffreEmploiEnrichie.offre_id == application_data.job_id
        ).first()
        
        # 2. Si non enrichie, chercher l'offre brute
        if not job:
            from ..models.database_models import OffreEmploiBrute
            brute = db.query(OffreEmploiBrute).filter(
                OffreEmploiBrute.id == application_data.job_id
            ).first()
            
            if not brute:
                raise ValueError(f"Offre d'emploi {application_data.job_id} non trouvée")
            
            job = OffreEmploiEnrichie(
                offre_id=brute.id,
                processed_at=None,
                confidence_score=0.0
            )
            db.add(job)
            db.commit()
            db.refresh(job)
        else:
            brute = job.offre_brute

        # 3. Récupérer l'entreprise
        company_id = None
        if brute.company_id:
            company_id = brute.company_id
        else:
            from ..models.database_models import Company
            company = db.query(Company).filter(Company.name == brute.company_name).first()
            if company:
                company_id = company.id
            else:
                raise ValueError(f"L'entreprise '{brute.company_name}' n'est pas référencée")
        
        # 4. Vérifier si candidature existe déjà
        existing = db.query(Application).filter(
            Application.user_id == user_id,
            Application.job_id == job.id
        ).first()
        
        if existing:
            raise ValueError("Vous avez déjà postulé à cette offre")
        
        # 5. Gérer le CV (Upload et dédoublonnage)
        cv_id = None
        if cv_file:
            UPLOAD_DIR = "app/static/uploads"
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            
            file_ext = os.path.splitext(cv_file.filename)[1]
            unique_filename = f"{user_id}_{uuid.uuid4()}{file_ext}"
            file_path = os.path.join(UPLOAD_DIR, unique_filename)
            
            # Sauvegarder le fichier
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(cv_file.file, buffer)
            
            # Extraire le texte
            file_service = FileService()
            extracted_text = None
            try:
                extracted_text = await file_service.extract_text_from_file(file_path)
            except Exception as e:
                logger.warning(f"Erreur d'extraction texte CV: {e}")
            
            # GÉRER LES DOUBLONS : Chercher si un CV avec le même nom existe déjà pour cet utilisateur
            existing_doc = db.query(Document).filter(
                Document.user_id == user_id,
                Document.category == "cv",
                Document.name == cv_file.filename
            ).first()
            
            if existing_doc:
                # Mise à jour du document existant (évite les doublons dans le profil)
                logger.info(f"Mise à jour du CV existant '{cv_file.filename}' pour l'utilisateur {user_id}")
                # Supprimer l'ancien fichier si possible
                if os.path.exists(existing_doc.file_path):
                    try: os.remove(existing_doc.file_path)
                    except: pass
                
                existing_doc.file_path = file_path
                existing_doc.extracted_text = extracted_text
                existing_doc.uploaded_at = datetime.utcnow()
                cv_id = existing_doc.id
            else:
                # Créer un nouveau document
                new_doc = Document(
                    user_id=user_id,
                    name=cv_file.filename,
                    file_path=file_path,
                    file_type=cv_file.content_type or "application/pdf",
                    category="cv",
                    extracted_text=extracted_text,
                    uploaded_at=datetime.utcnow()
                )
                db.add(new_doc)
                db.flush() # Pour récupérer l'ID
                cv_id = new_doc.id
        
        # 6. Créer la candidature
        application = Application(
            user_id=user_id,
            job_id=job.id,
            company_id=company_id,
            cover_letter=application_data.cover_letter,
            cv_id=cv_id,
            status="applied"
        )
        
        db.add(application)
        db.commit()
        db.refresh(application)
        
        # 7. Historique
        history = ApplicationStatusHistory(
            application_id=application.id,
            from_status=None,
            to_status="applied",
            comment="Candidature initiale (avec CV)" if cv_id else "Candidature initiale"
        )
        db.add(history)
        db.commit()
        
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
        """Récupère toutes les candidatures d'une entreprise avec détails."""
        query = db.query(Application).filter(Application.company_id == company_id)
        
        if status:
            query = query.filter(Application.status == status)
        
        total = query.count()
        applications = query.options(
            joinedload(Application.user).joinedload(User.profile),
            joinedload(Application.job).joinedload(OffreEmploiEnrichie.offre_brute)
        ).order_by(Application.applied_at.desc()).offset(skip).limit(limit).all()
        
        # Enriches applications with basic details if needed (or rely on relationship loading)
        # However, for ApplicationWithDetailsResponse, we need specific fields.
        # Ensure relationships are loaded
        for app in applications:
            if app.user:
                profile = app.user.profile
                app.user_name = f"{profile.first_name} {profile.last_name}" if profile else "Candidat"
                app.user_email = app.user.email
            if app.job and app.job.offre_brute:
                app.job_title = app.job.offre_brute.title
                app.company_name = app.job.offre_brute.company_name

        return applications, total
    
    def get_job_applications(
        self,
        db: Session,
        job_id: UUID,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[List[Application], int]:
        """Récupère toutes les candidatures pour une offre avec détails."""
        query = db.query(Application).filter(Application.job_id == job_id)
        total = query.count()
        applications = query.options(
            joinedload(Application.user).joinedload(User.profile),
            joinedload(Application.job).joinedload(OffreEmploiEnrichie.offre_brute)
        ).order_by(Application.applied_at.desc()).offset(skip).limit(limit).all()
        
        for app in applications:
            if app.user:
                profile = app.user.profile
                app.user_name = f"{profile.first_name if profile else ''} {profile.last_name if profile else ''}".strip() or "Candidat"
                app.user_email = app.user.email
            if app.job and app.job.offre_brute:
                app.job_title = app.job.offre_brute.title
                app.company_name = app.job.offre_brute.company_name
                
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
        job_id: Optional[UUID] = None,
        include_history: bool = True
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
                for app in hired_apps if app.decision_date and app.applied_at
            ]
            avg_time_to_hire = sum(hire_times) / len(hire_times) if hire_times else None
        else:
            avg_time_to_hire = None
        
        # Match Score Moyen
        avg_match_score = query.with_entities(func.avg(Application.match_score)).scalar()
        
        # Activités récentes
        recent_activities = []
        if include_history:
            history_query = db.query(ApplicationStatusHistory).join(Application).join(User).outerjoin(UserProfile)
            if company_id:
                history_query = history_query.filter(Application.company_id == company_id)
            if job_id:
                history_query = history_query.filter(Application.job_id == job_id)
            
            activities = history_query.order_by(ApplicationStatusHistory.created_at.desc()).limit(5).all()
            
            status_labels = {
                "applied": "Candidature reçue",
                "shortlisted": "Profil présélectionné",
                "interview_scheduled": "Entretien planifié",
                "interview_completed": "Entretien réalisé",
                "offer_made": "Offre envoyée",
                "hired": "Candidat recruté",
                "rejected": "Candidature refusée",
                "withdrawn": "Candidature retirée"
            }
            
            for act in activities:
                # Récupérer l'utilisateur (candidat) lié à la candidature
                candidate = act.application.user
                profile = candidate.profile if candidate else None
                candidate_name = f"{profile.first_name} {profile.last_name}" if profile else (candidate.email if candidate else "Candidat")
                
                recent_activities.append({
                    "id": act.id,
                    "application_id": act.application_id,
                    "from_status": act.from_status,
                    "to_status": act.to_status,
                    "changed_by": act.changed_by,
                    "comment": act.comment,
                    "created_at": act.created_at,
                    "candidate_name": candidate_name,
                    "action_label": status_labels.get(act.to_status, act.to_status)
                })
        
        # Taux de conversion
        hired_count = by_status.get("hired", 0)
        conversion_rate = (hired_count / total * 100) if total > 0 else 0
        
        return {
            "total": total,
            "by_status": by_status,
            "avg_time_to_review": avg_time_to_review,
            "avg_time_to_hire": avg_time_to_hire,
            "conversion_rate": conversion_rate,
            "avg_match_score": avg_match_score,
            "recent_activities": recent_activities
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
