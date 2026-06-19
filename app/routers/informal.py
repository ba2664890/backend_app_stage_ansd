"""
Routes API pour le secteur informel.
Endpoints pour: Passeport, Portfolio, Badges, Mentoring, Trust Bonds, Formations, Micro-crédits
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from uuid import UUID

from ..database import get_db
from ..models.informal_models import (
    DigitalPassport, ProjectPortfolio, Badge, Mentorship, 
    TrustBond, TrainingCourse, MicroLoan, CareerProgression
)
from ..models.database_models import User
from ..services.informal_service import (
    DigitalPassportService, PortfolioService, BadgeService,
    MentoringService, TrustBondService, TrainingService,
    MicroLoanService, SkillMappingService, PeerRecommendationService,
    CareerProgressionService
)
from ..utils.auth import get_current_user


router = APIRouter(
    prefix="/api/v1/informal",
    tags=["Informal Sector"],
    responses={404: {"description": "Not found"}},
)


# ==================== 1. PASSEPORT NUMÉRIQUE ====================

@router.post("/passport/create", response_model=Dict)
async def create_passport(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Créer un Passeport Numérique."""
    passport = await DigitalPassportService.create_passport(db, str(current_user.id))
    return {
        "passport_id": str(passport.id),
        "status": passport.status.value,
        "trust_score": passport.trust_score,
        "message": "Passeport créé! Invitez vos pairs pour le valider."
    }


@router.post("/passport/{passport_id}/add-review", response_model=Dict)
async def add_peer_review(
    passport_id: str,
    rating: int,
    comment: str,
    skills_validated: List[str],
    work_relationship: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ajouter une évaluation de pair au Passeport."""
    if rating < 1 or rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be 1-5")
    
    review = await DigitalPassportService.add_peer_review(
        db, passport_id, str(current_user.id), rating, comment,
        skills_validated, work_relationship
    )
    
    return {
        "review_id": str(review.id),
        "rating": review.rating,
        "message": "Évaluation ajoutée au Passeport"
    }


@router.get("/passport/progress", response_model=Dict)
async def get_passport_progress(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer la progression du Passeport."""
    progress = await DigitalPassportService.get_passport_progress(db, str(current_user.id))
    if not progress:
        raise HTTPException(status_code=404, detail="Passport not found")
    return progress


# ==================== 2. PORTFOLIO ====================

@router.post("/portfolio/create-project", response_model=Dict)
async def create_project(
    title: str,
    description: str,
    category: str,
    skills_used: List[str],
    budget: int,
    result_description: str,
    media_urls: List[str],
    client_name: str,
    client_contact: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Créer un nouveau projet dans le portfolio."""
    project = await PortfolioService.create_project(
        db, str(current_user.id), title, description, category,
        skills_used, budget, result_description, media_urls,
        client_name, client_contact
    )
    
    return {
        "project_id": str(project.id),
        "title": project.title,
        "message": "Projet ajouté au portfolio"
    }


@router.post("/portfolio/{project_id}/verify-client", response_model=Dict)
async def verify_client_feedback(
    project_id: str,
    client_feedback: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Vérifier et ajouter le feedback client."""
    project = await PortfolioService.verify_client_feedback(db, project_id, client_feedback)
    
    return {
        "project_id": str(project.id),
        "is_verified": project.is_client_verified,
        "message": "Feedback client ajouté et vérifié"
    }


@router.get("/portfolio/stats", response_model=Dict)
async def get_portfolio_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer les stats du portfolio."""
    stats = await PortfolioService.get_portfolio_stats(db, str(current_user.id))
    return stats


# ==================== 3. BADGES & CERTIFICATS ====================

@router.get("/badges", response_model=List[Dict])
async def get_user_badges(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer tous les badges de l'utilisateur."""
    badges = await BadgeService.get_user_badges(db, str(current_user.id))
    return badges


@router.post("/badges/check", response_model=Dict)
async def check_badge_eligibility(
    badge_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Vérifier si l'utilisateur peut obtenir un badge."""
    is_eligible = await BadgeService.check_badge_criteria(
        db, str(current_user.id), badge_id
    )
    
    return {
        "badge_id": badge_id,
        "is_eligible": is_eligible,
        "message": "Vous avez les critères!" if is_eligible else "Vous n'avez pas tous les critères"
    }


# ==================== 4. MENTORAT ====================

@router.post("/mentoring/request", response_model=Dict)
async def request_mentorship(
    mentor_id: str,
    skill_focus: str,
    duration_weeks: int = 12,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Demander du mentorat."""
    expected_end = datetime.now() + timedelta(weeks=duration_weeks)
    mentorship = await MentoringService.create_mentorship_request(
        db, mentor_id, str(current_user.id), skill_focus, expected_end
    )
    
    return {
        "mentorship_id": str(mentorship.id),
        "status": mentorship.status.value,
        "message": "Demande de mentorat créée"
    }


@router.post("/mentoring/{mentorship_id}/accept", response_model=Dict)
async def accept_mentorship(
    mentorship_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Accepter une demande de mentorat."""
    mentorship = await MentoringService.accept_mentorship(
        db, mentorship_id, datetime.now()
    )
    
    return {
        "mentorship_id": str(mentorship.id),
        "status": mentorship.status.value,
        "message": "Mentorat accepté!"
    }


@router.post("/mentoring/{mentorship_id}/log-session", response_model=Dict)
async def log_mentorship_session(
    mentorship_id: str,
    topic: str,
    summary: str,
    duration_minutes: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Enregistrer une session de mentorat."""
    session = await MentoringService.log_mentorship_session(
        db, mentorship_id, topic, summary, duration_minutes
    )
    
    return {
        "session_id": str(session.id),
        "duration": session.duration_minutes,
        "message": "Session enregistrée"
    }


# ==================== 5. GARANTIE DE CONFIANCE ====================

@router.post("/trust-bond/request", response_model=Dict)
async def request_trust_bond(
    amount: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Demander une garantie de confiance."""
    expiration = datetime.now() + timedelta(days=365)
    bond = await TrustBondService.create_trust_bond(
        db, str(current_user.id), amount, expiration
    )
    
    return {
        "bond_id": str(bond.id),
        "amount": bond.amount,
        "status": bond.status.value,
        "message": "Demande de garantie créée"
    }


@router.post("/trust-bond/{bond_id}/file-claim", response_model=Dict)
async def file_trust_bond_claim(
    bond_id: str,
    reason: str,
    amount_claimed: int,
    evidence_urls: List[str],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Déposer une réclamation contre une garantie."""
    claim = await TrustBondService.file_claim(
        db, bond_id, str(current_user.id), reason, amount_claimed, evidence_urls
    )
    
    return {
        "claim_id": str(claim.id),
        "status": claim.status,
        "message": "Réclamation déposée, en attente d'investigation"
    }


# ==================== 6. FORMATIONS ====================

@router.post("/training/enroll", response_model=Dict)
async def enroll_course(
    course_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """S'inscrire à une formation."""
    enrollment = await TrainingService.enroll_user(db, course_id, str(current_user.id))
    
    return {
        "enrollment_id": str(enrollment.id),
        "progress": enrollment.progress_percentage,
        "message": "Inscrit à la formation!"
    }


@router.get("/training/available", response_model=List[Dict])
async def list_available_courses(
    category: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Lister les formations disponibles."""
    from sqlalchemy import select
    query = select(TrainingCourse)
    if category:
        query = query.where(TrainingCourse.category == category)
    
    courses = db.execute(query).scalars().all()
    
    return [
        {
            "course_id": str(c.id),
            "title": c.title,
            "category": c.category,
            "level": c.level.value,
            "duration": c.duration_hours,
            "cost": c.cost,
            "format": c.format
        }
        for c in courses
    ]


@router.post("/training/{enrollment_id}/complete", response_model=Dict)
async def complete_course(
    enrollment_id: str,
    final_score: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Marquer une formation comme complétée."""
    if final_score < 0 or final_score > 100:
        raise HTTPException(status_code=400, detail="Score must be 0-100")
    
    enrollment = await TrainingService.complete_course(db, enrollment_id, final_score)
    
    return {
        "enrollment_id": str(enrollment.id),
        "is_certified": enrollment.is_certified,
        "score": enrollment.final_score,
        "certificate_url": enrollment.certificate_url if enrollment.is_certified else None,
        "message": "Formation complétée!" if enrollment.is_certified else "Score insuffisant"
    }


# ==================== 7. MICRO-CRÉDITS ====================

@router.post("/micro-loans/request", response_model=Dict)
async def request_micro_loan(
    loan_amount: int,
    purpose: str,
    description: str,
    duration_months: int = 12,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Demander un micro-crédit."""
    if loan_amount < 50000 or loan_amount > 5000000:
        raise HTTPException(status_code=400, detail="Loan amount must be 50K-5M CFA")
    
    loan = await MicroLoanService.request_loan(
        db, str(current_user.id), loan_amount, purpose, description, duration_months
    )
    
    return {
        "loan_id": str(loan.id),
        "amount": loan.loan_amount,
        "monthly_payment": loan.monthly_payment,
        "status": loan.status.value,
        "message": "Demande créée, en attente d'approbation"
    }


@router.post("/micro-loans/{loan_id}/record-payment", response_model=Dict)
async def record_loan_payment(
    loan_id: str,
    amount: int,
    payment_method: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Enregistrer un paiement de prêt."""
    payment = await MicroLoanService.record_payment(db, loan_id, amount, payment_method)
    
    return {
        "payment_id": str(payment.id),
        "amount": payment.amount,
        "payment_date": payment.payment_date.isoformat(),
        "message": "Paiement enregistré"
    }


# ==================== 8. MAPPING DE COMPÉTENCES (IA) ====================

@router.post("/skills/map-informal", response_model=Dict)
async def map_informal_skill(
    informal_skill: str,
    context: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mapper automatiquement une compétence informelle → compétences formelles."""
    from ..services.llm_client import LLMClient
    llm_client = LLMClient()
    service = SkillMappingService(llm_client)
    
    mapping = await service.map_informal_skills(
        db, str(current_user.id), informal_skill, context
    )
    
    return {
        "mapping_id": str(mapping.id),
        "informal_skill": mapping.informal_skill_description,
        "formal_skills": mapping.mapped_formal_skills,
        "confidence": mapping.mapping_confidence,
        "message": "Compétences mappées par IA"
    }


# ==================== 9. RECOMMANDATIONS PAR PAIRS ====================

@router.post("/recommendations/give", response_model=Dict)
async def give_recommendation(
    recommended_user_id: str,
    skills_recommended: List[str],
    reason: str,
    confidence_level: int,
    work_relationship: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Donner une recommandation à un pair."""
    if confidence_level < 1 or confidence_level > 5:
        raise HTTPException(status_code=400, detail="Confidence must be 1-5")
    
    recommendation = await PeerRecommendationService.create_recommendation(
        db, str(current_user.id), recommended_user_id, skills_recommended,
        reason, confidence_level, work_relationship
    )
    
    return {
        "recommendation_id": str(recommendation.id),
        "recommended_user": recommended_user_id,
        "message": "Recommandation créée"
    }


@router.get("/recommendations/received", response_model=List[Dict])
async def get_received_recommendations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer toutes les recommandations reçues."""
    recommendations = await PeerRecommendationService.get_user_recommendations(
        db, str(current_user.id)
    )
    return recommendations


# ==================== 10. PROGRESSION DE CARRIÈRE ====================

@router.get("/career-progression/dashboard", response_model=Dict)
async def get_career_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer le dashboard de progression de carrière complet."""
    dashboard = await CareerProgressionService.get_progression_dashboard(
        db, str(current_user.id)
    )
    return dashboard


@router.post("/career-progression/update", response_model=Dict)
async def update_career_progression(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mettre à jour la progression de carrière."""
    progression = await CareerProgressionService.update_progression(
        db, str(current_user.id)
    )
    
    return {
        "stage": progression.current_stage,
        "progress": progression.stage_progress_percentage,
        "next_milestone": progression.next_milestone,
        "message": "Progression mise à jour"
    }


# ==================== BULK/ADMIN ENDPOINTS ====================

@router.post("/admin/award-badge", response_model=Dict)
async def award_badge_to_user(
    user_id: str,
    badge_id: str,
    evidence: Dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """[Admin] Attribuer un badge à un utilisateur."""
    # Vérifier que l'utilisateur courant est admin
    role_val = getattr(current_user.user.role, 'value', current_user.user.role)
    if role_val != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    user_badge = await BadgeService.award_badge(db, user_id, badge_id, evidence)
    
    return {
        "badge_id": str(user_badge.id),
        "user_id": user_id,
        "message": "Badge attribué"
    }


@router.post("/admin/approve-loan", response_model=Dict)
async def approve_loan_request(
    loan_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """[Admin] Approuver un micro-crédit."""
    role_val = getattr(current_user.user.role, 'value', current_user.user.role)
    if role_val != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    loan = await MicroLoanService.approve_loan(db, loan_id, str(current_user.id))
    
    return {
        "loan_id": str(loan.id),
        "status": loan.status.value,
        "message": "Prêt approuvé"
    }
