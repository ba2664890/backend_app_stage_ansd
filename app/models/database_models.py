"""
Modèles SQLAlchemy pour la base de données.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, ARRAY, JSON, ForeignKey, UniqueConstraint, Index, Enum as SQLAlchemyEnum
import enum
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey, func, event
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geography


from ..database import Base

# COPIEZ-COLLEZ CES CLASSES CORRIGÉES :

class OffreEmploiBrute(Base):
    __tablename__ = "offres_emploi_brutes"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    spider_source = Column(String(50), nullable=False)
    original_id = Column(String(255), nullable=False)
    title = Column(Text, nullable=False)
    url = Column(Text)
    location = Column(String(255))
    company_name = Column(String(255))
    posted_date = Column(DateTime)
    source = Column(String(100))
    description = Column(Text)
    contract_type = Column(String(50))
    salary = Column(String(100))
    category = Column(String(100))
    sector = Column(String(100))
    experience_level = Column(String(255))
    education_level = Column(String(255))
    nb_positions = Column(Integer, default=1)
    expiration_date = Column(DateTime)
    
    # Nouveaux champs pour la plateforme
    remote_type = Column(String(50)) # Onsite, Hybrid, Remote
    is_urgent = Column(Boolean, default=False)
    languages = Column(ARRAY(String))
    benefits = Column(ARRAY(String))
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Liens pour les offres postées via la plateforme
    recruiter_id = Column(UUID(as_uuid=True), ForeignKey("recruiters.id", ondelete="SET NULL"), nullable=True)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    contributor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Relations CORRIGÉES
    recruiter = relationship("Recruiter", backref="posted_jobs")
    contributor = relationship("User", backref="contributed_jobs", foreign_keys=[contributor_id])
    enrichie = relationship("OffreEmploiEnrichie", back_populates="offre_brute", uselist=False)
    admin_boundary_id = Column(Integer, ForeignKey("senegal_admin_boundaries.id"))
    admin_boundary = relationship(
        "SenegalAdminBoundary", 
        back_populates="offres_brutes",
        foreign_keys=[admin_boundary_id]
    )

    saved_by_users = relationship(
        "UserSavedJob",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="dynamic"
    )

class OffreEmploiEnrichie(Base):
    __tablename__ = "offres_emploi_enrichies"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    offre_id = Column(UUID(as_uuid=True), ForeignKey('offres_emploi_brutes.id'), nullable=False, unique=True)
    
    # Informations extraites par NLP
    extracted_salary_min = Column(Integer)
    extracted_salary_max = Column(Integer)
    extracted_salary_currency = Column(String(10))
    extracted_contract_type = Column(String(50))
    extracted_experience_years = Column(Integer)
    extracted_skills = Column(ARRAY(String))
    extracted_sector = Column(String(100))
    extracted_job_category = Column(String(100))
    extracted_job_title = Column(String(255))
    
    # Analyse sémantique
    sentiment_score = Column(Float)
    key_phrases = Column(ARRAY(String))
    
    # Classification
    job_level = Column(String(50))
    job_type = Column(String(50))
    
    # Métadonnées
    processing_version = Column(String(20))
    processed_at = Column(DateTime, default=func.now())
    confidence_score = Column(Float)
    
    # Relations CORRIGÉES
    offre_brute = relationship("OffreEmploiBrute", back_populates="enrichie")
    recommendations = relationship("JobRecommendation", back_populates="job")
    
    # ✅ Colonne sans relation pour éviter l'ambigüité
    boundary_id = Column(Integer, ForeignKey("senegal_admin_boundaries.id"), index=True)

class SenegalAdminBoundary(Base):
    __tablename__ = "senegal_admin_boundaries"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    level = Column(String, nullable=False, index=True)
    parent_name = Column(String, nullable=True)
    geojson = Column(JSON, nullable=False)
    centroid = Column(Geography("POINT", srid=4326), nullable=True)
    offer_count = Column(Integer, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ✅ Relation UNIQUE et CLAIRE
    offres_brutes = relationship(
        "OffreEmploiBrute", 
        back_populates="admin_boundary",
        foreign_keys="OffreEmploiBrute.admin_boundary_id"
    )

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    RECRUITER = "recruiter"
    HR_MANAGER = "hr_manager"
    CANDIDATE = "candidate"
    GOVERNMENT = "government"
    ADVERTISER = "advertiser"

class CandidateCategory(str, enum.Enum):
    PUPIL = "pupil"
    STUDENT_PRO = "student_pro"
    INFORMAL = "informal"

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    verification_token = Column(String(255))
    reset_password_token = Column(String(255))
    reset_password_expires = Column(DateTime)
    last_login = Column(DateTime)
    
    # Champ role avec Enum PostgreSQL
    role = Column(
        SQLAlchemyEnum(UserRole, name="user_role_enum", create_type=True, values_callable=lambda x: [e.value for e in x]), 
        default=UserRole.CANDIDATE
    )
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # 1-to-1 : un utilisateur a zéro ou un profil
    profile = relationship(
        "UserProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )

    saved_jobs = relationship(
        "UserSavedJob",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="dynamic"  # Pour de meilleures performances avec de grands ensembles
    )
    
    # Relation avec Recruiter (1-to-1 optionnel)
    recruiter_profile = relationship(
        "Recruiter",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )

    advertiser_profile = relationship(
        "AdvertiserProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )



class UserProfile(Base):
    __tablename__ = "user_profiles"

    # PK locale
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # FK vers users (obligatoire pour SQLAlchemy)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True          # <- garantit la cardinalité 1-to-1
    )

    # --- champs déjà présents ---
    
    phone = Column(String(50))
    first_name = Column(String(100))
    last_name = Column(String(100))
    location = Column(String(255))
    category = Column(
        SQLAlchemyEnum(
            CandidateCategory, 
            name="candidate_category_enum", 
            create_type=True,
            values_callable=lambda x: [e.value for e in x]
        ), 
        default=CandidateCategory.STUDENT_PRO
    )
    current_title = Column(String(255))
    experience_years = Column(Integer)
    education_level = Column(String(100))
    skills = Column(ARRAY(String))
    preferred_contract_type = Column(ARRAY(String))
    preferred_salary_min = Column(Integer)
    preferred_salary_max = Column(Integer)
    cv_url = Column(Text)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    verification_token = Column(String(255))
    reset_password_token = Column(String(255))
    reset_password_expires = Column(DateTime)
    last_login = Column(DateTime)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # --- Lien Administratif ---
    admin_boundary_id = Column(Integer, ForeignKey("senegal_admin_boundaries.id"), nullable=True, index=True)

    # relations
    user = relationship("User", back_populates="profile")
    recommendations = relationship("JobRecommendation", back_populates="user")
    admin_boundary = relationship("SenegalAdminBoundary")

    __table_args__ = (
        Index('idx_user_profiles_skills', 'skills', postgresql_using='gin'),
        Index('idx_user_profiles_verification_token', 'verification_token'),
        Index('idx_user_profiles_reset_token', 'reset_password_token'),
        Index('idx_user_profiles_is_active', 'is_active'),
        Index('idx_user_profiles_user_id', 'user_id'),   # utile aussi
    )






class JobRecommendation(Base):
    """Modèle pour les recommandations d'emploi."""
    
    __tablename__ = "job_recommendations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('user_profiles.id'), nullable=False)
    job_id = Column(UUID(as_uuid=True), ForeignKey('offres_emploi_enrichies.id'), nullable=False)
    match_score = Column(Float, nullable=False)
    match_reasons = Column(ARRAY(String))
    is_viewed = Column(Boolean, default=False)
    is_applied = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    
    # Relations
    user = relationship("UserProfile", back_populates="recommendations")
    job = relationship("OffreEmploiEnrichie", back_populates="recommendations")
    
    # Index
    __table_args__ = (
        Index('idx_recommendations_user', 'user_id'),
        Index('idx_recommendations_job', 'job_id'),
        Index('idx_recommendations_score', 'match_score'),
    )

class JobStatistics(Base):
    """Modèle pour les statistiques calculées."""
    
    __tablename__ = "job_statistics"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    metric_name = Column(String(100), nullable=False)
    metric_value = Column(JSON, nullable=False)
    period_start = Column(DateTime)
    period_end = Column(DateTime)
    category = Column(String(100))
    location = Column(String(100))
    created_at = Column(DateTime, default=func.now())
    
    # Index
    __table_args__ = (
        Index('idx_job_statistics_period', 'period_start', 'period_end'),
        Index('idx_job_statistics_category', 'category'),
    )

class CompetenceReferentiel(Base):
    """Modèle pour le référentiel des compétences."""
    
    __tablename__ = "competences_referentiel"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    competence_name = Column(String(255), unique=True, nullable=False)
    category = Column(String(100))
    subcategory = Column(String(100))
    description = Column(Text)
    created_at = Column(DateTime, default=func.now())
    
    # Index
    __table_args__ = (
        Index('idx_competences_category', 'category'),
        Index('idx_competences_name', 'competence_name'),
    )

# ==================== MODULE 1: COMPANIES & RECRUITERS ====================

class Company(Base):
    """Modèle pour les entreprises."""
    
    __tablename__ = "companies"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)
    sector = Column(String(100))
    size = Column(String(50))  # PME, ETI, GE
    location = Column(String(255))
    description = Column(Text)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # --- Lien Administratif ---
    admin_boundary_id = Column(Integer, ForeignKey("senegal_admin_boundaries.id"), nullable=True, index=True)

    # Relations
    recruiters = relationship("Recruiter", back_populates="company", cascade="all, delete-orphan")
    skill_needs = relationship("CompanySkillNeed", back_populates="company", cascade="all, delete-orphan")
    admin_boundary = relationship("SenegalAdminBoundary")
    
    # Index
    __table_args__ = (
        Index('idx_companies_name', 'name'),
        Index('idx_companies_sector', 'sector'),
        Index('idx_companies_is_verified', 'is_verified'),
    )

class Recruiter(Base):
    """Modèle pour les recruteurs."""
    
    __tablename__ = "recruiters"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(50))  # RH, Manager, Admin RH
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relations
    user = relationship("User", back_populates="recruiter_profile")
    company = relationship("Company", back_populates="recruiters")
    
    # Index
    __table_args__ = (
        UniqueConstraint('user_id', 'company_id', name='uq_user_company'),
        Index('idx_recruiters_user', 'user_id'),
        Index('idx_recruiters_company', 'company_id'),
    )

class CompanySkillNeed(Base):
    """Modèle pour les besoins en compétences des entreprises (GEPP)."""
    
    __tablename__ = "company_skill_needs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    competence_id = Column(UUID(as_uuid=True), ForeignKey("competences_referentiel.id", ondelete="CASCADE"), nullable=False)
    priority = Column(Integer)  # 1=critique, 2=important, 3=souhaitable
    created_at = Column(DateTime, default=func.now())
    
    # Relations
    company = relationship("Company", back_populates="skill_needs")
    competence = relationship("CompetenceReferentiel")
    
    # Index
    __table_args__ = (
        UniqueConstraint('company_id', 'competence_id', name='uq_company_skill'),
        Index('idx_company_skill_needs_company', 'company_id'),
        Index('idx_company_skill_needs_priority', 'priority'),
    )

# ==================== MODULE 4: ATS (APPLICANT TRACKING SYSTEM) ====================

class Application(Base):
    """Modèle pour les candidatures (ATS)."""
    
    __tablename__ = "applications"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(UUID(as_uuid=True), ForeignKey("offres_emploi_enrichies.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    
    # Pipeline status: applied, shortlisted, interview_scheduled, interview_completed, offer_made, hired, rejected, withdrawn
    status = Column(String(50), nullable=False, default="applied")
    
    # Additional fields
    cover_letter = Column(Text)
    notes = Column(Text)  # Notes internes RH
    rating = Column(Integer)  # 1-5 rating by recruiter
    match_score = Column(Float)  # % de matching calculé par l'IA
    
    # Timestamps
    applied_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    reviewed_at = Column(DateTime)  # When recruiter first reviewed
    interview_date = Column(DateTime)
    decision_date = Column(DateTime)
    
    # Relations
    user = relationship("User", backref="applications")
    job = relationship("OffreEmploiEnrichie", backref="applications")
    company = relationship("Company", backref="applications")
    status_history = relationship("ApplicationStatusHistory", back_populates="application", cascade="all, delete-orphan")
    
    # Lien vers le CV utilisé pour cette candidature
    cv_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    cv = relationship("Document", backref="applications_used_in")
    
    # Index
    __table_args__ = (
        UniqueConstraint('user_id', 'job_id', name='uq_user_job_application'),
        Index('idx_applications_user', 'user_id'),
        Index('idx_applications_job', 'job_id'),
        Index('idx_applications_company', 'company_id'),
        Index('idx_applications_status', 'status'),
        Index('idx_applications_applied_at', 'applied_at'),
    )

class ApplicationStatusHistory(Base):
    """Historique des changements de statut des candidatures."""
    
    __tablename__ = "application_status_history"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    from_status = Column(String(50))
    to_status = Column(String(50), nullable=False)
    changed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))  # Recruiter who made the change
    comment = Column(Text)
    created_at = Column(DateTime, default=func.now())
    
    # Relations
    application = relationship("Application", back_populates="status_history")
    changed_by_user = relationship("User")
    
    # Index
    __table_args__ = (
        Index('idx_status_history_application', 'application_id'),
        Index('idx_status_history_created', 'created_at'),
    )

# ==================== MESSAGING (RECRUITER-CANDIDATE) ====================

class Message(Base):
    """Messages échangés entre recruteurs et candidats."""
    
    __tablename__ = "messages"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sender_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    receiver_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    
    # Relations
    sender = relationship("User", foreign_keys=[sender_id])
    receiver = relationship("User", foreign_keys=[receiver_id])
    
    # Index
    __table_args__ = (
        Index('idx_messages_sender', 'sender_id'),
        Index('idx_messages_receiver', 'receiver_id'),
        Index('idx_messages_created', 'created_at'),
    )

# ==================== MODULE 9: AI ASSISTANT (CHAT RH) ====================

class RHChatHistory(Base):
    """Historique des conversations avec l'assistant RH."""
    
    __tablename__ = "rh_chat_history"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recruiter_id = Column(UUID(as_uuid=True), ForeignKey("recruiters.id", ondelete="CASCADE"), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    context = Column(JSON)  # Context utilisé pour la réponse (données, filtres, etc.)
    model_used = Column(String(50))  # Nom du modèle LLM utilisé
    tokens_used = Column(Integer)  # Nombre de tokens consommés
    created_at = Column(DateTime, default=func.now())
    
    # Relations
    recruiter = relationship("Recruiter")
    
    # Index
    __table_args__ = (
        Index('idx_chat_history_recruiter', 'recruiter_id'),
        Index('idx_chat_history_created', 'created_at'),
    )

# ==================== RBAC: ROLES & PERMISSIONS ====================

class Role(Base):
    """Rôles utilisateur pour le système RBAC."""
    
    __tablename__ = "roles"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), unique=True, nullable=False)  # admin, recruiter, candidate, hr_manager
    description = Column(Text)
    permissions = Column(ARRAY(String))  # Liste des permissions
    created_at = Column(DateTime, default=func.now())
    
    # Relations
    user_roles = relationship("UserAssignment", back_populates="role", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_roles_name', 'name'),
    )

class UserAssignment(Base):
    """Association utilisateur-rôle."""
    
    __tablename__ = "user_roles"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    assigned_at = Column(DateTime, default=func.now())
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))  # Qui a assigné ce rôle
    
    # Relations
    user = relationship("User", foreign_keys=[user_id], backref="user_roles")
    role = relationship("Role", back_populates="user_roles")
    assigner = relationship("User", foreign_keys=[assigned_by])
    
    __table_args__ = (
        UniqueConstraint('user_id', 'role_id', name='uq_user_role'),
        Index('idx_user_roles_user', 'user_id'),
        Index('idx_user_roles_role', 'role_id'),
    )

# ==================== NOTIFICATIONS ====================

class Notification(Base):
    """Notifications pour les utilisateurs."""
    
    __tablename__ = "notifications"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(50), nullable=False)  # application_status, new_match, interview_reminder, etc.
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    action_url = Column(String(500))  # URL vers l'action concernée
    is_read = Column(Boolean, default=False)
    is_sent = Column(Boolean, default=False)  # Pour tracking email/push
    extra_data = Column(JSON)  # Données additionnelles
    created_at = Column(DateTime, default=func.now())
    read_at = Column(DateTime)
    
    # Relations
    user = relationship("User", backref="notifications")
    
    __table_args__ = (
        Index('idx_notifications_user', 'user_id'),
        Index('idx_notifications_is_read', 'is_read'),
        Index('idx_notifications_created', 'created_at'),
        Index('idx_notifications_type', 'type'),
    )

# ==================== WEBHOOKS ====================

class Webhook(Base):
    """Webhooks pour intégrations externes."""
    
    __tablename__ = "webhooks"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    url = Column(String(500), nullable=False)
    events = Column(ARRAY(String), nullable=False)  # ["application.created", "application.status_changed"]
    secret = Column(String(255))  # Pour signature HMAC
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    last_triggered_at = Column(DateTime)
    
    # Relations
    company = relationship("Company", backref="webhooks")
    
    __table_args__ = (
        Index('idx_webhooks_company', 'company_id'),
        Index('idx_webhooks_is_active', 'is_active'),
    )

# Vue pour les analyses rapides (à créer via migration)
# Cette vue est déjà définie dans le script SQL d'initialisation


class UserSavedJob(Base):
    __tablename__ = "user_saved_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Relation vers l'utilisateur
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey('users.id', ondelete="CASCADE"),
        nullable=False
    )

    # Relation vers l'offre brute (plus stable que l'enrichie)
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey('offres_emploi_brutes.id', ondelete="CASCADE"),
        nullable=False
    )



    note = Column(Text)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relations correctes & cohérentes
    user = relationship("User", back_populates="saved_jobs")
    job = relationship("OffreEmploiBrute", back_populates="saved_by_users")

    __table_args__ = (
        UniqueConstraint('user_id', 'job_id', name='uq_user_saved_job'),
        Index('idx_user_saved_jobs_user', 'user_id'),
        Index('idx_user_saved_jobs_job', 'job_id'),
        Index('idx_user_saved_jobs_created', 'created_at'),
    )

class Document(Base):
    """Modèle pour les documents des candidats (CV, diplômes, etc.)."""
    
    __tablename__ = "documents"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_type = Column(String(50), nullable=False) # 'application/pdf', 'image/jpeg', etc.
    size = Column(String(50)) # Human readable size or bytes
    category = Column(String(50), nullable=False) # 'cv', 'diploma', 'cert', 'other'
    uploaded_at = Column(DateTime, default=func.now())
    is_verified = Column(Boolean, default=False)
    
    # Contenu extrait du document (pour persistance sur Railway)
    extracted_text = Column(Text, nullable=True)
    
    # Relations
    user = relationship("User", backref="documents")

    __table_args__ = (
        Index('idx_documents_user', 'user_id'),
        Index('idx_documents_category', 'category'),
    )
class AdvertiserProfile(Base):
    """Profil pour les annonceurs/contributeurs."""
    __tablename__ = "advertiser_profiles"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    points = Column(Integer, default=0)
    level = Column(Integer, default=1)
    total_contributions = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relations
    user = relationship("User", back_populates="advertiser_profile")
    claimed_rewards = relationship("UserReward", back_populates="advertiser")
    transactions = relationship("PointTransaction", back_populates="advertiser")

class PointTransaction(Base):
    """Historique des transactions de points."""
    __tablename__ = "point_transactions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    advertiser_id = Column(UUID(as_uuid=True), ForeignKey("advertiser_profiles.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Integer, nullable=False) # Positif pour ajout, négatif pour dépense
    reason = Column(String(255), nullable=False) # "job_post_form", "job_post_file", "reward_claim", etc.
    created_at = Column(DateTime, default=func.now())
    
    # Relations
    advertiser = relationship("AdvertiserProfile", back_populates="transactions")

class Reward(Base):
    """Catalogue des récompenses."""
    __tablename__ = "rewards"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    cost_points = Column(Integer, nullable=False)
    image_url = Column(String(500))
    is_active = Column(Boolean, default=True)
    stock = Column(Integer, default=-1) # -1 pour illimité
    created_at = Column(DateTime, default=func.now())

class UserReward(Base):
    """Récompenses réclamées par les utilisateurs."""
    __tablename__ = "user_rewards"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    advertiser_id = Column(UUID(as_uuid=True), ForeignKey("advertiser_profiles.id", ondelete="CASCADE"), nullable=False)
    reward_id = Column(UUID(as_uuid=True), ForeignKey("rewards.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(50), default="claimed") # "claimed", "used", "expired"
    claim_code = Column(String(100), unique=True) # Code de validation unique
    claimed_at = Column(DateTime, default=func.now())
    
    # Relations
    advertiser = relationship("AdvertiserProfile", back_populates="claimed_rewards")
    reward = relationship("Reward")
