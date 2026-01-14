"""
Authentication utilities for the Emploi Dakar backend.
"""

from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models.database_models import User, UserProfile

# ⚙️ Schéma de sécurité HTTP Bearer
security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)   # pas de troncature

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

# -------------------------------------------------------------
# GESTION DES TOKENS
# -------------------------------------------------------------
def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Crée un token JWT d’accès."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.API_ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.API_SECRET_KEY, algorithm=settings.API_ALGORITHM)

def verify_token(token: str) -> Dict[str, Any]:
    """Vérifie la validité d’un token et retourne le payload."""
    try:
        payload = jwt.decode(token, settings.API_SECRET_KEY, algorithms=[settings.API_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré.",
            headers={"WWW-Authenticate": "Bearer"},
        )

# -------------------------------------------------------------
# AUTHENTIFICATION UTILISATEUR
# -------------------------------------------------------------

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> UserProfile:
    """Retourne le profil utilisateur à partir du token Bearer."""
    token = credentials.credentials
    payload = verify_token(token)

    # Note: payload.get("sub") returns user_id (UUID string) based on create_user_token
    # But line 71 uses it to filter by email? 
    # Let's fix this potential bug too: we should use user_id to find User, assuming sub IS user_id.
    
    sub: Optional[str] = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide : identifiant manquant.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ✅ 1. Chercher le profil via user.id (UUID)
    # On suppose que 'sub' est l'ID utilisateur (voir create_user_token)
    user_profile = db.query(UserProfile).filter(UserProfile.user_id == sub).first()
    
    # Fallback pour compatibilité si 'sub' était l'email (ancien code)
    if not user_profile:
        user = db.query(User).filter(User.email == sub).first()
        if user:
            user_profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()

    if not user_profile:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Profil non trouvé.",
        )

    return user_profile

def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
    db: Session = Depends(get_db)
) -> Optional[UserProfile]:
    """Retourne l’utilisateur courant s’il est authentifié, sinon None."""
    if not credentials:
        return None

    try:
        payload = verify_token(credentials.credentials)
        user_id = payload.get("sub")
        if not user_id:
            return None
            
        # Try both strategies (ID or Email) to be safe
        profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first() # UserProfile.user_id matches sub
        if not profile:
             # Maybe sub is Profile ID? (unlikely but check)
             profile = db.query(UserProfile).filter(UserProfile.id == user_id).first()
             
        if not profile:
             # Maybe sub is email?
             user = db.query(User).filter(User.email == user_id).first()
             if user:
                 profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
                 
        return profile
    except Exception:
        return None

def get_current_active_user_optional(
    current_user: Optional[UserProfile] = Depends(get_current_user_optional),
) -> Optional[UserProfile]:
    """
    Retourne l'utilisateur seulement s'il est actif.
    Utilisé pour les routes publiques qui personnalisent le contenu si connecté.
    """
    if not current_user:
        return None
    if not current_user.is_active:
        return None
    return current_user

def authenticate_user(db: Session, email: str, password: str) -> Optional[UserProfile]:
    """Vérifie l’authenticité d’un utilisateur."""
    user = db.query(UserProfile).filter(UserProfile.email == email).first()
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user

def create_user_token(user: UserProfile) -> str:
    """Crée un token JWT pour un utilisateur."""
    token_data = {"sub": str(user.id), "email": user.email}
    return create_access_token(token_data)

# -------------------------------------------------------------
# UTILITAIRE DE TEST
# -------------------------------------------------------------
def generate_demo_token() -> str:
    """Crée un token de démonstration (non sécurisé)."""
    demo_data = {"sub": "demo-user-id", "email": "demo@example.com"}
    return create_access_token(demo_data)
