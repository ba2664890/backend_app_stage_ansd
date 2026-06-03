"""
Modèles Pydantic pour l'API REST.
"""

from pydantic import BaseModel, ConfigDict, Field, EmailStr, validator
from typing import List, Optional, Dict, Any, Generic, TypeVar
from datetime import date, datetime
from uuid import UUID

from .database_models import UserRole, CandidateCategory

# Modèles de base
class BaseResponse(BaseModel):
    """Modèle de base pour les réponsess API."""
    success: bool = True
    message: Optional[str] = None

# Modèles pour les offres d'emploi
class JobOfferBase(BaseModel):
    """Modèle de base pour les offres d'emploi."""
    title: Optional[str] = Field(None, description="Titre du poste")
    company_name: Optional[str] = Field(None, description="Nom de l'entreprise")
    location: Optional[str] = Field(None, description="Localisation du poste")
    contract_type: Optional[str] = Field(None, description="Type de contrat")
    description: Optional[str] = Field(None, description="Description du poste")
    posted_date: Optional[datetime] = Field(None, description="Date de publication")
    url: Optional[str] = Field(None, description="URL de l'offre")
    source: Optional[str] = Field(None, description="Source de l'offre")
    
    # Nouveaux champs pour la publication
    education_level: Optional[str] = Field(None, description="Niveau d'études requis")
    nb_positions: Optional[int] = Field(1, description="Nombre de postes ouverts")
    expiration_date: Optional[datetime] = Field(None, description="Date d'expiration de l'offre")
    remote_type: Optional[str] = Field(None, description="Type de télétravail (Onsite, Hybrid, Remote)")
    is_urgent: Optional[bool] = Field(False, description="Marquer comme urgent")
    languages: Optional[List[str]] = Field(None, description="Langues requises")
    benefits: Optional[List[str]] = Field(None, description="Avantages proposés")


class JobCreate(BaseModel):
    """Modèle pour créer une offre d'emploi."""
    title: str = Field(..., description="Titre du poste")
    company_name: str = Field(..., description="Nom de l'entreprise")
    location: str = Field(..., description="Localisation")
    contract_type: str = Field(..., description="Type de contrat")
    description: str = Field(..., description="Description du poste")
    url: Optional[str] = Field(None, description="URL de candidature")
    
    # Champs enrichis
    sector: Optional[str] = Field(None, description="Secteur d'activité")
    min_salary: Optional[int] = Field(None, description="Salaire minimum")
    max_salary: Optional[int] = Field(None, description="Salaire maximum")
    experience_years: Optional[int] = Field(None, description="Années d'expérience requises")
    education_level: Optional[str] = Field(None, description="Niveau d'études requis")
    skills: Optional[List[str]] = Field(None, description="Compétences requises")
    remote_type: Optional[str] = Field(None, description="Type de télétravail")
    is_urgent: bool = Field(False, description="Urgent")
    expiration_date: Optional[datetime] = Field(None, description="Date d'expiration")
    languages: Optional[List[str]] = Field(None, description="Langues requises")
    benefits: Optional[List[str]] = Field(None, description="Avantages")
    nb_positions: Optional[int] = Field(1, description="Nombre de postes")

class JobOfferResponse(JobOfferBase):
    """Modèle de réponse pour une offre d'emploi enrichie."""
    id: UUID
    spider_source: str = Field(..., description="Source du spider")
    original_id: str = Field(..., description="ID original")
    
    # Informations enrichies
    extracted_salary_min: Optional[int] = Field(None, description="Salaire minimum extrait")
    extracted_salary_max: Optional[int] = Field(None, description="Salaire maximum extrait")
    extracted_salary_currency: Optional[str] = Field(None, description="Devise du salaire")
    extracted_contract_type: Optional[str] = Field(None, description="Type de contrat extrait")
    extracted_experience_years: Optional[int] = Field(None, description="Années d'expérience requises")
    extracted_skills: Optional[List[str]] = Field(None, description="Compétences extraites")
    extracted_sector: Optional[str] = Field(None, description="Secteur d'activité")
    extracted_job_category: Optional[str] = Field(None, description="Catégorie du poste")
    extracted_job_title: Optional[str] = Field(None, description="Titre du poste extrait")
    
    # Analyse sémantique
    sentiment_score: Optional[float] = Field(None, description="Score de sentiment")
    key_phrases: Optional[List[str]] = Field(None, description="Phrases clés")
    
    # Classification
    job_level: Optional[str] = Field(None, description="Niveau du poste")
    job_type: Optional[str] = Field(None, description="Type d'emploi")
    
    # Métadonnées
    confidence_score: Optional[float] = Field(None, description="Score de confiance NLP")
    created_at: Optional[datetime] = None
    processed_at: Optional[datetime] = Field(None, description="Date de traitement NLP")
    recruiter_id: Optional[UUID] = None
    contributor_id: Optional[UUID] = None

    @validator("posted_date", pre=True, always=True)
    def parse_posted_date(cls, v):
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        if isinstance(v, date):
            # Convertit date → datetime à minuit
            return datetime.combine(v, datetime.min.time())
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v)
            except ValueError:
                raise ValueError(f"Impossible de parser posted_date: {v}")
        raise ValueError(f"Type invalide pour posted_date: {type(v)}")    
    class Config:
        from_attributes = True

class JobSearchParams(BaseModel):
    """Paramètres de recherche pour les offres d'emploi."""
    skip: int = Field(0, ge=0, description="Nombre d'offres à ignorer")
    limit: int = Field(20, ge=1, le=100, description="Nombre d'offres à retourner")
    location: Optional[str] = Field(None, description="Filtrer par localisation")
    contract_type: Optional[str] = Field(None, description="Filtrer par type de contrat")
    sector: Optional[str] = Field(None, description="Filtrer par secteur")
    min_salary: Optional[int] = Field(None, ge=0, description="Salaire minimum")
    max_salary: Optional[int] = Field(None, ge=0, description="Salaire maximum")
    job_title: Optional[str] = Field(None, description="Filtrer par titre de poste extrait")
    search: Optional[str] = Field(None, description="Recherche textuelle")
    source_type: Optional[str] = Field(None, description="Filtrer par type de source (direct ou indirect)")
    education_level: Optional[str] = Field(None, description="Filtrer par niveau d'éducation")

# Modèles pour l'analytics
class MarketTrend(BaseModel):
    """Modèle pour une tendance du marché."""
    period: str = Field(..., description="Période de la tendance")
    total_offers: int = Field(..., description="Nombre total d'offres")
    new_offers: int = Field(..., description="Nombre de nouvelles offres")
    avg_salary_min: Optional[float] = Field(None, description="Salaire minimum moyen")
    avg_salary_max: Optional[float] = Field(None, description="Salaire maximum moyen")
    top_sectors: List[Dict[str, Any]] = Field(..., description="Top secteurs")
    top_skills: List[Dict[str, Any]] = Field(..., description="Top compétences")

class SectorAnalysis(BaseModel):
    """Modèle pour l'analyse des secteurs."""
    sector: str = Field(..., description="Nom du secteur")
    count: int = Field(..., description="Nombre d'offres")
    percentage: float = Field(..., description="Pourcentage du total")
    avg_salary_min: Optional[float] = Field(None, description="Salaire minimum moyen")
    avg_salary_max: Optional[float] = Field(None, description="Salaire maximum moyen")
    top_skills: List[str] = Field(..., description="Compétences principales")

class SkillsAnalysis(BaseModel):
    """Modèle pour l'analyse des compétences."""
    skill: str = Field(..., description="Nom de la compétence")
    count: int = Field(..., description="Nombre de mentions")
    percentage: float = Field(..., description="Pourcentage d'apparition")
    related_sectors: List[str] = Field(..., description="Secteurs associés")
    salary_impact: Optional[float] = Field(None, description="Impact sur le salaire")

class SalaryTrend(BaseModel):
    """Modèle pour une tendance salariale."""
    period: str = Field(..., description="Période de la tendance")
    avg_salary_min: float = Field(..., description="Salaire minimum moyen")
    avg_salary_max: float = Field(..., description="Salaire maximum moyen")
    median_salary: float = Field(..., description="Salaire médian")
    percentile_25: float = Field(..., description="25ème percentile")
    percentile_75: float = Field(..., description="75ème percentile")
    sector: Optional[str] = Field(None, description="Secteur spécifique")

class JobAnalyticsResponse(BaseModel):
    """Réponse pour l'analyse du marché."""
    period: str = Field(..., description="Période analysée")
    total_offers: int = Field(..., description="Nombre total d'offres")
    total_companies: int = Field(..., description="Nombre total d'entreprises")
    total_locations: int = Field(..., description="Nombre total de localisations")
    market_trends: List[MarketTrend] = Field(..., description="Tendances du marché")
    sector_analysis: List[SectorAnalysis] = Field(..., description="Analyse des secteurs")
    skills_analysis: List[SkillsAnalysis] = Field(..., description="Analyse des compétences")
    salary_trends: List[SalaryTrend] = Field(..., description="Tendances salariales")

# Modèles pour les recommandations
class RecommendationRequest(BaseModel):
    """Requête pour obtenir des recommandations."""
    max_results: int = Field(10, ge=1, le=200, description="Nombre maximum de recommandations")
    min_match_score: float = Field(0.5, ge=0.0, le=1.0, description="Score de matching minimum")
    preferred_sectors: Optional[List[str]] = Field(None, description="Secteurs préférés")
    preferred_contract_types: Optional[List[str]] = Field(None, description="Types de contrat préférés")
    min_salary: Optional[int] = Field(None, ge=0, description="Salaire minimum souhaité")
    max_salary: Optional[int] = Field(None, ge=0, description="Salaire maximum souhaité")
    preferred_job_titles: Optional[List[str]] = Field(None, description="Titres de poste préférés")
    location_radius: Optional[int] = Field(None, description="Rayon de recherche géographique (km)")


class JobRecommendationResponse(BaseModel):
    job_id: str
    title: str
    company_name: str
    location: str
    match_score: float
    match_reasons: List[str]
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    contract_type: Optional[str] = None
    experience_required: Optional[str] = None
    posted_date: Optional[datetime] = None
    deadline: Optional[datetime] = None
    url: Optional[str] = None
    skills: List[str]
    sector_match: bool
    contract_type_match: bool
    location_match: bool
    applicants_count: int = 0
    views_count: int = 0
    remote_option: bool = False
    is_favorited: bool = False
    company_size: Optional[str] = None
    status: str = "pending"

class RecommendationResponse(BaseModel):
    user_id: str  # Important : str, pas UUID
    recommendations: List[JobRecommendationResponse]
    total_recommendations: int
    average_match_score: float
    generated_at: datetime

# ==================== USER & PROFILE MODELS ====================

class UserProfileBase(BaseModel):
    """Modèle de base pour le profil utilisateur."""
    phone: Optional[str] = Field(None, description="Numéro de téléphone")
    first_name: Optional[str] = Field(None, description="Prénom")
    points: Optional[int] = Field(1240, description="Points formation du candidat")

    last_name: Optional[str] = Field(None, description="Nom")
    location: Optional[str] = Field(None, description="Localisation")
    category: Optional[CandidateCategory] = Field(CandidateCategory.STUDENT_PRO, description="Catégorie de profil candidat")
    current_title: Optional[str] = Field(None, description="Titre du poste actuel")
    experience_years: Optional[int] = Field(None, ge=0, description="Années d'expérience")
    education_level: Optional[str] = Field(None, description="Niveau d'éducation")
    skills: Optional[List[str]] = Field(None, description="Compétences")
    preferred_contract_type: Optional[List[str]] = Field(None, description="Types de contrat préférés")
    preferred_salary_min: Optional[int] = Field(None, ge=0, description="Salaire minimum préféré")
    preferred_salary_max: Optional[int] = Field(None, ge=0, description="Salaire maximum préféré")
    cv_url: Optional[str] = Field(None, description="URL du CV")
    bio: Optional[str] = Field(None, description="Biographie/Présentation")
    availability: Optional[str] = Field(None, description="Disponibilité")
    linkedin: Optional[str] = Field(None, description="Lien LinkedIn")
    github: Optional[str] = Field(None, description="Lien GitHub")
    portfolio: Optional[str] = Field(None, description="Lien Portfolio")
    whatsapp: Optional[str] = Field(None, description="Numéro WhatsApp")
    languages: Optional[List[Dict[str, Any]]] = Field(None, description="Langues maîtrisées")
    experiences: Optional[List[Dict[str, Any]]] = Field(None, description="Expériences et parcours")
    certifications: Optional[List[Dict[str, Any]]] = Field(None, description="Certifications obtenues")


class UserProfileCreate(UserProfileBase):
    """Modèle pour créer un profil utilisateur."""
    pass

class UserProfileResponse(UserProfileBase):
    """Modèle de réponse pour un profil utilisateur."""
    id: UUID
    created_at: datetime
    updated_at: datetime
    user_id: UUID
    role: Optional[str] = Field(None, description="Rôle utilisateur")
    email: Optional[str] = Field(None, description="Email de l'utilisateur")
    
    class Config:
        from_attributes = True

class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    role: Optional[str] = "candidate"
    is_active: bool = True
    created_at: datetime
    profile: Optional[UserProfileResponse] = None

    model_config = {"from_attributes": True}

class UserCreate(BaseModel):
    """Modèle pour créer un utilisateur."""
    email: EmailStr = Field(..., description="Email de l'utilisateur")
    password: str = Field(..., min_length=8, description="Mot de passe de l'utilisateur")
    role: Optional[str] = Field(None, description="Rôle de l'utilisateur (admin, recruiter, candidate, government)")
    
    # Champs optionnels pour le profil à la création
    first_name: Optional[str] = Field(None, description="Prénom")
    last_name: Optional[str] = Field(None, description="Nom")
    phone: Optional[str] = Field(None, description="Numéro de téléphone")
    location: Optional[str] = Field(None, description="Localisation")
    current_title: Optional[str] = Field(None, description="Titre actuel du poste")
    experience_years: Optional[int] = Field(None, ge=0, description="Années d'expérience")
    category: Optional[CandidateCategory] = Field(CandidateCategory.STUDENT_PRO, description="Catégorie de profil candidat")

    @validator('role', pre=True, always=True)
    def validate_role(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            return v.lower()
        return v

class UserStatusUpdate(BaseModel):
    """Modèle pour mettre à jour le statut d'un utilisateur."""
    is_active: bool

class AuthResponse(BaseModel):
    """Réponse d'authentification incluant le token et l'utilisateur."""
    access_token: str
    token_type: str = "bearer"
    user: UserProfileResponse

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class AdminBoundaryOut(BaseModel):
    name: str
    level: str
    parent_name: Optional[str] = None
    geojson: Dict[str, Any]
    centroid: Optional[Dict[str, float]] = None
    offer_count: int = 0

    model_config = ConfigDict(from_attributes=True) # type: ignore

# Modèles pour les statistiques
class DashboardStats(BaseModel):
    """Statistiques pour le tableau de bord."""
    total_offers: int
    total_companies: int
    total_locations: int
    offers_this_month: int
    offers_today: int
    avg_salary_min: Optional[float]
    avg_salary_max: Optional[float]
    top_sectors: List[Dict[str, Any]]
    top_skills: List[Dict[str, Any]]
    contract_type_distribution: List[Dict[str, Any]]
    experience_level_distribution: List[Dict[str, Any]]
    monthly_trend: List[Dict[str, Any]]
    # Métiers (Nouveaux)
    jobs_by_type: Optional[Dict[str, List[Dict[str, Any]]]] = None
    jobs_by_sector: Optional[Dict[str, List[Dict[str, Any]]]] = None

class GeographicStats(BaseModel):
    """Statistiques géographiques."""
    region: str
    count: int
    percentage: float
    avg_salary_min: Optional[float]
    avg_salary_max: Optional[float]
    top_sectors: List[str]
    coordinates: Optional[Dict[str, float]]  # lat, lng

class JobStatisticsResponse(BaseModel):
    """Réponse pour les statistiques d'emploi."""
    dashboard: DashboardStats
    geographic: List[GeographicStats]
    generated_at: datetime

# Modèles paginés
T = TypeVar('T')

class PaginatedResponse(BaseModel, Generic[T]):
    """Modèle de réponse paginée."""
    items: List[T] = Field(..., description="Éléments de la page")
    total: int = Field(..., description="Nombre total d'éléments")
    page: int = Field(..., description="Numéro de page")
    size: int = Field(..., description="Taille de la page")
    pages: int = Field(..., description="Nombre total de pages")
    has_next: bool = Field(..., description="Indique s'il y a une page suivante")
    has_prev: bool = Field(..., description="Indique s'il y a une page précédente")

class HeatmapData(BaseModel):
    sector: str
    skills: Dict[str, int]

class SalaryByExperience(BaseModel):
    level: str
    avg_min: Optional[float]
    avg_max: Optional[float]
    count: int

class CompanyHiringStats(BaseModel):
    company: str
    offers: int

class ContractTypeEvolution(BaseModel):
    month: str
    contracts: Dict[str, int]

class FullAnalyticsResponse(BaseModel):
    dashboard: DashboardStats
    geographic: List[GeographicStats]
    heatmap: List[HeatmapData]
    salary_by_experience: List[SalaryByExperience]
    top_companies: List[CompanyHiringStats]
    contract_evolution: List[ContractTypeEvolution]
    evolution_rates: Dict[str, Any]
    # Nouveaux champs pour les métiers
    jobs_by_type: Optional[Dict[str, List[Dict[str, Any]]]] = None
    jobs_by_sector: Optional[Dict[str, List[Dict[str, Any]]]] = None
    skills_by_job: Optional[List[Dict[str, Any]]] = None
    generated_at: datetime




class OfferGeoJSON(BaseModel):
    id: str
    title: Optional[str] = None
    location: Optional[str]
    contract: Optional[str]
    boundary: str

class ChoroplethResponse(BaseModel):
    type: str = "FeatureCollection"
    features: List[Dict[str, Any]] = Field(description="GeoJSON Features")
    offers: List[OfferGeoJSON]
    total_boundaries: int
    total_offers: int



from pydantic import BaseModel

class SaveJobRequest(BaseModel):
    job_id: str

# ==================== MODULE 1: COMPANIES & RECRUITERS ====================

# Company schemas
class CompanyBase(BaseModel):
    """Modèle de base pour les entreprises."""
    name: str = Field(..., description="Nom de l'entreprise")
    sector: Optional[str] = Field(None, description="Secteur d'activité")
    size: Optional[str] = Field(None, description="Taille de l'entreprise (PME, ETI, GE)")
    location: Optional[str] = Field(None, description="Localisation")
    description: Optional[str] = Field(None, description="Description de l'entreprise")

class CompanyCreate(CompanyBase):
    """Modèle pour créer une entreprise."""
    pass

class CompanyUpdate(BaseModel):
    """Modèle pour mettre à jour une entreprise."""
    name: Optional[str] = None
    sector: Optional[str] = None
    size: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None

class CompanyResponse(CompanyBase):
    """Modèle de réponse pour une entreprise."""
    id: UUID
    is_verified: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

# Recruiter schemas
class RecruiterBase(BaseModel):
    """Modèle de base pour les recruteurs."""
    role: Optional[str] = Field(None, description="Rôle (RH, Manager, Admin RH)")

class RecruiterCreate(RecruiterBase):
    """Modèle pour créer un recruteur."""
    company_id: UUID = Field(..., description="ID de l'entreprise")

class RecruiterInvite(BaseModel):
    """Modèle pour inviter un nouveau recruteur."""
    email: str = Field(..., description="Email de l'utilisateur à inviter")
    role: Optional[str] = Field("recruiter", description="Rôle à lui assigner")

class RecruiterResponse(RecruiterBase):
    """Modèle de réponse pour un recruteur."""
    id: UUID
    user_id: UUID
    company_id: UUID
    created_at: datetime
    
    # Enrichissement avec les données utilisateur
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    
    class Config:
        from_attributes = True

class RecruiterWithCompanyResponse(RecruiterResponse):
    """Modèle de réponse pour un recruteur avec les détails de l'entreprise."""
    company: CompanyResponse
    
    class Config:
        from_attributes = True

# Company Skill Need schemas
class CompanySkillNeedCreate(BaseModel):
    """Modèle pour créer un besoin en compétence."""
    competence_id: UUID = Field(..., description="ID de la compétence")
    priority: int = Field(..., ge=1, le=3, description="Priorité (1=critique, 2=important, 3=souhaitable)")

class CompanySkillNeedResponse(BaseModel):
    """Modèle de réponse pour un besoin en compétence."""
    id: UUID
    company_id: UUID
    competence_id: UUID
    priority: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class SkillGapResponse(BaseModel):
    """Modèle de réponse pour un écart de compétence (Frontend compatibility)."""
    skill: str
    needed_count: int
    gap_percentage: float
    difficulty_level: str # 'easy', 'medium', 'hard'

# ==================== MODULE 4: ATS (APPLICANT TRACKING SYSTEM) ====================

class ApplicationBase(BaseModel):
    """Modèle de base pour les candidatures."""
    cover_letter: Optional[str] = Field(None, description="Lettre de motivation")

class ApplicationCreate(ApplicationBase):
    """Modèle pour créer une candidature."""
    job_id: UUID = Field(..., description="ID de l'offre d'emploi")

class ApplicationUpdateStatus(BaseModel):
    """Modèle pour mettre à jour le statut d'une candidature."""
    status: str = Field(..., description="Nouveau statut (applied, shortlisted, interview_scheduled, etc.)")
    comment: Optional[str] = Field(None, description="Commentaire sur le changement")
    interview_date: Optional[datetime] = Field(None, description="Date d'entretien si applicable")

class ApplicationUpdateNotes(BaseModel):
    """Modèle pour mettre à jour les notes RH."""
    notes: Optional[str] = None
    rating: Optional[int] = Field(None, ge=1, le=5, description="Note de 1 à 5")

class ApplicationResponse(ApplicationBase):
    """Modèle de réponse pour une candidature."""
    id: UUID
    user_id: UUID
    job_id: UUID
    company_id: UUID
    cv_id: Optional[UUID] = None  # Ajout du lien vers le CV
    status: str
    notes: Optional[str]
    rating: Optional[int]
    applied_at: datetime
    updated_at: datetime
    reviewed_at: Optional[datetime]
    interview_date: Optional[datetime]
    decision_date: Optional[datetime]
    
    class Config:
        from_attributes = True

class ApplicationWithDetailsResponse(ApplicationResponse):
    """Modèle de réponse avec détails utilisateur et offre."""
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    job_title: Optional[str] = None
    company_name: Optional[str] = None

class ApplicationStatusHistoryResponse(BaseModel):
    """Modèle de réponse pour l'historique de statut."""
    id: UUID
    application_id: UUID
    from_status: Optional[str]
    to_status: str
    changed_by: Optional[UUID]
    comment: Optional[str]
    created_at: datetime
    
    # Extra fields for dashboard
    candidate_name: Optional[str] = None
    action_label: Optional[str] = None
    
    class Config:
        from_attributes = True

class ApplicationStatsResponse(BaseModel):
    """Statistiques des candidatures."""
    total: int
    by_status: Dict[str, int]
    avg_time_to_review: Optional[float] = None  # en heures
    avg_time_to_hire: Optional[float] = None  # en jours
    conversion_rate: Optional[float] = None  # % applied → hired
    avg_match_score: Optional[float] = None  # % moyen de matching
    recent_activities: List[ApplicationStatusHistoryResponse] = []

# ==================== MODULE 9: AI ASSISTANT (CHAT RH) ====================

class ChatRequest(BaseModel):
    """Requête pour le chat RH."""
    question: str = Field(..., description="Question posée à l'assistant")
    context: Optional[Dict[str, Any]] = Field(None, description="Contexte additionnel")

class ChatResponse(BaseModel):
    """Réponse du chat RH."""
    answer: str = Field(..., description="Réponse de l'assistant")
    sources: Optional[List[str]] = Field(None, description="Sources utilisées")
    suggestions: Optional[List[str]] = Field(None, description="Suggestions de questions")

class ChatHistoryResponse(BaseModel):
    """Historique de chat."""
    id: UUID
    recruiter_id: UUID
    question: str
    answer: str
    created_at: datetime
    
    class Config:
        from_attributes = True

class GenerateJobDescriptionRequest(BaseModel):
    """Requête pour générer une description de poste."""
    job_title: str = Field(..., description="Titre du poste")
    sector: Optional[str] = Field(None, description="Secteur d'activité")
    experience_level: Optional[str] = Field(None, description="Niveau d'expérience requis")
    key_skills: Optional[List[str]] = Field(None, description="Compétences clés")
    additional_context: Optional[str] = Field(None, description="Contexte additionnel")

class GenerateJobDescriptionResponse(BaseModel):
    """Réponse de génération de description."""
    job_description: str = Field(..., description="Description générée")
    suggested_skills: List[str] = Field(..., description="Compétences suggérées")
    suggested_salary_range: Optional[Dict[str, int]] = Field(None, description="Fourchette salariale suggérée")


# ==================== WEBHOOKS ====================

class WebhookBase(BaseModel):
    """Modèle de base pour les webhooks."""
    url: str = Field(..., description="URL de callback")
    events: List[str] = Field(..., description="Liste des événements souscrits")
    is_active: bool = Field(True, description="Si le webhook est actif")

class WebhookCreate(WebhookBase):
    """Modèle pour créer un webhook."""
    company_id: UUID

class WebhookUpdate(BaseModel):
    """Modèle pour mettre à jour un webhook."""
    url: Optional[str] = None
    events: Optional[List[str]] = None
    is_active: Optional[bool] = None

class WebhookResponse(WebhookBase):
    """Modèle de réponse pour un webhook."""
    id: UUID
    company_id: UUID
    secret: Optional[str] = Field(None, description="Secret pour signature HMAC")
    created_at: datetime
    last_triggered_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)

# ==================== ADVERTISER & REWARDS ====================

class AdvertiserProfileResponse(BaseModel):
    id: UUID
    user_id: UUID
    points: int
    level: int
    total_contributions: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class RewardResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    cost_points: int
    image_url: Optional[str] = None
    is_active: bool
    stock: int
    
    class Config:
        from_attributes = True

class UserRewardResponse(BaseModel):
    id: UUID
    reward: RewardResponse
    status: str
    claim_code: Optional[str] = None
    claimed_at: datetime
    
    class Config:
        from_attributes = True

class PointTransactionResponse(BaseModel):
    id: UUID
    amount: int
    reason: str
    created_at: datetime
    
    class Config:
        from_attributes = True

# ==================== MESSAGING (RECRUITER-CANDIDATE) ====================

class MessageCreate(BaseModel):
    """Modèle pour envoyer un message."""
    receiver_id: UUID = Field(..., description="ID du destinataire")
    content: str = Field(..., description="Contenu du message")

class MessageResponse(BaseModel):
    """Modèle de réponse pour un message."""
    id: UUID
    sender_id: UUID
    receiver_id: UUID
    content: str
    is_read: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class ConversationSummary(BaseModel):
    """Résumé d'une conversation pour la liste."""
    user_id: UUID
    first_name: Optional[str]
    last_name: Optional[str]
    email: Optional[str]
    last_message: Optional[str]
    last_message_at: Optional[datetime]
    unread_count: int = 0
    role: str

class AdvertiserStatsResponse(BaseModel):
    profile: AdvertiserProfileResponse
    recent_transactions: List[PointTransactionResponse]
    claimed_rewards: List[UserRewardResponse]


class TrajectoryStepResponse(BaseModel):
    id: UUID
    category: str
    step_name: str
    comment: Optional[str] = None
    order: int
    # Frontend-facing aliases
    label: str = ""
    ai_insight: str = ""

    class Config:
        from_attributes = True

    @classmethod
    def from_orm(cls, obj):
        instance = super().from_orm(obj)
        instance.label = obj.step_name
        instance.ai_insight = obj.comment or ""
        return instance

