"""
Service pour la gestion des recruteurs.
"""

from typing import List, Optional
from sqlalchemy.orm import Session
from uuid import UUID
import logging

from ..models.database_models import Recruiter, Company, User
from ..models.api_models import RecruiterCreate

logger = logging.getLogger(__name__)


class RecruiterService:
    """Service pour gérer les recruteurs."""
    
    def create_recruiter(
        self,
        db: Session,
        user_id: UUID,
        recruiter_data: RecruiterCreate
    ) -> Recruiter:
        """
        Crée un nouveau recruteur (associe un utilisateur à une entreprise).
        
        Args:
            db: Session de base de données
            user_id: ID de l'utilisateur
            recruiter_data: Données du recruteur
            
        Returns:
            Recruiter: Le recruteur créé
            
        Raises:
            ValueError: Si l'utilisateur n'existe pas, l'entreprise n'existe pas,
                       ou si l'association existe déjà
        """
        # Vérifier que l'utilisateur existe
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError(f"Utilisateur avec ID {user_id} non trouvé")
        
        # Vérifier que l'entreprise existe
        company = db.query(Company).filter(Company.id == recruiter_data.company_id).first()
        if not company:
            raise ValueError(f"Entreprise avec ID {recruiter_data.company_id} non trouvée")
        
        # Vérifier si l'association existe déjà
        existing = db.query(Recruiter).filter(
            Recruiter.user_id == user_id,
            Recruiter.company_id == recruiter_data.company_id
        ).first()
        
        if existing:
            raise ValueError(
                f"L'utilisateur {user_id} est déjà recruteur pour l'entreprise {recruiter_data.company_id}"
            )
        
        # Créer le recruteur
        recruiter = Recruiter(
            user_id=user_id,
            company_id=recruiter_data.company_id,
            role=recruiter_data.role
        )
        db.add(recruiter)
        db.commit()
        db.refresh(recruiter)
        
        logger.info(
            f"Recruteur créé: User {user_id} → Company {recruiter_data.company_id} (ID: {recruiter.id})"
        )
        return recruiter
    
    def get_recruiter_by_id(self, db: Session, recruiter_id: UUID) -> Optional[Recruiter]:
        """
        Récupère un recruteur par son ID.
        
        Args:
            db: Session de base de données
            recruiter_id: ID du recruteur
            
        Returns:
            Optional[Recruiter]: Le recruteur ou None si non trouvé
        """
        return db.query(Recruiter).filter(Recruiter.id == recruiter_id).first()
    
    def get_recruiters_by_company(
        self,
        db: Session,
        company_id: UUID,
        skip: int = 0,
        limit: int = 50
    ) -> tuple[List[Recruiter], int]:
        """
        Récupère tous les recruteurs d'une entreprise.
        
        Args:
            db: Session de base de données
            company_id: ID de l'entreprise
            skip: Nombre de recruteurs à ignorer
            limit: Nombre maximum de recruteurs à retourner
            
        Returns:
            tuple: (Liste de recruteurs, nombre total)
        """
        query = db.query(Recruiter).filter(Recruiter.company_id == company_id)
        
        total = query.count()
        recruiters = query.order_by(Recruiter.created_at.desc()).offset(skip).limit(limit).all()
        
        return recruiters, total
    
    def get_recruiter_by_user(self, db: Session, user_id: UUID) -> Optional[Recruiter]:
        """
        Récupère le profil recruteur d'un utilisateur.
        
        Args:
            db: Session de base de données
            user_id: ID de l'utilisateur
            
        Returns:
            Optional[Recruiter]: Le recruteur ou None si l'utilisateur n'est pas recruteur
        """
        return db.query(Recruiter).filter(Recruiter.user_id == user_id).first()

    def get_or_create_recruiter(self, db: Session, user_id: UUID) -> Optional[Recruiter]:
        """
        Récupère le profil recruteur ou le crée si l'utilisateur a le rôle requis.
        """
        recruiter = self.get_recruiter_by_user(db, user_id)
        if recruiter:
            return recruiter
            
        # Fallback registration
        from ..models.database_models import UserRole
        user = db.query(User).filter(User.id == user_id).first()
        if user and user.role in [UserRole.RECRUITER, UserRole.HR_MANAGER, UserRole.ADMIN]:
            company = db.query(Company).first()
            if not company:
                company = Company(name="Entreprise par défaut", sector="Général")
                db.add(company)
                db.commit()
                db.refresh(company)
            
            recruiter = Recruiter(
                user_id=user_id,
                company_id=company.id,
                role="admin"
            )
            db.add(recruiter)
            db.commit()
            db.refresh(recruiter)
            return recruiter
            
        return None
    
    def update_recruiter_role(
        self,
        db: Session,
        recruiter_id: UUID,
        new_role: str
    ) -> Optional[Recruiter]:
        """
        Met à jour le rôle d'un recruteur.
        
        Args:
            db: Session de base de données
            recruiter_id: ID du recruteur
            new_role: Nouveau rôle
            
        Returns:
            Optional[Recruiter]: Le recruteur mis à jour ou None si non trouvé
        """
        recruiter = self.get_recruiter_by_id(db, recruiter_id)
        if not recruiter:
            return None
        
        recruiter.role = new_role
        db.commit()
        db.refresh(recruiter)
        
        logger.info(f"Rôle du recruteur {recruiter_id} mis à jour: {new_role}")
        return recruiter
    
    def delete_recruiter(self, db: Session, recruiter_id: UUID) -> bool:
        """
        Supprime un recruteur (retire l'association utilisateur-entreprise).
        
        Args:
            db: Session de base de données
            recruiter_id: ID du recruteur
            
        Returns:
            bool: True si supprimé, False si non trouvé
        """
        recruiter = self.get_recruiter_by_id(db, recruiter_id)
        if not recruiter:
            return False
        
        db.delete(recruiter)
        db.commit()
        
        logger.info(f"Recruteur supprimé: {recruiter_id}")
        return True
