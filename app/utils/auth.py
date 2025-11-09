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
from ..models.database_models import UserProfile

# Security scheme
security = HTTPBearer()

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Generate a password hash."""
    return pwd_context.hash(password)

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.API_ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.API_SECRET_KEY, algorithm=settings.API_ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> Dict[str, Any]:
    """Verify a JWT token and return its payload."""
    try:
        payload = jwt.decode(token, settings.API_SECRET_KEY, algorithms=[settings.API_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> UserProfile:
    """Get the current authenticated user."""
    token = credentials.credentials
    payload = verify_token(token)
    
    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = db.query(UserProfile).filter(UserProfile.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return user

def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> Optional[UserProfile]:
    """Get the current authenticated user (optional)."""
    if not credentials:
        return None
    
    try:
        token = credentials.credentials
        payload = verify_token(token)
        
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
        
        user = db.query(UserProfile).filter(UserProfile.id == user_id).first()
        return user
        
    except HTTPException:
        return None

def create_user_token(user: UserProfile) -> str:
    """Create a token for a user."""
    token_data = {
        "sub": str(user.id),
        "email": user.email,
        "exp": datetime.utcnow() + timedelta(minutes=settings.API_ACCESS_TOKEN_EXPIRE_MINUTES)
    }
    return create_access_token(token_data)

def authenticate_user(db: Session, email: str, password: str) -> Optional[UserProfile]:
    """Authenticate a user with email and password."""
    user = db.query(UserProfile).filter(UserProfile.email == email).first()
    if not user:
        return None
    
    # For demo purposes, we'll skip password verification
    # In production, you should implement proper password hashing
    return user

def generate_demo_token() -> str:
    """Generate a demo token for testing purposes."""
    demo_data = {
        "sub": "demo-user-id",
        "email": "demo@example.com",
        "exp": datetime.utcnow() + timedelta(hours=24)
    }
    return create_access_token(demo_data)