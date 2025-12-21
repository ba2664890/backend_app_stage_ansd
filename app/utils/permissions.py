"""
Système de permissions RBAC (Role-Based Access Control).
"""

from enum import Enum
from typing import List, Optional
from functools import wraps
from fastapi import HTTPException, Depends
from sqlalchemy.orm import Session
from uuid import UUID

from ..database import get_db
from ..models.database_models import User, Role, UserRole


class Permission(str, Enum):
    """Énumération des permissions disponibles."""
    
    # Permissions générales
    VIEW_DASHBOARD = "view_dashboard"
    
    # Permissions entreprises
    CREATE_COMPANY = "create_company"
    UPDATE_COMPANY = "update_company"
    DELETE_COMPANY = "delete_company"
    VERIFY_COMPANY = "verify_company"
    
    # Permissions candidatures
    VIEW_APPLICATIONS = "view_applications"
    VIEW_OWN_APPLICATIONS = "view_own_applications"
    MANAGE_APPLICATIONS = "manage_applications"
    UPDATE_APPLICATION_STATUS = "update_application_status"
    
    # Permissions utilisateurs
    MANAGE_USERS = "manage_users"
    ASSIGN_ROLES = "assign_roles"
    
    # Permissions analytics
    VIEW_ANALYTICS = "view_analytics"
    VIEW_COMPANY_ANALYTICS = "view_company_analytics"
    
    # Permissions AI
    USE_AI_ASSISTANT = "use_ai_assistant"
    
    # Permissions exports
    EXPORT_DATA = "export_data"


class RoleType(str, Enum):
    """Types de rôles prédéfinis."""
    ADMIN = "admin"
    RECRUITER = "recruiter"
    HR_MANAGER = "hr_manager"
    CANDIDATE = "candidate"


# Définition des permissions par rôle
ROLE_PERMISSIONS = {
    RoleType.ADMIN: [
        Permission.VIEW_DASHBOARD,
        Permission.CREATE_COMPANY,
        Permission.UPDATE_COMPANY,
        Permission.DELETE_COMPANY,
        Permission.VERIFY_COMPANY,
        Permission.VIEW_APPLICATIONS,
        Permission.MANAGE_APPLICATIONS,
        Permission.UPDATE_APPLICATION_STATUS,
        Permission.MANAGE_USERS,
        Permission.ASSIGN_ROLES,
        Permission.VIEW_ANALYTICS,
        Permission.VIEW_COMPANY_ANALYTICS,
        Permission.USE_AI_ASSISTANT,
        Permission.EXPORT_DATA,
    ],
    RoleType.HR_MANAGER: [
        Permission.VIEW_DASHBOARD,
        Permission.UPDATE_COMPANY,
        Permission.VIEW_APPLICATIONS,
        Permission.MANAGE_APPLICATIONS,
        Permission.UPDATE_APPLICATION_STATUS,
        Permission.VIEW_COMPANY_ANALYTICS,
        Permission.USE_AI_ASSISTANT,
        Permission.EXPORT_DATA,
    ],
    RoleType.RECRUITER: [
        Permission.VIEW_DASHBOARD,
        Permission.VIEW_APPLICATIONS,
        Permission.UPDATE_APPLICATION_STATUS,
        Permission.VIEW_COMPANY_ANALYTICS,
        Permission.USE_AI_ASSISTANT,
    ],
    RoleType.CANDIDATE: [
        Permission.VIEW_OWN_APPLICATIONS,
    ],
}


class PermissionService:
    """Service pour gérer les permissions."""
    
    def get_user_permissions(self, db: Session, user_id: UUID) -> List[str]:
        """Récupère toutes les permissions d'un utilisateur."""
        user_roles = db.query(UserRole).filter(UserRole.user_id == user_id).all()
        
        all_permissions = set()
        for user_role in user_roles:
            if user_role.role and user_role.role.permissions:
                all_permissions.update(user_role.role.permissions)
        
        return list(all_permissions)
    
    def has_permission(self, db: Session, user_id: UUID, permission: Permission) -> bool:
        """Vérifie si un utilisateur a une permission spécifique."""
        permissions = self.get_user_permissions(db, user_id)
        return permission.value in permissions
    
    def has_any_permission(self, db: Session, user_id: UUID, permissions: List[Permission]) -> bool:
        """Vérifie si un utilisateur a au moins une des permissions."""
        user_permissions = self.get_user_permissions(db, user_id)
        return any(perm.value in user_permissions for perm in permissions)
    
    def has_all_permissions(self, db: Session, user_id: UUID, permissions: List[Permission]) -> bool:
        """Vérifie si un utilisateur a toutes les permissions."""
        user_permissions = self.get_user_permissions(db, user_id)
        return all(perm.value in user_permissions for perm in permissions)
    
    def assign_role(
        self,
        db: Session,
        user_id: UUID,
        role_name: str,
        assigned_by: UUID
    ) -> UserRole:
        """Assigne un rôle à un utilisateur."""
        # Vérifier que le rôle existe
        role = db.query(Role).filter(Role.name == role_name).first()
        if not role:
            raise ValueError(f"Rôle '{role_name}' non trouvé")
        
        # Vérifier si déjà assigné
        existing = db.query(UserRole).filter(
            UserRole.user_id == user_id,
            UserRole.role_id == role.id
        ).first()
        
        if existing:
            return existing
        
        # Créer l'assignation
        user_role = UserRole(
            user_id=user_id,
            role_id=role.id,
            assigned_by=assigned_by
        )
        db.add(user_role)
        db.commit()
        db.refresh(user_role)
        
        return user_role
    
    def remove_role(self, db: Session, user_id: UUID, role_name: str) -> bool:
        """Retire un rôle d'un utilisateur."""
        role = db.query(Role).filter(Role.name == role_name).first()
        if not role:
            return False
        
        user_role = db.query(UserRole).filter(
            UserRole.user_id == user_id,
            UserRole.role_id == role.id
        ).first()
        
        if user_role:
            db.delete(user_role)
            db.commit()
            return True
        
        return False
    
    def initialize_default_roles(self, db: Session):
        """Initialise les rôles par défaut dans la base de données."""
        for role_type, permissions in ROLE_PERMISSIONS.items():
            existing_role = db.query(Role).filter(Role.name == role_type.value).first()
            
            if not existing_role:
                role = Role(
                    name=role_type.value,
                    description=f"Rôle {role_type.value}",
                    permissions=[p.value for p in permissions]
                )
                db.add(role)
        
        db.commit()


# Décorateurs pour vérifier les permissions

def require_permission(permission: Permission):
    """Décorateur pour vérifier qu'un utilisateur a une permission."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, current_user=None, db: Session = None, **kwargs):
            if current_user is None or db is None:
                raise HTTPException(status_code=401, detail="Non authentifié")
            
            permission_service = PermissionService()
            user_id = current_user.user_id
            
            if not permission_service.has_permission(db, user_id, permission):
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission refusée: {permission.value} requise"
                )
            
            return await func(*args, current_user=current_user, db=db, **kwargs)
        return wrapper
    return decorator


def require_any_permission(*permissions: Permission):
    """Décorateur pour vérifier qu'un utilisateur a au moins une des permissions."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, current_user=None, db: Session = None, **kwargs):
            if current_user is None or db is None:
                raise HTTPException(status_code=401, detail="Non authentifié")
            
            permission_service = PermissionService()
            user_id = current_user.user_id
            
            if not permission_service.has_any_permission(db, user_id, list(permissions)):
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission refusée: une des permissions {[p.value for p in permissions]} requise"
                )
            
            return await func(*args, current_user=current_user, db=db, **kwargs)
        return wrapper
    return decorator


def require_role(role: RoleType):
    """Décorateur pour vérifier qu'un utilisateur a un rôle spécifique."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, current_user=None, db: Session = None, **kwargs):
            if current_user is None or db is None:
                raise HTTPException(status_code=401, detail="Non authentifié")
            
            user_id = current_user.user_id
            user_role = db.query(UserRole).join(Role).filter(
                UserRole.user_id == user_id,
                Role.name == role.value
            ).first()
            
            if not user_role:
                raise HTTPException(
                    status_code=403,
                    detail=f"Rôle '{role.value}' requis"
                )
            
            return await func(*args, current_user=current_user, db=db, **kwargs)
        return wrapper
    return decorator
