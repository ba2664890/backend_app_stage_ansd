# Models package for Emploi Dakar backend

from .database_models import (
    OffreEmploiBrute,
    OffreEmploiEnrichie, 
    UserProfile,
    JobRecommendation,
    JobStatistics,
    CompetenceReferentiel
)

from .api_models import (
    JobOfferResponse,
    JobSearchParams,
    UserProfileCreate,
    UserProfileResponse,
    RecommendationRequest,
    RecommendationResponse,
    PaginatedResponse
)

__all__ = [
    # Database models
    'OffreEmploiBrute',
    'OffreEmploiEnrichie',
    'UserProfile',
    'JobRecommendation',
    'JobStatistics',
    'CompetenceReferentiel',
    
    # API models
    'JobOfferResponse',
    'JobSearchParams',
    'UserProfileCreate',
    'UserProfileResponse',
    'RecommendationRequest',
    'RecommendationResponse',
    'PaginatedResponse'
]