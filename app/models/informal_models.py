"""
Modèles SQLAlchemy spécifiques aux candidats du secteur informel.
Inclut: Passeport numérique, Portfolio, Mentoring, Badges, Micro-crédits, etc.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, ARRAY, JSON, ForeignKey, UniqueConstraint, Index, Enum as SQLAlchemyEnum
import enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from datetime import datetime

from ..database import Base


# ==================== ENUM FOR INFORMAL SPACE ====================

class PassportStatus(str, enum.Enum):
    """États du Passeport Numérique."""
    CREATED = "created"  # Passeport créé
    PEER_VALIDATED = "peer_validated"  # Validé par au moins 3 pairs
    VERIFIED = "verified"  # Vérifié par admin/expert
    GOLD = "gold"  # Statut or (confiance max)


class BadgeCategory(str, enum.Enum):
    """Catégories de badges/certificats."""
    SKILL = "skill"  # Compétence validée
    PROJECT = "project"  # Projet réalisé
    COURSE = "course"  # Formation suivie
    PEER_REVIEW = "peer_review"  # Évaluations pairs positives
    WORK_HISTORY = "work_history"  # Historique de travail vérifié


class MentorshipStatus(str, enum.Enum):
    """États du mentorat."""
    REQUESTED = "requested"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TrustBondStatus(str, enum.Enum):
    """États de la garantie de confiance."""
    PENDING = "pending"  # En attente de validation
    ACTIVE = "active"  # Valide et couvrant
    CLAIMED = "claimed"  # Réclamation en cours
    RESOLVED = "resolved"  # Résolu (conforme ou compensé)
    EXPIRED = "expired"


class TrainingLevel(str, enum.Enum):
    """Niveaux de formation."""
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class LoanStatus(str, enum.Enum):
    """États des micro-crédits."""
    PENDING = "pending"  # En attente d'approbation
    APPROVED = "approved"  # Approuvé
    ACTIVE = "active"  # Actif (décaissé)
    REPAYMENT = "repayment"  # En remboursement
    COMPLETED = "completed"  # Remboursé
    DEFAULT = "default"  # En défaut


# ==================== 1. PASSEPORT NUMÉRIQUE ====================

class DigitalPassport(Base):
    """Passeport Numérique de Compétences pour candidats informels.
    
    Fonctionnalités:
    - Validé par pairs (collègues, anciens clients)
    - Points de confiance cumulatifs
    - Historique d'évaluations
    - Progression vers statut OR
    """
    __tablename__ = "digital_passports"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    
    # État du passeport
    status = Column(
        SQLAlchemyEnum(PassportStatus, name="passport_status_enum", create_type=True, values_callable=lambda x: [e.value for e in x]),
        default=PassportStatus.CREATED
    )
    
    # Points de confiance
    trust_score = Column(Integer, default=0)  # 0-100
    peer_validation_count = Column(Integer, default=0)  # Nombre de pairs qui ont validé
    verification_count = Column(Integer, default=0)  # Nombre d'experts qui ont vérifié
    
    # Documents justificatifs
    supporting_documents = Column(ARRAY(String))  # URLs vers documents
    verified_skills = Column(ARRAY(String))  # Compétences vérifiées
    verified_experience_years = Column(Integer, default=0)
    
    # Métadonnées
    issue_date = Column(DateTime, default=func.now())
    last_validation_date = Column(DateTime)
    expiration_date = Column(DateTime, nullable=True)  # Null = n'expire pas
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relations
    user = relationship("User", backref="digital_passport")
    peer_reviews = relationship("PeerReview", back_populates="passport", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_passport_user', 'user_id'),
        Index('idx_passport_status', 'status'),
        Index('idx_passport_trust_score', 'trust_score'),
    )


class PeerReview(Base):
    """Évaluations par les pairs du travail/compétences.
    
    Validé par:
    - Anciens collègues
    - Clients/recruteurs antérieurs
    - Pairs du même secteur
    """
    __tablename__ = "peer_reviews"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    passport_id = Column(UUID(as_uuid=True), ForeignKey("digital_passports.id", ondelete="CASCADE"), nullable=False)
    reviewer_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Évaluation
    rating = Column(Integer, nullable=False)  # 1-5 stars
    comment = Column(Text)
    skills_validated = Column(ARRAY(String))  # Quelles compétences ont été validées
    work_relationship = Column(String(100))  # "colleague", "client", "supervisor"
    
    # Vérification
    is_verified = Column(Boolean, default=False)  # Vérification email/SMS du reviewer
    verification_date = Column(DateTime)
    
    created_at = Column(DateTime, default=func.now())
    
    # Relations
    passport = relationship("DigitalPassport", back_populates="peer_reviews")
    reviewer = relationship("User", foreign_keys=[reviewer_id])
    
    __table_args__ = (
        UniqueConstraint('passport_id', 'reviewer_id', name='uq_passport_reviewer'),
        Index('idx_peer_reviews_passport', 'passport_id'),
        Index('idx_peer_reviews_reviewer', 'reviewer_id'),
        Index('idx_peer_reviews_rating', 'rating'),
    )


# ==================== 2. PORTFOLIO DE PROJETS ====================

class ProjectPortfolio(Base):
    """Portfolio de projets réalisés par candidats informels.
    
    Chaque projet:
    - Titre, description
    - Compétences utilisées
    - Dates de réalisation
    - Photos/vidéos
    - Résultats mesurables
    - Feedback clients
    """
    __tablename__ = "project_portfolios"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Infos projet
    title = Column(String(255), nullable=False)
    description = Column(Text)
    category = Column(String(100))  # "construction", "menuiserie", "mécanique", etc.
    
    # Compétences utilisées
    skills_used = Column(ARRAY(String))
    
    # Dates
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    
    # Résultats
    budget = Column(Integer)  # En CFA
    result_description = Column(Text)  # Qu'est-ce qui a été livré?
    metrics = Column(JSON)  # {duration_days, budget_respected, client_satisfaction, ...}
    
    # Média
    media_urls = Column(ARRAY(String))  # Photos avant/après, vidéos
    
    # Vérification client
    client_name = Column(String(255))
    client_contact = Column(String(255))
    client_feedback = Column(Text)
    is_client_verified = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relations
    user = relationship("User", backref="projects")
    portfolio_feedbacks = relationship("PortfolioFeedback", back_populates="project", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_project_portfolio_user', 'user_id'),
        Index('idx_project_portfolio_category', 'category'),
        Index('idx_project_portfolio_start_date', 'start_date'),
    )


class PortfolioFeedback(Base):
    """Feedbacks sur les projets du portfolio."""
    __tablename__ = "portfolio_feedbacks"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("project_portfolios.id", ondelete="CASCADE"), nullable=False)
    reviewer_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    rating = Column(Integer)  # 1-5
    comment = Column(Text)
    created_at = Column(DateTime, default=func.now())
    
    # Relations
    project = relationship("ProjectPortfolio", back_populates="portfolio_feedbacks")
    reviewer = relationship("User", foreign_keys=[reviewer_id])


# ==================== 3. SYSTÈME DE BADGES/CERTIFICATS ====================

class Badge(Base):
    """Catalogues de badges/certificats disponibles.
    
    Exemples:
    - "Compétence vérifiée: Menuiserie"
    - "5 projets réussis"
    - "100 heures de travail formalisé"
    - "Formation suivie: Électricité sécurisée"
    """
    __tablename__ = "badges"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Badge info
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text)
    category = Column(
        SQLAlchemyEnum(BadgeCategory, name="badge_category_enum", create_type=True, values_callable=lambda x: [e.value for e in x]),
        nullable=False
    )
    
    # Médaille
    icon_url = Column(String(500))  # URL de l'image
    color_hex = Column(String(7))  # Couleur du badge
    
    # Critères d'obtention
    criteria = Column(JSON)  # {type: "peer_reviews_count", value: 5, ...}
    
    created_at = Column(DateTime, default=func.now())
    
    # Relations
    user_badges = relationship("UserBadge", back_populates="badge", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_badge_name', 'name'),
        Index('idx_badge_category', 'category'),
    )


class UserBadge(Base):
    """Badges obtenus par les utilisateurs."""
    __tablename__ = "user_badges"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    badge_id = Column(UUID(as_uuid=True), ForeignKey("badges.id", ondelete="CASCADE"), nullable=False)
    
    earned_at = Column(DateTime, default=func.now())
    evidence = Column(JSON)  # Preuve d'obtention (id de peer review, projet, etc.)
    
    # Relations
    user = relationship("User", backref="badges")
    badge = relationship("Badge", back_populates="user_badges")
    
    __table_args__ = (
        UniqueConstraint('user_id', 'badge_id', name='uq_user_badge'),
        Index('idx_user_badges_user', 'user_id'),
        Index('idx_user_badges_badge', 'badge_id'),
    )


# ==================== 4. SYSTÈME DE MENTORING/PARRAINAGE ====================

class Mentorship(Base):
    """Programmes de mentorat: senior → junior/débutant.
    
    - Mentor: Expert du métier qui guide
    - Apprenti: Jeune/débutant qui veut apprendre
    - Sessions de conseil
    - Progression suivie
    """
    __tablename__ = "mentorships"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mentor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    apprentice_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Infos mentorat
    skill_focus = Column(String(255))  # Compétence principale à transférer
    status = Column(
        SQLAlchemyEnum(MentorshipStatus, name="mentorship_status_enum", create_type=True, values_callable=lambda x: [e.value for e in x]),
        default=MentorshipStatus.REQUESTED
    )
    
    # Durée
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    expected_end_date = Column(DateTime)
    
    # Suivi
    progress_notes = Column(ARRAY(Text))  # Notes de progression
    is_mentor_verified = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relations
    mentor = relationship("User", foreign_keys=[mentor_id], backref="mentorships_as_mentor")
    apprentice = relationship("User", foreign_keys=[apprentice_id], backref="mentorships_as_apprentice")
    sessions = relationship("MentorshipSession", back_populates="mentorship", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_mentorship_mentor', 'mentor_id'),
        Index('idx_mentorship_apprentice', 'apprentice_id'),
        Index('idx_mentorship_status', 'status'),
    )


class MentorshipSession(Base):
    """Sessions de mentorat individuelles."""
    __tablename__ = "mentorship_sessions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mentorship_id = Column(UUID(as_uuid=True), ForeignKey("mentorships.id", ondelete="CASCADE"), nullable=False)
    
    # Infos session
    session_date = Column(DateTime)
    duration_minutes = Column(Integer)
    topic = Column(String(255))  # Sujet de la session
    
    # Contenu
    summary = Column(Text)  # Ce qui a été couvert
    feedback_from_mentor = Column(Text)
    feedback_from_apprentice = Column(Text)
    
    # Suivi
    is_completed = Column(Boolean, default=False)
    rating_by_apprentice = Column(Integer)  # 1-5 stars
    
    created_at = Column(DateTime, default=func.now())
    
    # Relations
    mentorship = relationship("Mentorship", back_populates="sessions")
    
    __table_args__ = (
        Index('idx_session_mentorship', 'mentorship_id'),
        Index('idx_session_date', 'session_date'),
    )


# ==================== 5. GARANTIE DE CONFIANCE (TRUST BOND) ====================

class TrustBond(Base):
    """Garantie de confiance: assurance/caution pour candidats informels.
    
    Problème: Employeur craint de recruter quelqu'un sans CNPS/documents
    Solution: Fonds d'assurance collecte → compensation en cas de problème
    """
    __tablename__ = "trust_bonds"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Bond info
    amount = Column(Integer, nullable=False)  # Montant en CFA (ex: 500,000)
    status = Column(
        SQLAlchemyEnum(TrustBondStatus, name="trust_bond_status_enum", create_type=True, values_callable=lambda x: [e.value for e in x]),
        default=TrustBondStatus.PENDING
    )
    
    # Validation
    validated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # Admin ou expert
    validation_date = Column(DateTime)
    
    # Réclamations
    claim_history = Column(JSON)  # Historique des réclamations/paiements
    total_claimed = Column(Integer, default=0)
    
    # Durée
    issued_date = Column(DateTime, default=func.now())
    expiration_date = Column(DateTime)  # Renouvellement annuel?
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relations
    user = relationship("User", backref="trust_bonds")
    validator = relationship("User", foreign_keys=[validated_by])
    claims = relationship("TrustBondClaim", back_populates="bond", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_trust_bond_user', 'user_id'),
        Index('idx_trust_bond_status', 'status'),
    )


class TrustBondClaim(Base):
    """Réclamations contre la garantie de confiance."""
    __tablename__ = "trust_bond_claims"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bond_id = Column(UUID(as_uuid=True), ForeignKey("trust_bonds.id", ondelete="CASCADE"), nullable=False)
    
    # Réclamation
    claimant_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reason = Column(String(255))  # "non-execution", "poor_quality", "abandonment"
    description = Column(Text)
    amount_claimed = Column(Integer)
    
    # Preuves
    evidence_urls = Column(ARRAY(String))  # Documents justificatifs
    
    # Processus
    status = Column(String(50))  # "pending", "investigating", "approved", "rejected", "paid"
    investigation_notes = Column(Text)
    approved_amount = Column(Integer)
    
    # Dates
    claim_date = Column(DateTime, default=func.now())
    investigation_started = Column(DateTime)
    resolved_date = Column(DateTime)
    
    # Relations
    bond = relationship("TrustBond", back_populates="claims")
    claimant = relationship("User", foreign_keys=[claimant_id])
    
    __table_args__ = (
        Index('idx_claim_bond', 'bond_id'),
        Index('idx_claim_claimant', 'claimant_id'),
    )


# ==================== 6. FORMATIONS ACCESSIBLES ====================

class TrainingCourse(Base):
    """Formations professionnelles accessibles aux candidats informels.
    
    - Gratuite ou micro-financement
    - Adaptée au contexte sénégalais
    - Certification reconnue
    """
    __tablename__ = "training_courses"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Infos cours
    title = Column(String(255), nullable=False)
    description = Column(Text)
    category = Column(String(100))  # "construction", "informatique", "commerce", etc.
    level = Column(
        SQLAlchemyEnum(TrainingLevel, name="training_level_enum", create_type=True, values_callable=lambda x: [e.value for e in x]),
        default=TrainingLevel.BEGINNER
    )
    
    # Instructeur
    instructor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Durée et accès
    duration_hours = Column(Integer)
    format = Column(String(50))  # "online", "in_person", "hybrid"
    location = Column(String(255))  # Pour in_person
    
    # Coût
    cost = Column(Integer, default=0)  # En CFA (0 = gratuit)
    cost_currency = Column(String(3), default="XOF")
    
    # Contenu
    content_modules = Column(ARRAY(String))  # Chapitres/modules
    learning_outcomes = Column(ARRAY(String))  # Compétences acquises
    
    # Dates
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    max_participants = Column(Integer)
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relations
    instructor = relationship("User", foreign_keys=[instructor_id])
    enrollments = relationship("CourseEnrollment", back_populates="course", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_course_category', 'category'),
        Index('idx_course_level', 'level'),
        Index('idx_course_start_date', 'start_date'),
    )


class CourseEnrollment(Base):
    """Inscriptions aux formations."""
    __tablename__ = "course_enrollments"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(UUID(as_uuid=True), ForeignKey("training_courses.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Suivi
    enrollment_date = Column(DateTime, default=func.now())
    completion_date = Column(DateTime)
    is_completed = Column(Boolean, default=False)
    progress_percentage = Column(Integer, default=0)
    
    # Résultat
    final_score = Column(Integer)  # 0-100
    certificate_url = Column(String(500))
    is_certified = Column(Boolean, default=False)
    
    # Relations
    course = relationship("TrainingCourse", back_populates="enrollments")
    user = relationship("User", backref="training_enrollments")
    
    __table_args__ = (
        UniqueConstraint('course_id', 'user_id', name='uq_course_user_enrollment'),
        Index('idx_enrollment_course', 'course_id'),
        Index('idx_enrollment_user', 'user_id'),
        Index('idx_enrollment_status', 'is_completed'),
    )


# ==================== 7. MICRO-CRÉDITS/FINANCEMENT ====================

class MicroLoan(Base):
    """Micro-crédits pour candidats informels.
    
    Financements pour:
    - Outils de travail
    - Formation professionnelle
    - Capital de démarrage
    """
    __tablename__ = "micro_loans"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Prêt
    loan_amount = Column(Integer, nullable=False)  # Montant en CFA
    loan_currency = Column(String(3), default="XOF")
    purpose = Column(String(255))  # "tools", "training", "business_startup"
    description = Column(Text)
    
    # Termes
    interest_rate = Column(Float)  # En %
    duration_months = Column(Integer)
    monthly_payment = Column(Integer)
    
    # États
    status = Column(
        SQLAlchemyEnum(LoanStatus, name="loan_status_enum", create_type=True, values_callable=lambda x: [e.value for e in x]),
        default=LoanStatus.PENDING
    )
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approval_date = Column(DateTime)
    
    # Dates clés
    request_date = Column(DateTime, default=func.now())
    disbursement_date = Column(DateTime)  # Quand le prêt a été donné
    due_date = Column(DateTime)
    
    # Remboursement
    total_repaid = Column(Integer, default=0)
    repayment_plan = Column(JSON)  # [{date: ..., amount: ..., status: ...}]
    
    # Garanties
    collateral_description = Column(Text)  # Qu'est-ce qui garantit le prêt
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relations
    user = relationship("User", backref="micro_loans")
    approver = relationship("User", foreign_keys=[approved_by])
    payments = relationship("LoanPayment", back_populates="loan", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_loan_user', 'user_id'),
        Index('idx_loan_status', 'status'),
        Index('idx_loan_request_date', 'request_date'),
    )


class LoanPayment(Base):
    """Paiements des micro-crédits."""
    __tablename__ = "loan_payments"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id = Column(UUID(as_uuid=True), ForeignKey("micro_loans.id", ondelete="CASCADE"), nullable=False)
    
    # Paiement
    amount = Column(Integer, nullable=False)
    payment_date = Column(DateTime, default=func.now())
    due_date = Column(DateTime)
    is_late = Column(Boolean, default=False)
    days_late = Column(Integer, default=0)
    
    # Méthode
    payment_method = Column(String(50))  # "mobile_money", "bank_transfer", "cash"
    reference = Column(String(255))  # N° de transaction
    
    # Relations
    loan = relationship("MicroLoan", back_populates="payments")
    
    __table_args__ = (
        Index('idx_payment_loan', 'loan_id'),
        Index('idx_payment_date', 'payment_date'),
    )


# ==================== 8. SKILL MAPPING: INFORMEL → FORMEL ====================

class InformalSkillMapping(Base):
    """Mapping automatique: compétences informelles → compétences formelles.
    
    Exemple:
    - "Je sais réparer des motos" → "Mécanique automobile" + "Diagnostic technique"
    - "J'ai construit 50 maisons" → "Gestion de projet" + "Supervision d'équipe"
    """
    __tablename__ = "informal_skill_mappings"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Source: compétence informelle
    informal_skill_description = Column(Text, nullable=False)
    informal_context = Column(Text)  # Contexte (ex: "5 ans d'expérience comme apprenti")
    
    # Mapping: compétences formelles correspondantes
    mapped_formal_skills = Column(ARRAY(String))  # IDs de CompetenceReferentiel
    mapping_confidence = Column(Float)  # 0-1 (certitude du mapping)
    
    # Validation
    is_validated = Column(Boolean, default=False)
    validated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    validation_date = Column(DateTime)
    
    # IA tracing
    llm_model_used = Column(String(100))  # Quel modèle a fait le mapping
    mapping_reasoning = Column(Text)  # Explication du mapping
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relations
    user = relationship("User", backref="skill_mappings")
    validator = relationship("User", foreign_keys=[validated_by])
    
    __table_args__ = (
        Index('idx_skill_mapping_user', 'user_id'),
        Index('idx_skill_mapping_confidence', 'mapping_confidence'),
    )


# ==================== 9. RECOMMANDATIONS PAR PAIRS ====================

class PeerRecommendation(Base):
    """Recommandations entre candidats (réseau).
    
    "Je recommande X pour des missions de [compétence] car..."
    Crée un réseau de confiance et facilite les recommandations par bouche à oreille.
    """
    __tablename__ = "peer_recommendations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recommender_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    recommended_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Recommandation
    skills_recommended = Column(ARRAY(String))  # Compétences pour lesquelles X est recommandé
    reason = Column(Text)  # Pourquoi recommandez-vous X?
    confidence_level = Column(Integer)  # 1-5
    work_relationship = Column(String(100))  # "colleague", "client", "mentor"
    
    # Vérification
    is_verified = Column(Boolean, default=False)
    verification_date = Column(DateTime)
    
    # Impact
    recommendation_count = Column(Integer, default=0)  # Combien de fois utilisée
    success_stories = Column(ARRAY(Text))  # Projets ayant résulté de cette recommandation
    
    created_at = Column(DateTime, default=func.now())
    
    # Relations
    recommender = relationship("User", foreign_keys=[recommender_id], backref="peer_recommendations_given")
    recommended = relationship("User", foreign_keys=[recommended_id], backref="peer_recommendations_received")
    
    __table_args__ = (
        Index('idx_recommendation_recommender', 'recommender_id'),
        Index('idx_recommendation_recommended', 'recommended_id'),
        Index('idx_recommendation_confidence', 'confidence_level'),
    )


# ==================== 10. CAREER PROGRESSION ====================

class CareerProgression(Base):
    """Suivi de la progression de carrière pour candidats informels.
    
    Étapes:
    1. Informel pur (sans documents)
    2. Informel validé (Passeport + pairs)
    3. Semi-formel (formations suivies)
    4. Formel (contrat, CNPS)
    """
    __tablename__ = "career_progressions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    
    # Étape actuelle
    current_stage = Column(String(50))  # "pure_informal", "validated", "semi_formal", "formal"
    stage_progress_percentage = Column(Integer, default=0)  # Progression dans l'étape actuelle
    
    # Jalons
    milestones = Column(JSON)  # {passport_created, peer_reviews: 3, courses_completed: 2, ...}
    
    # Historique
    stage_history = Column(JSON)  # [{stage: "pure_informal", date: ...}, ...]
    
    # Objectifs
    next_milestone = Column(String(255))  # Prochaine étape recommandée
    recommended_actions = Column(ARRAY(String))  # Actions pour progresser
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relations
    user = relationship("User", backref="career_progression", uselist=False)
    
    __table_args__ = (
        Index('idx_career_user', 'user_id'),
        Index('idx_career_stage', 'current_stage'),
    )
