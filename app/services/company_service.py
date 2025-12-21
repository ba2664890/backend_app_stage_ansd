"""
Service pour la gestion des entreprises.
"""

from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import UUID
import logging

from ..models.database_models import Company
from ..models.api_models import CompanyCreate, CompanyUpdate

logger = logging.getLogger(__name__)


class CompanyService:
    """Service pour gérer les entreprises."""
    
    def create_company(self, db: Session, company_data: CompanyCreate) -> Company:
        """
        Crée une nouvelle entreprise.
        
        Args:
            db: Session de base de données
            company_data: Données de l'entreprise à créer
            
        Returns:
            Company: L'entreprise créée
            
        Raises:
            ValueError: Si une entreprise avec le même nom existe déjà
        """
        # Vérifier si l'entreprise existe déjà
        existing = db.query(Company).filter(
            func.lower(Company.name) == func.lower(company_data.name)
        ).first()
        
        if existing:
            raise ValueError(f"Une entreprise avec le nom '{company_data.name}' existe déjà")
        
        # Créer l'entreprise
        company = Company(**company_data.model_dump())
        db.add(company)
        db.commit()
        db.refresh(company)
        
        logger.info(f"Entreprise créée: {company.name} (ID: {company.id})")
        return company
    
    def get_company_by_id(self, db: Session, company_id: UUID) -> Optional[Company]:
        """
        Récupère une entreprise par son ID.
        
        Args:
            db: Session de base de données
            company_id: ID de l'entreprise
            
        Returns:
            Optional[Company]: L'entreprise ou None si non trouvée
        """
        return db.query(Company).filter(Company.id == company_id).first()
    
    def get_companies(
        self,
        db: Session,
        skip: int = 0,
        limit: int = 20,
        sector: Optional[str] = None,
        is_verified: Optional[bool] = None,
        search: Optional[str] = None
    ) -> tuple[List[Company], int]:
        """
        Récupère une liste d'entreprises avec filtres.
        
        Args:
            db: Session de base de données
            skip: Nombre d'entreprises à ignorer
            limit: Nombre maximum d'entreprises à retourner
            sector: Filtrer par secteur
            is_verified: Filtrer par statut de vérification
            search: Recherche textuelle dans le nom ou la description
            
        Returns:
            tuple: (Liste d'entreprises, nombre total)
        """
        query = db.query(Company)
        
        # Appliquer les filtres
        if sector:
            query = query.filter(Company.sector == sector)
        
        if is_verified is not None:
            query = query.filter(Company.is_verified == is_verified)
        
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                (Company.name.ilike(search_pattern)) |
                (Company.description.ilike(search_pattern))
            )
        
        # Compter le total
        total = query.count()
        
        # Appliquer pagination
        companies = query.order_by(Company.created_at.desc()).offset(skip).limit(limit).all()
        
        return companies, total
    
    def update_company(
        self,
        db: Session,
        company_id: UUID,
        company_data: CompanyUpdate
    ) -> Optional[Company]:
        """
        Met à jour une entreprise.
        
        Args:
            db: Session de base de données
            company_id: ID de l'entreprise
            company_data: Données à mettre à jour
            
        Returns:
            Optional[Company]: L'entreprise mise à jour ou None si non trouvée
        """
        company = self.get_company_by_id(db, company_id)
        if not company:
            return None
        
        # Mettre à jour les champs fournis
        update_data = company_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(company, field, value)
        
        db.commit()
        db.refresh(company)
        
        logger.info(f"Entreprise mise à jour: {company.name} (ID: {company.id})")
        return company
    
    def verify_company(self, db: Session, company_id: UUID) -> Optional[Company]:
        """
        Vérifie une entreprise (marque is_verified = True).
        
        Args:
            db: Session de base de données
            company_id: ID de l'entreprise
            
        Returns:
            Optional[Company]: L'entreprise vérifiée ou None si non trouvée
        """
        company = self.get_company_by_id(db, company_id)
        if not company:
            return None
        
        company.is_verified = True
        db.commit()
        db.refresh(company)
        
        logger.info(f"Entreprise vérifiée: {company.name} (ID: {company.id})")
        return company
    
    def delete_company(self, db: Session, company_id: UUID) -> bool:
        """
        Supprime une entreprise.
        
        Args:
            db: Session de base de données
            company_id: ID de l'entreprise
            
        Returns:
            bool: True si supprimée, False si non trouvée
        """
        company = self.get_company_by_id(db, company_id)
        if not company:
            return False
        
        db.delete(company)
        db.commit()
        
        logger.info(f"Entreprise supprimée: {company.name} (ID: {company.id})")
        return True
