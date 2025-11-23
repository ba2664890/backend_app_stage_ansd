"""
Modèles SQLAlchemy pour la base de données.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, ARRAY, JSON, ForeignKey, UniqueConstraint, Index
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
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relations CORRIGÉES
    enrichie = relationship("OffreEmploiEnrichie", back_populates="offre_brute", uselist=False)
    admin_boundary_id = Column(Integer, ForeignKey("senegal_admin_boundaries.id"))
    admin_boundary = relationship(
        "SenegalAdminBoundary", 
        back_populates="offres_brutes",
        foreign_keys=[admin_boundary_id]
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

    saved_by_users = relationship(
        "UserSavedJob",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="dynamic"
    )

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

    # relations
    user = relationship("User", back_populates="profile")
    recommendations = relationship("JobRecommendation", back_populates="user")

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

# Vue pour les analyses rapides (à créer via migration)
# Cette vue est déjà définie dans le script SQL d'initialisation

class UserSavedJob(Base):
    """Modèle pour les offres d'emploi sauvegardées par les utilisateurs."""
    
    __tablename__ = "user_saved_jobs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete="CASCADE"), nullable=False)
    job_id = Column(UUID(as_uuid=True), ForeignKey('offres_emploi_brutes.id', ondelete="CASCADE"), nullable=False)
    
    # Optionnel : note personnelle de l'utilisateur
    note = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relations
    user = relationship("User", back_populates="saved_jobs")
    job = relationship("OffreEmploiBrute", back_populates="saved_by_users")
    
    # Contraintes et index
    __table_args__ = (
        UniqueConstraint('user_id', 'job_id', name='uq_user_saved_job'),
        Index('idx_user_saved_jobs_user', 'user_id'),
        Index('idx_user_saved_jobs_job', 'job_id'),
        Index('idx_user_saved_jobs_created', 'created_at'),
        Index('idx_user_saved_jobs_user_job', 'user_id', 'job_id'),  # Composite index pour les recherches rapides
    )