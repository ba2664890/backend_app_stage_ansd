"""
Modèles Pydantic pour l'API REST.
"""

from pydantic import BaseModel, ConfigDict, Field, EmailStr, validator
from typing import List, Optional, Dict, Any, Generic, TypeVar
from datetime import date, datetime
from uuid import UUID

# Modèles de base
class BaseResponse(BaseModel):
    """Modèle de base pour les réponses API."""
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
    
    # Analyse sémantique
    sentiment_score: Optional[float] = Field(None, description="Score de sentiment")
    key_phrases: Optional[List[str]] = Field(None, description="Phrases clés")
    
    # Classification
    job_level: Optional[str] = Field(None, description="Niveau du poste")
    job_type: Optional[str] = Field(None, description="Type d'emploi")
    
    # Métadonnées
    confidence_score: Optional[float] = Field(None, description="Score de confiance NLP")
    created_at: datetime
    processed_at: Optional[datetime] = Field(None, description="Date de traitement NLP")
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
    search: Optional[str] = Field(None, description="Recherche textuelle")

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
    max_results: int = Field(10, ge=1, le=50, description="Nombre maximum de recommandations")
    min_match_score: float = Field(0.5, ge=0.0, le=1.0, description="Score de matching minimum")
    preferred_sectors: Optional[List[str]] = Field(None, description="Secteurs préférés")
    preferred_contract_types: Optional[List[str]] = Field(None, description="Types de contrat préférés")
    min_salary: Optional[int] = Field(None, ge=0, description="Salaire minimum souhaité")
    max_salary: Optional[int] = Field(None, ge=0, description="Salaire maximum souhaité")
    location_radius: Optional[int] = Field(None, description="Rayon de recherche géographique (km)")

class JobRecommendationResponse(BaseModel):
    """Réponse pour une recommandation d'emploi."""
    job_id: UUID
    title: str
    company_name: Optional[str]
    location: Optional[str]
    match_score: float
    match_reasons: List[str]
    salary_range: Optional[str]
    skills_match: List[str]
    sector_match: bool
    contract_type_match: bool
    location_match: bool

class RecommendationResponse(BaseModel):
    """Réponse pour les recommandations."""
    user_id: UUID
    recommendations: List[JobRecommendationResponse]
    total_recommendations: int
    average_match_score: float
    generated_at: datetime

# ==================== Pydantic Models ====================
class UserCreate(BaseModel):
    """Modèle pour créer un utilisateur."""
    email: EmailStr = Field(..., description="Email de l'utilisateur")
    password: str = Field(..., min_length=8, description="Mot de passe de l'utilisateur")


class UserProfileResponses(BaseModel):
    id: UUID
    user_id: UUID

    model_config = {"from_attributes": True}


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    profile: Optional[UserProfileResponses] = None

    model_config = {"from_attributes": True}



# Modèles pour les utilisateurs
class UserProfileBase(BaseModel):
    """Modèle de base pour le profil utilisateur."""
    email: EmailStr = Field(..., description="Email de l'utilisateur")
    phone: Optional[str] = Field(None, description="Numéro de téléphone")
    first_name: Optional[str] = Field(None, description="Prénom")
    last_name: Optional[str] = Field(None, description="Nom")
    location: Optional[str] = Field(None, description="Localisation")
    experience_years: Optional[int] = Field(None, ge=0, description="Années d'expérience")
    education_level: Optional[str] = Field(None, description="Niveau d'éducation")
    skills: Optional[List[str]] = Field(None, description="Compétences")
    preferred_contract_type: Optional[List[str]] = Field(None, description="Types de contrat préférés")
    preferred_salary_min: Optional[int] = Field(None, ge=0, description="Salaire minimum préféré")
    preferred_salary_max: Optional[int] = Field(None, ge=0, description="Salaire maximum préféré")
    cv_url: Optional[str] = Field(None, description="URL du CV")
    

class UserProfileCreate(UserProfileBase):
    """Modèle pour créer un profil utilisateur."""
    pass

class UserProfileResponse(UserProfileBase):
    """Modèle de réponse pour un profil utilisateur."""
    id: UUID
    created_at: datetime
    updated_at: datetime
    user_id: UUID
    
    class Config:
        from_attributes = True

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