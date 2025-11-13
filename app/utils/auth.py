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

    email: Optional[str] = payload.get("sub")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide : identifiant manquant.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ✅ 1. Chercher l'utilisateur par email
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Utilisateur non trouvé.",
        )

    # ✅ 2. Chercher le profil via user.id (UUID)
    user_profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
    if not user_profile:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Profil non trouvé.",
        )

    return user_profile

def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
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
        return db.query(UserProfile).filter(UserProfile.id == user_id).first()
    except Exception:
        return None

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
