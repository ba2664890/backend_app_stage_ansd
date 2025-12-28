from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from ..database import get_db
from ..models.api_models import UserResponse, PaginatedResponse
from ..utils.auth import get_current_user
from ..services.user_service import UserService

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
user_service = UserService()

@router.get("/users", response_model=PaginatedResponse[UserResponse])
async def search_users(
    role: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Recherche des utilisateurs par rôle ou texte (admin/recruiter only).
    """
    # TODO: Add proper permission check for Admin or Recruiter
    users, total = user_service.search_users(db, role=role, search=search, skip=skip, limit=limit)
    
    pages = (total + limit - 1) // limit
    page = (skip // limit) + 1
    
    return PaginatedResponse(
        items=users,
        total=total,
        page=page,
        size=limit,
        pages=pages,
        has_next=page < pages,
        has_prev=page > 1
    )
