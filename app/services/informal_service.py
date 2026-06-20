"""
Services métier pour le secteur informel.
Gère: Passeport, Portfolio, Badges, Mentoring, Trust Bonds, Formations, Micro-crédits
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from sqlalchemy import func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models.informal_models import (
    DigitalPassport, PeerReview, ProjectPortfolio, PortfolioFeedback,
    Badge, UserBadge, Mentorship, MentorshipSession, TrustBond, TrustBondClaim,
    TrainingCourse, CourseEnrollment, MicroLoan, LoanPayment,
    InformalSkillMapping, PeerRecommendation, CareerProgression,
    PassportStatus, BadgeCategory, MentorshipStatus, TrustBondStatus,
    LoanStatus, TrainingLevel
)
from ..models.database_models import User, UserProfile, PointTransaction, CandidateCategory
from ..services.llm_client import LLMClient
from ..services.ai_providers import EmbeddingProvider
from ..config import settings


# ==================== 1. PASSEPORT NUMÉRIQUE SERVICE ====================

class DigitalPassportService:
    """Service pour gérer les Passeports Numériques."""
    
    @staticmethod
    async def create_passport(db: Session, user_id: str) -> DigitalPassport:
        """Créer un nouveau Passeport Numérique."""
        passport = DigitalPassport(
            user_id=user_id,
            status=PassportStatus.CREATED,
            issue_date=datetime.now()
        )
        db.add(passport)
        db.commit()
        db.refresh(passport)
        return passport
    
    @staticmethod
    async def add_peer_review(
        db: Session, 
        passport_id: str, 
        reviewer_id: str,
        rating: int,
        comment: str,
        skills_validated: List[str],
        work_relationship: str
    ) -> PeerReview:
        """Ajouter une évaluation par un pair."""
        # Vérifier que le reviewer est vérifié (email/SMS)
        review = PeerReview(
            passport_id=passport_id,
            reviewer_id=reviewer_id,
            rating=rating,
            comment=comment,
            skills_validated=skills_validated,
            work_relationship=work_relationship,
            is_verified=True,  # À intégrer avec service SMS/Email
            verification_date=datetime.now()
        )
        db.add(review)
        
        # Mettre à jour le score de confiance du passeport
        passport = db.query(DigitalPassport).filter_by(id=passport_id).first()
        if passport:
            # Calcul du score: moyenne des ratings * nombre d'évaluations
            reviews = db.query(PeerReview).filter_by(passport_id=passport_id).all()
            avg_rating = sum([r.rating for r in reviews]) / len(reviews) if reviews else 0
            passport.trust_score = int((avg_rating / 5) * 100)
            passport.peer_validation_count = len(reviews)
            
            # Si 3+ reviews et score > 70 → passer à PEER_VALIDATED
            if passport.peer_validation_count >= 3 and passport.trust_score >= 70:
                passport.status = PassportStatus.PEER_VALIDATED
                passport.last_validation_date = datetime.now()
        
        db.add(review)
        db.commit()
        db.refresh(review)
        return review
    
    @staticmethod
    async def get_passport_progress(db: Session, user_id: str) -> Dict:
        """Récupérer la progression du Passeport."""
        passport = db.query(DigitalPassport).filter_by(user_id=user_id).first()
        if not passport:
            return None
        
        reviews = db.query(PeerReview).filter_by(passport_id=passport.id).all()
        
        return {
            "passport_id": str(passport.id),
            "status": passport.status.value,
            "trust_score": passport.trust_score,
            "peer_validation_count": passport.peer_validation_count,
            "verified_skills": passport.verified_skills or [],
            "reviews_count": len(reviews),
            "avg_rating": sum([r.rating for r in reviews]) / len(reviews) if reviews else 0,
            "is_gold": passport.status == PassportStatus.GOLD,
            "progress_to_gold": f"{passport.trust_score}%"
        }


# ==================== 2. PORTFOLIO SERVICE ====================

class PortfolioService:
    """Service pour gérer les portfolios de projets."""
    
    @staticmethod
    async def create_project(
        db: Session,
        user_id: str,
        title: str,
        description: str,
        category: str,
        skills_used: List[str],
        budget: int,
        result_description: str,
        media_urls: List[str],
        client_name: str,
        client_contact: str
    ) -> ProjectPortfolio:
        """Créer un nouveau projet dans le portfolio."""
        project = ProjectPortfolio(
            user_id=user_id,
            title=title,
            description=description,
            category=category,
            skills_used=skills_used,
            start_date=datetime.now(),
            end_date=datetime.now(),
            budget=budget,
            result_description=result_description,
            media_urls=media_urls,
            client_name=client_name,
            client_contact=client_contact
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return project
    
    @staticmethod
    async def verify_client_feedback(
        db: Session,
        project_id: str,
        client_feedback: str
    ) -> ProjectPortfolio:
        """Ajouter et vérifier le feedback client."""
        project = db.query(ProjectPortfolio).filter_by(id=project_id).first()
        if project:
            project.client_feedback = client_feedback
            project.is_client_verified = True
            db.commit()
            db.refresh(project)
        return project
    
    @staticmethod
    async def get_portfolio_stats(db: Session, user_id: str) -> Dict:
        """Récupérer les stats du portfolio."""
        projects = db.query(ProjectPortfolio).filter_by(user_id=user_id).all()
        
        total_budget = sum([p.budget or 0 for p in projects])
        avg_rating = 0
        if projects:
            feedbacks = []
            for p in projects:
                feedbacks.extend(db.query(PortfolioFeedback).filter_by(project_id=p.id).all())
            avg_rating = sum([f.rating for f in feedbacks if f.rating]) / len(feedbacks) if feedbacks else 0
        
        return {
            "total_projects": len(projects),
            "total_budget_managed": total_budget,
            "avg_client_rating": avg_rating,
            "verified_projects": sum([1 for p in projects if p.is_client_verified]),
            "projects": [
                {
                    "title": p.title,
                    "category": p.category,
                    "budget": p.budget,
                    "client_verified": p.is_client_verified,
                    "skills": p.skills_used
                }
                for p in projects
            ]
        }


# ==================== 3. BADGE & ACHIEVEMENT SERVICE ====================

class BadgeService:
    """Service pour gérer les badges et certificats."""
    
    @staticmethod
    async def award_badge(
        db: Session,
        user_id: str,
        badge_id: str,
        evidence: Dict
    ) -> UserBadge:
        """Attribuer un badge à un utilisateur."""
        user_badge = UserBadge(
            user_id=user_id,
            badge_id=badge_id,
            earned_at=datetime.now(),
            evidence=evidence
        )
        db.add(user_badge)
        
        # Ajouter des points bonus pour avoir obtenu un badge
        user_profile = db.query(UserProfile).filter_by(user_id=user_id).first()
        if user_profile:
            user_profile.points += 100  # 100 points par badge
            
            # Créer une transaction de points
            transaction = PointTransaction(
                advertiser_id=user_id,
                amount=100,
                reason="badge_earned"
            )
            db.add(transaction)
        
        db.commit()
        db.refresh(user_badge)
        return user_badge
    
    @staticmethod
    async def get_user_badges(db: Session, user_id: str) -> List[Dict]:
        """Récupérer tous les badges d'un utilisateur."""
        user_badges = db.query(UserBadge).filter_by(user_id=user_id).all()
        
        return [
            {
                "badge_name": ub.badge.name,
                "category": ub.badge.category.value,
                "icon_url": ub.badge.icon_url,
                "earned_at": ub.earned_at.isoformat(),
                "color": ub.badge.color_hex
            }
            for ub in user_badges
        ]
    
    @staticmethod
    async def check_badge_criteria(
        db: Session,
        user_id: str,
        badge_id: str
    ) -> bool:
        """Vérifier si l'utilisateur peut obtenir ce badge."""
        badge = db.query(Badge).filter_by(id=badge_id).first()
        if not badge:
            return False
        
        # Vérifier les critères (exemple: 5 peer reviews)
        criteria = badge.criteria
        if criteria.get("type") == "peer_reviews_count":
            passport = db.query(DigitalPassport).filter_by(user_id=user_id).first()
            if passport and passport.peer_validation_count >= criteria.get("value", 0):
                return True
        
        return False


# ==================== 4. MENTORING SERVICE ====================

class MentoringService:
    """Service pour gérer le mentorat et le parrainage."""
    
    @staticmethod
    async def create_mentorship_request(
        db: Session,
        mentor_id: str,
        apprentice_id: str,
        skill_focus: str,
        expected_end_date: datetime
    ) -> Mentorship:
        """Créer une demande de mentorat."""
        mentorship = Mentorship(
            mentor_id=mentor_id,
            apprentice_id=apprentice_id,
            skill_focus=skill_focus,
            status=MentorshipStatus.REQUESTED,
            expected_end_date=expected_end_date
        )
        db.add(mentorship)
        db.commit()
        db.refresh(mentorship)
        return mentorship
    
    @staticmethod
    async def accept_mentorship(
        db: Session,
        mentorship_id: str,
        start_date: datetime
    ) -> Mentorship:
        """Accepter une demande de mentorat."""
        mentorship = db.query(Mentorship).filter_by(id=mentorship_id).first()
        if mentorship:
            mentorship.status = MentorshipStatus.ACCEPTED
            mentorship.start_date = start_date
            db.commit()
            db.refresh(mentorship)
        return mentorship
    
    @staticmethod
    async def log_mentorship_session(
        db: Session,
        mentorship_id: str,
        topic: str,
        summary: str,
        duration_minutes: int
    ) -> MentorshipSession:
        """Enregistrer une session de mentorat."""
        session = MentorshipSession(
            mentorship_id=mentorship_id,
            session_date=datetime.now(),
            topic=topic,
            summary=summary,
            duration_minutes=duration_minutes,
            is_completed=True
        )
        db.add(session)
        
        # Mettre à jour le statut du mentorat si en cours
        mentorship = db.query(Mentorship).filter_by(id=mentorship_id).first()
        if mentorship and mentorship.status == MentorshipStatus.ACCEPTED:
            mentorship.status = MentorshipStatus.IN_PROGRESS
        
        db.commit()
        db.refresh(session)
        return session


# ==================== 5. TRUST BOND SERVICE ====================

class TrustBondService:
    """Service pour gérer la garantie de confiance."""
    
    @staticmethod
    async def create_trust_bond(
        db: Session,
        user_id: str,
        amount: int,
        expiration_date: datetime
    ) -> TrustBond:
        """Créer une garantie de confiance pour un candidat."""
        bond = TrustBond(
            user_id=user_id,
            amount=amount,
            status=TrustBondStatus.PENDING,
            issued_date=datetime.now(),
            expiration_date=expiration_date
        )
        db.add(bond)
        db.commit()
        db.refresh(bond)
        return bond
    
    @staticmethod
    async def validate_trust_bond(
        db: Session,
        bond_id: str,
        validator_id: str
    ) -> TrustBond:
        """Valider une garantie de confiance par un administrateur."""
        bond = db.query(TrustBond).filter_by(id=bond_id).first()
        if bond:
            bond.status = TrustBondStatus.ACTIVE
            bond.validated_by = validator_id
            bond.validation_date = datetime.now()
            db.commit()
            db.refresh(bond)
        return bond
    
    @staticmethod
    async def file_claim(
        db: Session,
        bond_id: str,
        claimant_id: str,
        reason: str,
        amount_claimed: int,
        evidence_urls: List[str]
    ) -> TrustBondClaim:
        """Déposer une réclamation contre la garantie."""
        claim = TrustBondClaim(
            bond_id=bond_id,
            claimant_id=claimant_id,
            reason=reason,
            amount_claimed=amount_claimed,
            evidence_urls=evidence_urls,
            status="pending",
            claim_date=datetime.now()
        )
        db.add(claim)
        
        # Mettre le bond en statut "claimed"
        bond = db.query(TrustBond).filter_by(id=bond_id).first()
        if bond:
            bond.status = TrustBondStatus.CLAIMED
        
        db.commit()
        db.refresh(claim)
        return claim


# ==================== 6. TRAINING SERVICE ====================

class TrainingService:
    """Service pour gérer les formations."""
    
    @staticmethod
    async def create_course(
        db: Session,
        title: str,
        description: str,
        category: str,
        level: str,
        instructor_id: str,
        duration_hours: int,
        cost: int = 0,
        start_date: datetime = None
    ) -> TrainingCourse:
        """Créer une nouvelle formation."""
        course = TrainingCourse(
            title=title,
            description=description,
            category=category,
            level=TrainingLevel(level),
            instructor_id=instructor_id,
            duration_hours=duration_hours,
            cost=cost,
            format="hybrid",
            start_date=start_date or datetime.now()
        )
        db.add(course)
        db.commit()
        db.refresh(course)
        return course
    
    @staticmethod
    async def enroll_user(
        db: Session,
        course_id: str,
        user_id: str
    ) -> CourseEnrollment:
        """Inscrire un utilisateur à une formation."""
        enrollment = CourseEnrollment(
            course_id=course_id,
            user_id=user_id,
            enrollment_date=datetime.now()
        )
        db.add(enrollment)
        
        # Ajouter des points d'inscription
        user_profile = db.query(UserProfile).filter_by(user_id=user_id).first()
        if user_profile:
            user_profile.points += 50
        
        db.commit()
        db.refresh(enrollment)
        return enrollment
    
    @staticmethod
    async def complete_course(
        db: Session,
        enrollment_id: str,
        final_score: int
    ) -> CourseEnrollment:
        """Marquer un cours comme complété."""
        enrollment = db.query(CourseEnrollment).filter_by(id=enrollment_id).first()
        if enrollment:
            enrollment.is_completed = True
            enrollment.completion_date = datetime.now()
            enrollment.final_score = final_score
            enrollment.is_certified = final_score >= 60
            enrollment.progress_percentage = 100
            
            # Ajouter des points de complétion
            user_profile = db.query(UserProfile).filter_by(user_id=enrollment.user_id).first()
            if user_profile and enrollment.is_certified:
                user_profile.points += 200
            
            db.commit()
            db.refresh(enrollment)
        
        return enrollment


# ==================== 7. MICRO-LOAN SERVICE ====================

class MicroLoanService:
    """Service pour gérer les micro-crédits."""
    
    @staticmethod
    async def request_loan(
        db: Session,
        user_id: str,
        loan_amount: int,
        purpose: str,
        description: str,
        duration_months: int,
        interest_rate: float = 10.0
    ) -> MicroLoan:
        """Demander un micro-crédit."""
        # Calculer les paramètres du prêt
        monthly_payment = int(loan_amount / duration_months * (1 + interest_rate / 100))
        due_date = datetime.now() + timedelta(days=30 * duration_months)
        
        loan = MicroLoan(
            user_id=user_id,
            loan_amount=loan_amount,
            purpose=purpose,
            description=description,
            duration_months=duration_months,
            interest_rate=interest_rate,
            monthly_payment=monthly_payment,
            status=LoanStatus.PENDING,
            request_date=datetime.now(),
            due_date=due_date
        )
        db.add(loan)
        db.commit()
        db.refresh(loan)
        return loan
    
    @staticmethod
    async def approve_loan(
        db: Session,
        loan_id: str,
        approver_id: str
    ) -> MicroLoan:
        """Approuver un micro-crédit."""
        loan = db.query(MicroLoan).filter_by(id=loan_id).first()
        if loan:
            loan.status = LoanStatus.APPROVED
            loan.approved_by = approver_id
            loan.approval_date = datetime.now()
            db.commit()
            db.refresh(loan)
        return loan
    
    @staticmethod
    async def disburse_loan(
        db: Session,
        loan_id: str
    ) -> MicroLoan:
        """Décaisser le prêt (transférer l'argent)."""
        loan = db.query(MicroLoan).filter_by(id=loan_id).first()
        if loan:
            loan.status = LoanStatus.ACTIVE
            loan.disbursement_date = datetime.now()
            db.commit()
            db.refresh(loan)
        return loan
    
    @staticmethod
    async def record_payment(
        db: Session,
        loan_id: str,
        amount: int,
        payment_method: str
    ) -> LoanPayment:
        """Enregistrer un paiement de prêt."""
        loan = db.query(MicroLoan).filter_by(id=loan_id).first()
        
        payment = LoanPayment(
            loan_id=loan_id,
            amount=amount,
            payment_date=datetime.now(),
            payment_method=payment_method
        )
        db.add(payment)
        
        if loan:
            loan.total_repaid += amount
            
            # Vérifier si le prêt est complètement remboursé
            if loan.total_repaid >= loan.loan_amount:
                loan.status = LoanStatus.COMPLETED
        
        db.commit()
        db.refresh(payment)
        return payment


# ==================== 8. SKILL MAPPING SERVICE (IA) ====================

class SkillMappingService:
    """Service pour mapper les compétences informelles → formelles via IA."""
    
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
    
    async def map_informal_skills(
        self,
        db: Session,
        user_id: str,
        informal_skill_description: str,
        informal_context: str
    ) -> InformalSkillMapping:
        """Mapper automatiquement une compétence informelle → compétences formelles."""
        
        # Prompt pour l'IA
        system_prompt = """Tu es un expert en capitalisation des compétences informelles.
        Analyse la compétence décrite et identifie les compétences formelles correspondantes.
        Retourne une liste des compétences formelles reconnues (format JSON).
        
        Exemple:
        Entrée: "J'ai réparé des moteurs de taxi pendant 8 ans"
        Sortie: ["Diagnostic moteur", "Réparation moteur", "Maintenance automobile", "Gestion d'outils techniques"]
        """
        
        user_message = f"""
        Compétence informelle: {informal_skill_description}
        Contexte: {informal_context}
        
        Quelles sont les compétences formelles correspondantes? Retourne une liste JSON.
        """
        
        try:
            # Appeler l'IA pour le mapping
            response = await self.llm_client.generate_json_response(system_prompt, user_message)
            mapped_skills = response.get("formal_skills", [])
            mapping_confidence = response.get("confidence", 0.7)
        except:
            mapped_skills = []
            mapping_confidence = 0.0
        
        # Créer l'enregistrement de mapping
        mapping = InformalSkillMapping(
            user_id=user_id,
            informal_skill_description=informal_skill_description,
            informal_context=informal_context,
            mapped_formal_skills=mapped_skills,
            mapping_confidence=mapping_confidence,
            llm_model_used="gemini-2.5-flash"
        )
        db.add(mapping)
        db.commit()
        db.refresh(mapping)
        return mapping


# ==================== 9. PEER RECOMMENDATION SERVICE ====================

class PeerRecommendationService:
    """Service pour gérer les recommandations entre pairs."""
    
    @staticmethod
    async def create_recommendation(
        db: Session,
        recommender_id: str,
        recommended_id: str,
        skills_recommended: List[str],
        reason: str,
        confidence_level: int,
        work_relationship: str
    ) -> PeerRecommendation:
        """Créer une recommandation par un pair."""
        recommendation = PeerRecommendation(
            recommender_id=recommender_id,
            recommended_id=recommended_id,
            skills_recommended=skills_recommended,
            reason=reason,
            confidence_level=confidence_level,
            work_relationship=work_relationship,
            is_verified=True,  # À intégrer avec service SMS/Email
            verification_date=datetime.now()
        )
        db.add(recommendation)
        db.commit()
        db.refresh(recommendation)
        return recommendation
    
    @staticmethod
    async def get_user_recommendations(
        db: Session,
        user_id: str
    ) -> List[Dict]:
        """Récupérer toutes les recommandations reçues."""
        recommendations = db.query(PeerRecommendation).filter_by(recommended_id=user_id).all()
        
        return [
            {
                "recommender_name": r.recommender.profile.first_name or "Anonyme",
                "skills": r.skills_recommended,
                "confidence": r.confidence_level,
                "reason": r.reason,
                "work_relationship": r.work_relationship,
                "created_at": r.created_at.isoformat()
            }
            for r in recommendations
        ]


# ==================== 10. CAREER PROGRESSION SERVICE ====================

class CareerProgressionService:
    """Service pour suivre la progression de carrière."""
    
    @staticmethod
    async def initialize_progression(
        db: Session,
        user_id: str
    ) -> CareerProgression:
        """Initialiser le suivi de progression de carrière."""
        # S'assurer que le user existe pour éviter une ForeignKeyViolation
        user_exists = db.query(User).filter(User.id == user_id).first()
        if not user_exists:
            raise ValueError(f"L'utilisateur avec l'ID {user_id} n'existe pas dans la table 'users'.")
            
        progression = CareerProgression(
            user_id=user_id,
            current_stage="pure_informal",
            stage_progress_percentage=0,
            milestones={
                "passport_created": False,
                "peer_reviews": 0,
                "courses_completed": 0,
                "projects_verified": 0
            }
        )
        db.add(progression)
        db.commit()
        db.refresh(progression)
        return progression
    
    @staticmethod
    async def update_progression(
        db: Session,
        user_id: str
    ) -> CareerProgression:
        """Mettre à jour la progression basée sur les actions."""
        progression = db.query(CareerProgression).filter_by(user_id=user_id).first()
        if not progression:
            return await CareerProgressionService.initialize_progression(db, user_id)
        
        # Récupérer les données
        passport = db.query(DigitalPassport).filter_by(user_id=user_id).first()
        projects = db.query(ProjectPortfolio).filter_by(user_id=user_id).all()
        enrollments = db.query(CourseEnrollment).filter_by(user_id=user_id).all()
        
        # Mettre à jour les jalons
        milestones = {
            "passport_created": passport is not None and passport.status != PassportStatus.CREATED,
            "peer_reviews": passport.peer_validation_count if passport else 0,
            "courses_completed": sum([1 for e in enrollments if e.is_completed]),
            "projects_verified": sum([1 for p in projects if p.is_client_verified])
        }
        
        # Déterminer l'étape
        if milestones["peer_reviews"] >= 3 and milestones["courses_completed"] >= 1:
            progression.current_stage = "semi_formal"
            progression.stage_progress_percentage = 65
            progression.next_milestone = "Obtenir un contrat formalisé"
        elif milestones["peer_reviews"] >= 3:
            progression.current_stage = "validated"
            progression.stage_progress_percentage = 40
            progression.next_milestone = "Suivre une formation"
        else:
            progression.current_stage = "pure_informal"
            progression.stage_progress_percentage = max(
                int(milestones["peer_reviews"] / 3 * 100),
                int(milestones["projects_verified"] / 2 * 30)
            )
            progression.next_milestone = "Obtenir au moins 3 évaluations de pairs"
        
        progression.milestones = milestones
        progression.updated_at = datetime.now()
        
        db.commit()
        db.refresh(progression)
        return progression
    
    @staticmethod
    async def get_progression_dashboard(
        db: Session,
        user_id: str
    ) -> Dict:
        """Récupérer le dashboard de progression complète."""
        progression = db.query(CareerProgression).filter_by(user_id=user_id).first()
        
        if not progression:
            await CareerProgressionService.initialize_progression(db, user_id)
            progression = db.query(CareerProgression).filter_by(user_id=user_id).first()
        
        # Récupérer tous les éléments
        passport = db.query(DigitalPassport).filter_by(user_id=user_id).first()
        projects = db.query(ProjectPortfolio).filter_by(user_id=user_id).all()
        enrollments = db.query(CourseEnrollment).filter_by(user_id=user_id).all()
        badges = db.query(UserBadge).filter_by(user_id=user_id).all()
        recommendations = db.query(PeerRecommendation).filter_by(recommended_id=user_id).all()
        
        return {
            "current_stage": progression.current_stage,
            "stage_progress": progression.stage_progress_percentage,
            "next_milestone": progression.next_milestone,
            "stats": {
                "passport_created": passport is not None,
                "passport_status": passport.status.value if passport else None,
                "passport_trust_score": passport.trust_score if passport else 0,
                "projects_count": len(projects),
                "projects_verified": sum([1 for p in projects if p.is_client_verified]),
                "courses_enrolled": len(enrollments),
                "courses_completed": sum([1 for e in enrollments if e.is_completed]),
                "badges_earned": len(badges),
                "peer_recommendations": len(recommendations),
            },
            "milestones": progression.milestones
        }
