"""
Service pour la gestion des utilisateurs et profils.
"""

from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_
import logging
from datetime import datetime

from ..models.database_models import User, UserProfile
from ..models.api_models import UserProfileCreate, UserProfileResponse
from sqlalchemy.orm import Session, joinedload


logger = logging.getLogger(__name__)

class UserService:
    """Service pour gérer les opérations sur les utilisateurs."""
    
    def __init__(self):
        """Initialise le service utilisateur."""
        pass
    

    def create_or_update_profile(self, db: Session, user_id: str, profile_data: UserProfileCreate) -> UserProfile:
        """
        Crée ou met à jour le profil utilisateur et charge la relation 'user'.
        """
        try:
            # Chercher le profil existant par user_id
            existing_profile = db.query(UserProfile).options(joinedload(UserProfile.user)) \
                                .filter(UserProfile.user_id == user_id).first()
            print(existing_profile)
            if existing_profile:
                # Mettre à jour le profil existant
                for key, value in profile_data.dict().items():
                    setattr(existing_profile, key, value)
                db.commit()
                db.refresh(existing_profile)
                logger.info(f"Profil mis à jour pour l'utilisateur {user_id}")
                return existing_profile
            else:
                # Récupérer l'utilisateur pour la relation FK
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    raise ValueError(f"Utilisateur {user_id} introuvable")
                
                # Créer un nouveau profil
                new_profile = UserProfile(
                    user_id=user_id,
                    **profile_data.dict()
                )
                db.add(new_profile)
                db.commit()
                db.refresh(new_profile)
                logger.info(f"Profil créé pour l'utilisateur {user_id}")
                return new_profile

        except Exception as e:
            logger.error(f"Erreur lors de la création/mise à jour du profil: {e}")
            db.rollback()
            raise


    
    def get_user_profile(self, db: Session, user_id: str) -> Optional[UserProfile]:
        """
        Récupère le profil utilisateur.
        
        Args:
            db: Session de base de données
            user_id: ID de l'utilisateur
            
        Returns:
            Le profil utilisateur ou None
        """
        try:
            profile = db.query(UserProfile).filter(
                UserProfile.id == user_id
            ).first()
            
            return profile
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du profil: {e}")
            raise
    
    def get_job_alerts(self, db: Session, user_id: str) -> Dict[str, Any]:
        """
        Récupère les alertes d'emploi pour l'utilisateur.
        
        Args:
            db: Session de base de données
            user_id: ID de l'utilisateur
            
        Returns:
            Dictionnaire avec les alertes d'emploi
        """
        try:
            profile = self.get_user_profile(db, user_id)
            
            if not profile:
                return {
                    "alerts": [],
                    "message": "Profil utilisateur non trouvé"
                }
            
            # Ici vous pouvez implémenter la logique pour récupérer les alertes
            # basées sur les préférences de l'utilisateur
            alerts = []
            
            return {
                "alerts": alerts,
                "total_alerts": len(alerts),
                "message": "Alertes récupérées avec succès"
            }
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des alertes: {e}")
            raise
    
    def update_preferences(
        self, 
        db: Session, 
        user_id: str, 
        preferences: Dict[str, Any]
    ) -> UserProfile:
        """
        Met à jour les préférences de l'utilisateur.
        
        Args:
            db: Session de base de données
            user_id: ID de l'utilisateur
            preferences: Préférences à mettre à jour
            
        Returns:
            Le profil mis à jour
        """
        try:
            profile = self.get_user_profile(db, user_id)
            
            if not profile:
                raise ValueError("Profil utilisateur non trouvé")
            
            # Mettre à jour les préférences
            for key, value in preferences.items():
                if hasattr(profile, key):
                    setattr(profile, key, value)
            
            db.commit()
            db.refresh(profile)
            
            logger.info(f"Préférences mises à jour pour l'utilisateur {user_id}")
            return profile
            
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour des préférences: {e}")
            db.rollback()
            raise
    
    def delete_user_profile(self, db: Session, user_id: str) -> bool:
        """
        Supprime le profil utilisateur.
        
        Args:
            db: Session de base de données
            user_id: ID de l'utilisateur
            
        Returns:
            True si la suppression a réussi
        """
        try:
            profile = self.get_user_profile(db, user_id)
            
            if not profile:
                return False
            
            db.delete(profile)
            db.commit()
            
            logger.info(f"Profil supprimé pour l'utilisateur {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur lors de la suppression du profil: {e}")
            db.rollback()
            raise
    
    def get_profile_completion_percentage(self, profile: UserProfile) -> int:
        """
        Calcule le pourcentage de complétion du profil.
        
        Args:
            profile: Profil utilisateur
            
        Returns:
            Pourcentage de complétion (0-100)
        """
        required_fields = [
            'first_name', 'last_name',  'skills',
            'experience_years', 'education_level'
        ]
        
        completed_fields = 0
        
        for field in required_fields:
            value = getattr(profile, field, None)
            if field == 'skills' and isinstance(value, list) and len(value) > 0:
                completed_fields += 1
            elif field == 'experience_years' and (value and value > 0):
                completed_fields += 1
            elif value and str(value).strip():
                completed_fields += 1
        
        return int((completed_fields / len(required_fields)) * 100)
    
    def search_users_by_skills(
        self, 
        db: Session, 
        skills: list[str], 
        limit: int = 10
    ) -> list[UserProfile]:
        """
        Recherche des utilisateurs par compétences.
        
        Args:
            db: Session de base de données
            skills: Liste de compétences à rechercher
            limit: Nombre maximum de résultats
            
        Returns:
            Liste des utilisateurs correspondants
        """
        try:
            query = db.query(UserProfile)
            
            # Filtrer par compétences (utilisateur ayant au moins une compétence recherchée)
            if skills:
                conditions = []
                for skill in skills:
                    conditions.append(UserProfile.skills.any(skill))
                
                if conditions:
                    query = query.filter(or_(*conditions))
            
            users = query.limit(limit).all()
            return users
            
        except Exception as e:
            logger.error(f"Erreur lors de la recherche par compétences: {e}")
            raise