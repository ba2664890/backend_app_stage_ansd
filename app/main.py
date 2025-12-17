"""
Main FastAPI application for the Emploi Dakar platform.
Provides REST API endpoints for job data, analytics, and recommendations.
"""

from pydoc import text
from fastapi import BackgroundTasks, FastAPI, HTTPException, Depends, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, Response
from contextlib import asynccontextmanager
import logging
import os
from typing import List, Optional, Dict, Any, cast
from datetime import datetime, timedelta
from pathlib import Path

import pydantic
from pydantic import EmailStr

from app.core.constants import AdminLevel
from app.services.admin_boundary_importer import AdminBoundaryImporterService


# Import des modules internes
from .database import SessionLocal, engine, Base, get_db
from .models.database_models import (
    OffreEmploiBrute, OffreEmploiEnrichie, SenegalAdminBoundary, User, UserProfile, 
    JobRecommendation, JobStatistics 
)
from .models.api_models import (
    ChoroplethResponse, CompanyHiringStats, ContractTypeEvolution, JobOfferResponse, JobAnalyticsResponse, RecommendationRequest, RecommendationResponse, SalaryByExperience, SaveJobRequest,
    UserProfileCreate, UserProfileResponse, JobSearchParams,
    PaginatedResponse, JobStatisticsResponse ,GeographicStats , SkillsAnalysis ,SalaryTrend , SectorAnalysis , FullAnalyticsResponse, DashboardStats , HeatmapData, UserResponse
)

from .services.job_service import JobService
from .services.analytics_service import AnalyticsService
from .services.recommendation_service import RecommendationService
from .services.user_service import UserService
from .services.admin_boundary import AdminBoundaryService, CarteService
from .models.api_models import AdminBoundaryOut
from .services.file_service import FileService

from .utils.auth import create_access_token, get_current_user, verify_password
from .utils.logger import setup_logging
from sqlalchemy.orm import Session
from sqlalchemy import text
from uuid import UUID

from app.services import job_service

# Configuration du logging
setup_logging()
logger = logging.getLogger(__name__)

"""
Application FastAPI avec lifespan robuste.
Gère PostGIS, création tables, et init services avec retry.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy.orm import Session


from .db.init_postgis import PostGISManager
from .core.exceptions import AppError, setup_exception_handlers
from .services.job_service import JobService
from .services.analytics_service import AnalyticsService
from .services.recommendation_service import RecommendationService
from .services.user_service import UserService
from .services.file_service import FileService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestionnaire de cycle de vie amélioré avec :
    - Vérification PostGIS avec retry
    - Création tables conditionnelle
    - Initialisation services avec gestion d'erreurs
    - Arrêt propre
    """
    
    logger.info("=" * 60)
    logger.info("🚀 DÉMARRAGE DE L'API EMPLOI SENEGAL")
    logger.info("=" * 60)
    
    db: Optional[Session] = None
    
    try:
        # Ouvre une session temporaire
        db = SessionLocal()
        
        # ÉTAPE 1 : Vérifie et installe PostGIS
        logger.info("Étape 1/3 : Vérification PostGIS...")
        postgis_manager = PostGISManager(max_retries=3, retry_delay=2.0)
        
        try:
            postgis_manager.ensure_postgis(db)
        except AppError as e:
            logger.error(f"❌ ERREUR POSTGIS CRITIQUE : {e.message}")
            logger.error("💡 L'application va démarrer SANS fonctionnalités géospatiales")
            
            # Mode dégradé : on continue mais on désactive les features geo
            app.state.geo_enabled = False
        else:
            app.state.geo_enabled = True
            logger.info("✅ PostGIS prêt")
        
        # ÉTAPE 2 : Création des tables
        logger.info("Étape 2/3 : Création des tables...")
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("✅ Tables créées/mises à jour avec succès")
        except Exception as e:
            logger.exception("❌ Erreur lors de la création des tables")
            raise AppError(
                message="Échec de création des tables",
                context={"error": str(e)},
                status_code=500,
            ) from e
        
        # ÉTAPE 3 : Initialisation des services
        logger.info("Étape 3/3 : Initialisation des services...")
        try:
            app.state.job_service = JobService()
            app.state.analytics_service = AnalyticsService()
            app.state.recommendation_service = RecommendationService()
            app.state.user_service = UserService()
            app.state.file_service = FileService()
            
            # Tu peux ajouter ici des vérifications de santé des services
            # ex: await app.state.job_service.health_check()
            
            logger.info("✅ Services initialisés")
            
        except Exception as e:
            logger.exception("❌ Erreur lors de l'init des services")
            raise AppError(
                message="Échec d'initialisation des services",
                context={"service_error": str(e)},
                status_code=500,
            ) from e
        
        # Statut final
        geo_status = "🗺️ Géospatial ACTIVÉ" if app.state.geo_enabled else "⚠️ Géospatial DÉSACTIVÉ"
        logger.info("=" * 60)
        logger.info(f"✅ API DÉMARRÉE AVEC SUCCÈS - {geo_status}")
        logger.info("=" * 60)
        
        yield  # 🎯 APPLICATION EN COURS D'EXÉCUTION
        
    except AppError as e:
        # Erreur critique : on loggue et on laisse l'application planter
        # (pour éviter de démarrer dans un état incohérent)
        logger.critical(f"💥 ERREUR FATALE AU DÉMARRAGE : {e.message}")
        logger.critical(f"Contexte : {e.context}")
        raise
        
    except Exception as e:
        # Erreur inattendue
        logger.critical("💥 ERREUR INATTENDUE AU DÉMARRAGE", exc_info=True)
        raise AppError(
            message="Erreur fatale inconnue au démarrage",
            context={"error_type": type(e).__name__},
            status_code=500,
        ) from e
    
    finally:
        # S'assure que la session est toujours fermée
        if db:
            try:
                db.close()
                logger.info("📡 Session DB fermée")
            except Exception as e:
                logger.warning(f"⚠️ Erreur lors de la fermeture de la session : {e}")
    
    # ========== PHASE D'ARRÊT ==========
    logger.info("=" * 60)
    logger.info("🛑 ARRÊT DE L'API EMPLOI SENEGAL")
    logger.info("=" * 60)
    
# Ferme le pool de connexions proprement
    try:
        if engine is not None:
            engine.dispose()   # ❗ NE PAS utiliser await
            logger.info("✔️ Engine SQLAlchemy correctement fermé.")
        else:
            logger.warning("⚠️ Engine SQLAlchemy est None, rien à fermer.")
    except Exception as e:
        logger.warning(f"Erreur lors du dispose() de l'engine : {e}")
    
    logger.info("✅ API arrêtée avec succès")




# Création de l'application FastAPI
app = FastAPI(
    title="Emploi Senegal API",
    description="API REST pour la plateforme d'emploi au Sénégal - Analyse, recommandations et visualisation",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

ALLOWED_ORIGINS = [
    "https://frontend-webscraping-pvfqjzk4q-cardans-projects-cb73ad15.vercel.app",
    "https://frontend-webscraping.vercel.app"  
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/import", status_code=201)
def import_admin_boundaries(
    clean: bool = Query(True, description="Vide la table avant import"),
    db: Session = Depends(get_db)
):
    """
    Importe les limites administratives depuis le dossier local `docs/SEN_adm/`.
    
    **Processus** :
    - Lit les fichiers `.shp` du dossier local
    - Importe les niveaux : region, departement, commune, arrondissement, quartier
    - Génère automatiquement le centroid et le geojson
    - Projection systématique en EPSG:4326 (WGS84)
    
    **Notes** :
    - Les fichiers doivent être dans `docs/SEN_adm/` à côté du dossier `service/`
    - Attend des fichiers nommés selon le pattern : `SEN_adm{0-4}.shp`
    - Nettoie la table par défaut (paramètre `clean=true`)
    """
    try:
        importer = AdminBoundaryImporterService()
        result = importer.import_all(db, clean=clean)
        stats = importer.verify_import(db)
        
        return {
            "status": "success",
            "message": f"{result['total_imported']} limites importées",
            "details": {
                "total_imported": result['total_imported'],
                "source_dir": result['source_dir'],
                "stats_by_level": stats,
                "clean_mode": clean
            }
        }
        
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail={
                "status": "error",
                "message": "Dossier 'docs/SEN_adm/' introuvable",
                "help": "Créez le dossier et placez les shapefiles dedans",
                "expected_path": str(e).split("'")[1] if "'" in str(e) else str(e)
            }
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "message": "Erreur inattendue lors de l'import",
                "details": str(e)
            }
        )

@app.get("/import/verify")
def verify_import(db: Session = Depends(get_db)):
    """
    Retourne le nombre de limites administratives importées par niveau.
    **Exemple de sortie** :
    ```json
    {
        "region": 14,
        "departement": 46,
        "commune": 557,
        "quartier": 808
    }
    ```
    """
    importer = AdminBoundaryImporterService()
    stats = importer.verify_import(db)
    
    return {
        "status": "success",
        "stats": stats,
        "total": sum(stats.values())
    }



# À AJOUTER dans votre fichier de routes analytics

@app.get("/analytics/temporal/daily")
async def get_daily_analytics(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """Récupère les statistiques quotidiennes des offres."""
    try:
        service = AnalyticsService()
        data = service.get_daily_trends(db, days)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Erreur dans get_daily_analytics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/analytics/jobs/top")
async def get_top_jobs_endpoint(
    period: str = Query("30d", regex="^(1d|7d|30d|90d|1y)$"),
    limit: int = Query(15, ge=5, le=50),
    db: Session = Depends(get_db)
):
    """Récupère les métiers les plus demandés."""
    try:
        service = AnalyticsService()
        data = service.get_top_job_titles(db, period, limit)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Erreur dans get_top_jobs: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/analytics/education/distribution")
async def get_education_analytics(
    period: str = Query("30d", regex="^(1d|7d|30d|90d|1y)$"),
    db: Session = Depends(get_db)
):
    """Récupère la répartition par niveau d'étude."""
    try:
        service = AnalyticsService()
        data = service.get_education_distribution(db, period)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Erreur dans get_education_analytics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



@app.post("/match-offers")
def match_offers_to_boundaries(
    level: str = Query(None, description="Limiter à un niveau (ex: 'quartier')"),
    threshold: int = Query(85, ge=50, le=100, description="Seuil de similarité (50-100)"),
    db: Session = Depends(get_db)
):
    """
    Mappe les offres d'emploi aux limites administratives par matching texte.
    
    **Exemple** :
    - Offre.location = "Dakar Plateau" → Quartier "Plateau" (score 100%)
    - Offre.location = "Dakar-Ponty" → Quartier "Dakar-Ponty" (score 95%)
    - Offre.location = "Poste à Dakar" → Région "Dakar" (score 85%)
    
    **Usage** :
    - Premier import : `POST /admin/match-offers?threshold=80`
    - Affiner manuellement les non-matchés
    """
    service = AdminBoundaryImporterService()
    
    try:
        result = service.match_offers_to_boundaries(db, level=level, similarity_threshold=threshold)
        return {
            "status": "success",
            "message": f"{result['matched']} offres matchées",
            "details": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/senegal/{level}")
def get_geojson_senegal(level: str, db: Session = Depends(get_db)):
    """Retourne les limites admin et offres au format GeoJSON."""
    service = CarteService(db)
    return service.get_choropleth_data(level)

@app.get("/offres")
def get_offres_geomap(
    level: str = None,  # Filtrer par niveau admin # type: ignore
    db: Session = Depends(get_db)
):
    """
    Retourne les offres avec leur limite administrative (pour choropleth).
    
    **Format** :
    ```json
    {
      "type": "FeatureCollection",
      "features": [
        {
          "type": "Feature",
          "geometry": { "type": "Polygon", "coordinates": [...] },
          "properties": {
            "name": "Dakar Plateau",
            "level": "quartier",
            "offer_count": 45,
            "offres": [...]  // Liste des offres dans cette zone
          }
        }
      ]
    }
    """
    query = db.query(SenegalAdminBoundary).filter(
        SenegalAdminBoundary.offer_count > 0
    )
    
    if level:
        query = query.filter_by(level=level)
    
    boundaries = query.all()
    
    features = []
    for boundary in boundaries:
        if boundary.geojson:
            # Récupérer les offres de cette limite
            offres = db.query(OffreEmploiBrute).filter_by(
                admin_boundary_id=boundary.id
            ).limit(10).all()
            
            features.append({
                "type": "Feature",
                "geometry": boundary.geojson,
                "properties": {
                    "id": boundary.id,
                    "name": boundary.name,
                    "level": boundary.level,
                    "offer_count": boundary.offer_count,
                    "offres": [
                        {
                            "id": str(o.id),
                            "title": o.title,
                            "company": o.company_name,
                            "contract": o.contract_type
                        }
                        for o in offres
                    ]
                }
            })
    
    return {
        "type": "FeatureCollection",
        "features": features,
        "total_boundaries": len(features)
    }


@app.get("/unmatched-offers")
def get_unmatched_offers(
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    Retourne les offres qui n'ont pas pu être matchées.
    Utile pour affiner le threshold ou corriger les noms.
    """
    offers = db.query(OffreEmploiBrute).filter(
        OffreEmploiBrute.admin_boundary_id.is_(None),
        OffreEmploiBrute.location.isnot(None)
    ).limit(limit).all()
    
    return {
        "total": len(offers),
        "locations": [o.location for o in offers]
    }


# Routes de base
@app.get("/", response_model=Dict[str, Any])
async def root():
    """Endpoint racine avec les informations de l'API."""
    return {
        "message": "Bienvenue sur l'API Emploi Dakar! 🌍",
        "version": "1.0.0",
        "description": "Plateforme intelligente d'analyse du marché de l'emploi au Sénégal",
        "documentation": "/docs",
        "health": "/health",
        "timestamp": datetime.now().isoformat()
    }



@app.get("/api/v1/carte/{level}", response_model=ChoroplethResponse)
def get_choropleth_map(
    level: AdminLevel,
    min_offers: int = Query(0, ge=0, description="Nombre minimum d'offres"),
    parent_name: Optional[str] = Query(None, description="Filtrer par parent (ex: 'Dakar')"),
    db: Session = Depends(get_db),
):
    """
    Récupère les données choroplèthe pour un niveau administratif avec navigation hiérarchique.
    
    - **level**: Niveau administratif (region, departement, commune, etc.)
    - **min_offers**: Nombre minimum d'offres pour afficher une zone
    - **parent_name**: Optionnel, filtre par parent pour navigation hiérarchique
    """
    try:
        service = CarteService(AdminBoundaryService())
        return service.get_choropleth_data(
            db=db,
            level=level,
            min_offers=min_offers,
            parent_name=parent_name
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/refresh-offer-counts")
def refresh_all_levels(db: Session = Depends(get_db)):
    """
    Recalcule les compteurs d'offres pour tous les niveaux (1 → 4).
    """
    levels = ["region", "departement", "arrondissement", "commune"]
    results = []
    admin_service = AdminBoundaryService()
    try:
        for lvl in levels:
            res = admin_service.refresh_offer_counts(db, lvl)
            results.append(res)

        return {
            "status": "success",
            "levels_processed": len(levels),
            "results": results
        }

    except Exception as e:
        raise AppError(
            message="Erreur durant le recalcul global des compteurs.",
            context={"error": str(e)},
            status_code=500
        )



@app.get("/health", response_model=Dict[str, Any])
async def health_check():
    """Endpoint de vérification de la santé de l'API."""
    try:
        # Vérifier la connexion à la base de données
        db = next(get_db())
        db.execute(text("SELECT 1"))
        
        # Vérifier les services
        services_status = {
            "database": "healthy",
            "job_service": "healthy" if hasattr(app.state, 'job_service') else "unhealthy",
            "analytics_service": "healthy" if hasattr(app.state, 'analytics_service') else "unhealthy",
            "recommendation_service": "healthy" if hasattr(app.state, 'recommendation_service') else "unhealthy"
        }
        
        return {
            "status": "healthy",
            "services": services_status,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")

# Routes pour les offres d'emploi
@app.get("/api/v1/jobs", response_model=PaginatedResponse[JobOfferResponse])
async def get_jobs(
    skip: int = Query(0, ge=0, description="Nombre d'offres à ignorer"),
    limit: int = Query(20, ge=1, le=100, description="Nombre d'offres à retourner"),
    location: Optional[str] = Query(None, description="Filtrer par localisation"),
    contract_type: Optional[str] = Query(None, description="Filtrer par type de contrat"),
    sector: Optional[str] = Query(None, description="Filtrer par secteur"),
    min_salary: Optional[int] = Query(None, ge=0, description="Salaire minimum"),
    max_salary: Optional[int] = Query(None, ge=0, description="Salaire maximum"),
    search: Optional[str] = Query(None, description="Recherche textuelle"),
    db=Depends(get_db)
):
    """Récupère une liste paginée d'offres d'emploi avec filtres."""
    try:
        params = JobSearchParams(
            skip=skip,
            limit=limit,
            location=location,
            contract_type=contract_type,
            sector=sector,
            min_salary=min_salary,
            max_salary=max_salary,
            search=search
        )
        
        result = app.state.job_service.search_jobs(db, params)
        return result
        
    except Exception as e:
        logger.error(f"Error fetching jobs: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de la récupération des offres")


job_servic = JobService()
@app.get("/api/v1/jobs/saved")
async def get_saved_jobs(
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user_id = user.user_id  # ⬅️ correction
    return job_servic.get_saved_jobs(db, user_id)

@app.get("/api/v1/jobs/{job_id}", response_model=JobOfferResponse)
async def get_job(job_id: str, db=Depends(get_db)):
    """Récupère une offre d'emploi spécifique par son ID."""
    try:
        job = app.state.job_service.get_job_by_id(db, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Offre d'emploi non trouvée")
        return job
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de la récupération de l'offre")
    
@app.post("/api/v1/jobs/saved")
async def save_job(
    payload: SaveJobRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user_id = user.user_id
    job_id = payload.job_id

    try:
        job_servic.save_job(db, user_id, job_id)
        return {"message": "Job saved successfully"}
    except Exception as e:
        logger.error(f"Error saving job: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de l'ajout du favori")

@app.get("/api/v1/jobs/stats/summary", response_model=Dict[str, Any])
async def get_jobs_summary(db=Depends(get_db)):
    """Récupère un résumé des statistiques des offres d'emploi."""
    try:
        stats = app.state.analytics_service.get_jobs_summary(db)
        return stats
        
    except Exception as e:
        logger.error(f"Error fetching job summary: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de la récupération du résumé")

# Routes pour l'analytics
@app.get("/api/v1/analytics/market-overview", response_model=JobAnalyticsResponse)
async def get_market_overview(
    period: str = Query("30d", description="Période d'analyse (7d, 30d, 90d, 1y)"),
    db=Depends(get_db)
):
    """Récupère une vue d'ensemble du marché de l'emploi."""
    try:
        overview = app.state.analytics_service.get_market_overview(db, period)
        return overview
        
    except Exception as e:
        logger.error(f"Error fetching market overview: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de l'analyse du marché")

@app.get("/api/v1/analytics/sectors", response_model=list[SectorAnalysis])
async def get_sector_analysis(
    period: str = Query("30d", description="Période d'analyse"),
    limit: int = Query(10, ge=1, le=50, description="Nombre de secteurs à retourner"),
    db=Depends(get_db)
):
    try:
        end_date = datetime.now()
        start_date = app.state.analytics_service.get_start_date(end_date, period)
        analysis = app.state.analytics_service.get_sector_analysis(db, start_date, end_date, limit)
        return analysis
    except Exception as e:
        logger.error(f"Error fetching sector analysis: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de l'analyse des secteurs")

@app.get("/api/v1/analytics/skills", response_model=List[SkillsAnalysis])
async def get_skills_analysis(
    period: str = Query("30d", description="Période d'analyse (ex: 7d, 30d, 90d)"),
    limit: int = Query(20, ge=1, le=100, description="Nombre de compétences à retourner"),
    db=Depends(get_db)
):
    """Analyse des compétences demandées."""
    try:
        end_date = datetime.now()
        start_date = app.state.analytics_service.get_start_date(end_date, period)
        analysis = app.state.analytics_service.get_skills_analysis(db, start_date, end_date, limit)
        return analysis  # 🔹 renvoie une liste de SkillsAnalysis
    except Exception as e:
        logger.error(f"Error fetching skills analysis: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de l'analyse des compétences")

    
@app.get("/api/v1/analytics/salary-trends", response_model=List[SalaryTrend])
async def get_salary_trends(
    period: str = Query("30d", description="Période d'analyse"),
    db=Depends(get_db)
):
    try:
        end_date = datetime.now()
        start_date = app.state.analytics_service.get_start_date(end_date, period)
        trends = app.state.analytics_service.get_salary_trends(db, start_date, end_date)
        return trends  # 🔹 c’est une liste de SalaryTrend
    except Exception as e:
        logger.error(f"Error fetching salary trends: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de l'analyse salariale")






from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from .database import get_db
from .models.database_models import User, UserProfile
from .models.api_models import UserProfileCreate, UserProfileResponse, UserCreate
from .utils.auth import create_access_token, verify_password, get_password_hash
from .services.user_service import UserService

user_service = UserService()

# ==================== ENDPOINT /register ====================
@app.post("/register", response_model=UserResponse)
async def register_user(user_in: UserCreate, db: Session = Depends(get_db)):
    """
    Inscription utilisateur.
    Crée un utilisateur et un profil vide.
    """
    # Vérifie si l'email existe déjà
    existing_user = db.query(User).filter(User.email == user_in.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email déjà utilisé")
    
    # Création de l'utilisateur
    user = User(
        email=user_in.email,
        hashed_password=get_password_hash(user_in.password)
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Création du profil associé
    profile = UserProfile(user_id=user.id)
    db.add(profile)
    db.commit()
    db.refresh(profile)

    # Convertis ton objet SQLAlchemy en dict
    user_dict = {
        "id": str(user.id),  # si UUID
        "email": user.email,
        "profile_id": str(user.profile.id) if user.profile else None
    }

    return UserResponse(**user_dict)




# ==================== LOGIN ====================
@app.post("/login")
async def login(username: str, password: str, db: Session = Depends(get_db)):
    """
    Authentification utilisateur.
    Renvoie un token JWT si les identifiants sont valides.
    """
    user = db.query(User).filter(User.email == username).first()
    if not user or not verify_password(password, str(user.hashed_password)):
        raise HTTPException(status_code=401, detail="Identifiants invalides")
    
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

# ==================== PROFIL UTILISATEUR ====================
@app.post("/api/v1/users/profile", response_model=UserProfileResponse)
async def create_user_profile(
    profile: UserProfileCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Crée ou met à jour le profil utilisateur.
    """
    user_profile = user_service.create_or_update_profile(db, user.user_id, profile)
    return user_profile




@app.get("/api/v1/users/profile/recu", response_model=UserProfileResponse)
async def get_user_profile(
    user: UserProfile = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Récupère le profil utilisateur.
    """
    # ✅ user est déjà le UserProfile
    if not user:
        raise HTTPException(status_code=404, detail="Profil utilisateur non trouvé")

    # Récupérer l'email via la relation user
    user_account = db.query(User).filter(User.id == user.user_id).first()
    if not user_account:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")

    return UserProfileResponse(
        id=UUID(str(user.id)),
        user_id=UUID(str(user.user_id)),
        email=user_account.email, # type: ignore
        first_name=cast(Optional[str], user.first_name),
        last_name=cast(Optional[str], user.last_name),
        phone=cast(Optional[str], user.phone),
        location=cast(Optional[str], user.location),
        experience_years=cast(Optional[int], user.experience_years),
        education_level=cast(Optional[str], user.education_level),
        skills=cast(Optional[List[str]], user.skills),
        preferred_contract_type=cast(Optional[List[str]], user.preferred_contract_type),
        preferred_salary_min=cast(Optional[int], user.preferred_salary_min),
        preferred_salary_max=cast(Optional[int], user.preferred_salary_max),
        cv_url=cast(Optional[str], user.cv_url),
        created_at=cast(datetime, user.created_at),
        updated_at=cast(datetime, user.updated_at),
    )




@app.post("/api/v1/recommendations", response_model=RecommendationResponse)
async def get_job_recommendations(
    request: RecommendationRequest,
    user=Depends(get_current_user),
    db=Depends(get_db)
):
    """Obtient des recommandations d'emploi personnalisées."""
    try:
        # Retournez l'objet Pydantic DIRECTEMENT, sans .dict(), sans tuple()
        return app.state.recommendation_service.get_recommendations(db, str(user.id), request)
    except Exception as e:
        logger.error(f"Error fetching recommendations: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de la génération des recommandations")

@app.post("/api/v1/recommendations/cv-match", response_model=RecommendationResponse)
async def match_cv_with_jobs(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db=Depends(get_db)
):
    """Match un CV avec les offres d'emploi disponibles."""
    try:
        if not file.content_type or file.content_type not in ["application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]:
            raise HTTPException(status_code=400, detail="Format de fichier non supporté")
        
        file_path = await app.state.file_service.save_upload_file(file)
        cv_text = await app.state.file_service.extract_text_from_file(file_path)
        recommendations = app.state.recommendation_service.match_cv_with_jobs(db, cv_text, str(user.id))
        await app.state.file_service.cleanup_file(file_path)
        
        # Retournez l'objet Pydantic DIRECTEMENT
        return recommendations
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error matching CV: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors du matching du CV")



@app.get("/api/v1/users/job-alerts")
async def get_job_alerts(
    user=Depends(get_current_user),
    db=Depends(get_db)
):
    """Récupère les alertes d'emploi pour l'utilisateur."""
    try:
        alerts = app.state.user_service.get_job_alerts(db, user.id)
        return alerts
        
    except Exception as e:
        logger.error(f"Error fetching job alerts: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de la récupération des alertes")

# Routes pour les statistiques
@app.get("/api/v1/stats/dashboard", response_model=JobStatisticsResponse)
async def get_dashboard_stats(db=Depends(get_db)):
    """Récupère les statistiques pour le tableau de bord."""
    try:
        stats = app.state.analytics_service.get_dashboard_stats(db)
        return stats
        
    except Exception as e:
        logger.error(f"Error fetching dashboard stats: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de la récupération des statistiques")

@app.get("/api/v1/stats/geographic" )
async def get_geographic_stats(db=Depends(get_db)):
    """Récupère les statistiques géographiques des offres."""
    try:
        stats = app.state.analytics_service.get_geographic_distribution(db)
        return stats
        
    except Exception as e:
        logger.error(f"Error fetching geographic stats: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de la récupération des statistiques géographiques")

# Routes pour le téléchargement de données
@app.get("/api/v1/export/jobs")
async def export_jobs(
    format: str = Query("csv", description="Format d'export (csv, json, xlsx)"),
    db=Depends(get_db)
):
    """Exporte les données des offres d'emploi."""
    try:
        file_path = await app.state.file_service.export_jobs_data(db, format)
        return {"download_url": f"/api/v1/download/{os.path.basename(file_path)}"}
        
    except Exception as e:
        logger.error(f"Error exporting jobs: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de l'export des données")

# Gestion d'erreurs
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Gestionnaire d'exceptions global."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Une erreur interne est survenue"}
    )

@app.get('/favicon.ico')
async def get_favicon():
    """Handle favicon request."""
    static_path = Path(__file__).parent / "static"
    favicon_path = static_path / "favicon.ico"
    
    if not static_path.exists():
        static_path.mkdir(parents=True, exist_ok=True)
        
    if not favicon_path.exists():
        return Response(status_code=204)
        
    return FileResponse(favicon_path)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )


"""
Routes FastAPI pour les analytics avancés.
Intégration du nouveau AdvancedAnalyticsService.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging


from .services.advanced_analytics_service import AdvancedAnalyticsService

logger = logging.getLogger(__name__)


# Initialiser le service
analytics_service = AdvancedAnalyticsService()


# ==================== ANALYSE COMPLÈTE ====================

@app.get("/api/v1/analytics/complete", response_model=FullAnalyticsResponse)
async def get_complete_analytics(
    period: str = Query("90d", description="Période d'analyse (7d, 30d, 90d, 180d, 1y)"),
    db: Session = Depends(get_db)
):
    """
    🎯 ENDPOINT PRINCIPAL - Récupère TOUTES les analyses en un seul appel.
    
    Inclut:
    - Dashboard avec KPIs et tendances
    - Analyse géographique
    - Heatmap compétences × secteurs
    - Salaires par expérience
    - Top entreprises qui recrutent
    - Évolution des types de contrat
    - Taux de croissance du marché
    
    Parfait pour charger tout le dashboard en une fois !
    """
    try:
        logger.info(f"🔍 Analyse complète demandée pour la période: {period}")
        result = analytics_service.get_complete_analytics(db, period)
        logger.info(f"✅ Analyse complète générée avec succès")
        return result
    except Exception as e:
        logger.error(f"❌ Erreur analyse complète: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'analyse: {str(e)}")


# ==================== DASHBOARD & MÉTRIQUES ====================

@app.get("/api/v1/analytics/dashboard", response_model=DashboardStats)
async def get_enhanced_dashboard(
    period: str = Query("90d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    📊 Dashboard enrichi avec métriques clés et tendances.
    
    Inclut:
    - Total offres, entreprises, localisations
    - Offres du mois et du jour
    - Top 10 secteurs avec croissance
    - Top 20 compétences avec tendances
    - Distribution contrats et expérience
    - Tendance mensuelle (12 mois)
    """
    try:
        start_date, end_date = analytics_service._get_period_bounds(period)
        result = analytics_service.get_enhanced_dashboard(db, start_date, end_date)
        return result
    except Exception as e:
        logger.error(f"Erreur dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analytics/evolution-rates", response_model=Dict[str, Any])
async def get_market_evolution_rates(
    period: str = Query("90d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    📈 Taux d'évolution du marché (comparaison avec période précédente).
    
    Compare:
    - Croissance des offres
    - Croissance des entreprises actives
    - Diversité géographique
    - Diversité sectorielle
    - Diversité des compétences
    - Indicateur de santé du marché
    """
    try:
        start_date, end_date = analytics_service._get_period_bounds(period)
        result = analytics_service.get_market_evolution_rates(db, start_date, end_date)
        return result
    except Exception as e:
        logger.error(f"Erreur taux évolution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ANALYSES GÉOGRAPHIQUES ====================

@app.get("/api/v1/analytics/geographic", response_model=List[GeographicStats])
async def get_geographic_analysis(
    period: str = Query("90d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    🗺️ Analyse géographique détaillée avec coordonnées GPS.
    
    Pour chaque région:
    - Nombre d'offres et pourcentage
    - Top secteurs
    - Salaires moyens (si disponibles)
    - Coordonnées GPS pour cartographie
    """
    try:
        start_date, end_date = analytics_service._get_period_bounds(period)
        result = analytics_service.get_geographic_analysis(db, start_date, end_date)
        return result
    except Exception as e:
        logger.error(f"Erreur analyse géographique: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analytics/regional-benchmark", response_model=Dict[str, Any])
async def get_regional_benchmark(
    period: str = Query("180d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    ⚖️ Benchmark inter-régional du Sénégal.
    
    Compare les 14 régions sur:
    - Volume d'offres
    - Nombre d'entreprises
    - Secteur dominant
    - Part de marché
    """
    try:
        result = analytics_service.get_regional_benchmark(db, period)
        return result
    except Exception as e:
        logger.error(f"Erreur benchmark régional: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ANALYSES SECTORIELLES ====================

@app.get("/api/v1/analytics/sectors", response_model=List[Dict[str, Any]])
async def get_sector_analysis(
    period: str = Query("90d", description="Période d'analyse"),
    limit: int = Query(15, ge=1, le=50, description="Nombre de secteurs"),
    db: Session = Depends(get_db)
):
    """
    📊 Analyse sectorielle détaillée.
    
    Pour chaque secteur:
    - Nombre d'offres et pourcentage
    - Salaires moyens
    - Top 5 compétences demandées
    """
    try:
        start_date, end_date = analytics_service._get_period_bounds(period)
        result = analytics_service.get_sector_analysis(db, start_date, end_date, limit)
        return result
    except Exception as e:
        logger.error(f"Erreur analyse secteurs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analytics/sectors/momentum", response_model=List[Dict[str, Any]])
async def get_sector_momentum(
    period: str = Query("180d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    🚀 Momentum sectoriel - Identifie les secteurs en accélération.
    
    Calcule l'accélération de croissance de chaque secteur.
    Parfait pour identifier les opportunités émergentes !
    """
    try:
        result = analytics_service.get_sector_momentum(db, period)
        return result
    except Exception as e:
        logger.error(f"Erreur momentum secteurs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analytics/sectors/contracts", response_model=List[Dict[str, Any]])
async def get_contract_by_sector(
    period: str = Query("90d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    📊 Distribution des types de contrat par secteur.
    Parfait pour un graphique en barres empilées.
    """
    try:
        start_date, end_date = analytics_service._get_period_bounds(period)
        result = analytics_service.get_contract_type_by_sector(db, start_date, end_date)
        return result
    except Exception as e:
        logger.error(f"Erreur contrats par secteur: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analytics/sectors/experience", response_model=List[Dict[str, Any]])
async def get_experience_by_sector(
    period: str = Query("90d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    📊 Distribution des niveaux d'expérience par secteur.
    """
    try:
        start_date, end_date = analytics_service._get_period_bounds(period)
        result = analytics_service.get_experience_level_distribution_by_sector(db, start_date, end_date)
        return result
    except Exception as e:
        logger.error(f"Erreur expérience par secteur: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/analytics/sectors/compare", response_model=Dict[str, Any])
async def compare_sectors(
    sectors: List[str],
    period: str = Query("90d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    ⚖️ Compare plusieurs secteurs sur différentes dimensions.
    
    Body: { "sectors": ["IT", "Finance", "Santé"] }
    """
    try:
        start_date, end_date = analytics_service._get_period_bounds(period)
        result = analytics_service.get_sector_comparison(db, sectors, start_date, end_date)
        return result
    except Exception as e:
        logger.error(f"Erreur comparaison secteurs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ANALYSES DE COMPÉTENCES ====================

@app.get("/api/v1/analytics/skills", response_model=List[Dict[str, Any]])
async def get_skills_analysis(
    period: str = Query("90d", description="Période d'analyse"),
    limit: int = Query(30, ge=1, le=100, description="Nombre de compétences"),
    db: Session = Depends(get_db)
):
    """
    🔥 Analyse des compétences les plus demandées.
    
    Pour chaque compétence:
    - Nombre de mentions
    - Pourcentage d'apparition
    - Secteurs associés
    """
    try:
        start_date, end_date = analytics_service._get_period_bounds(period)
        result = analytics_service.get_skills_analysis(db, start_date, end_date, limit)
        return result
    except Exception as e:
        logger.error(f"Erreur analyse compétences: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analytics/skills/emerging", response_model=List[Dict[str, Any]])
async def get_emerging_skills(
    period: str = Query("90d", description="Période d'analyse"),
    growth_threshold: float = Query(50.0, description="Seuil de croissance minimum (%)"),
    db: Session = Depends(get_db)
):
    """
    🌟 Compétences émergentes - Forte croissance récente.
    
    Identifie les compétences qui explosent en demande.
    Parfait pour orienter les formations !
    """
    try:
        result = analytics_service.get_emerging_skills(db, period, growth_threshold)
        return result
    except Exception as e:
        logger.error(f"Erreur compétences émergentes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analytics/skills/co-occurrence", response_model=List[Dict[str, Any]])
async def get_skills_co_occurrence(
    period: str = Query("90d", description="Période d'analyse"),
    min_count: int = Query(5, description="Nombre minimum d'occurrences"),
    db: Session = Depends(get_db)
):
    """
    🔗 Co-occurrence des compétences.
    
    Identifie quelles compétences sont souvent demandées ensemble.
    Parfait pour un graphe de réseau !
    """
    try:
        start_date, end_date = analytics_service._get_period_bounds(period)
        result = analytics_service.get_skills_co_occurrence(db, start_date, end_date, min_count)
        return result
    except Exception as e:
        logger.error(f"Erreur co-occurrence: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analytics/skills/heatmap", response_model=List[HeatmapData])
async def get_skills_sector_heatmap(
    period: str = Query("90d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    🔥 Heatmap compétences × secteurs.
    
    Matrice montrant quelles compétences sont demandées dans quels secteurs.
    Parfait pour une heatmap interactive !
    """
    try:
        start_date, end_date = analytics_service._get_period_bounds(period)
        result = analytics_service.get_skills_sector_heatmap(db, start_date, end_date)
        return result
    except Exception as e:
        logger.error(f"Erreur heatmap: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analytics/skills/saturation", response_model=List[Dict[str, Any]])
async def get_skill_saturation_index(
    period: str = Query("90d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    📊 Indice de saturation des compétences.
    
    Identifie:
    - Compétences sur-demandées
    - Compétences rares/opportunités
    - Score d'opportunité pour chaque compétence
    """
    try:
        start_date, end_date = analytics_service._get_period_bounds(period)
        result = analytics_service.get_skill_saturation_index(db, start_date, end_date)
        return result
    except Exception as e:
        logger.error(f"Erreur saturation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/analytics/skills/value-analysis", response_model=Dict[str, Any])
async def get_skill_value_analysis(
    skills: List[str],
    period: str = Query("180d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    💎 Analyse de la valeur marchande des compétences.
    
    Pour chaque compétence:
    - Demande du marché
    - Score de valeur (0-100)
    - Diversité sectorielle
    - Impact salarial
    
    Body: { "skills": ["Python", "React", "SQL"] }
    """
    try:
        result = analytics_service.get_skill_value_analysis(db, skills, period)
        return result
    except Exception as e:
        logger.error(f"Erreur valeur compétences: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ANALYSES TEMPORELLES ====================

@app.get("/api/v1/analytics/temporal/monthly-trends", response_model=List[Dict[str, Any]])
async def get_monthly_trends(
    days: int = Query(365, description="Nombre de jours à analyser"),
    db: Session = Depends(get_db)
):
    """
    📅 Tendances mensuelles sur N jours.
    """
    try:
        result = analytics_service._get_monthly_trend(db, days)
        return result
    except Exception as e:
        logger.error(f"Erreur tendances mensuelles: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analytics/temporal/seasonal", response_model=Dict[str, Any])
async def get_seasonal_trends(
    years: int = Query(2, description="Nombre d'années à analyser"),
    db: Session = Depends(get_db)
):
    """
    🌡️ Analyse des tendances saisonnières.
    
    Identifie les pics de recrutement annuels (par mois).
    Parfait pour un graphique radar !
    """
    try:
        result = analytics_service.get_seasonal_trends(db, years)
        return result
    except Exception as e:
        logger.error(f"Erreur tendances saisonnières: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analytics/temporal/day-of-week", response_model=List[Dict[str, Any]])
async def get_day_of_week_patterns(
    period: str = Query("90d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    📆 Patterns par jour de la semaine.
    
    Identifie les meilleurs jours pour publier des offres.
    """
    try:
        result = analytics_service.get_day_of_week_patterns(db, period)
        return result
    except Exception as e:
        logger.error(f"Erreur patterns jour: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analytics/temporal/velocity", response_model=Dict[str, Any])
async def get_posting_velocity(
    period: str = Query("90d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    ⚡ Vélocité de publication des offres.
    
    Analyse combien d'offres sont publiées par jour/semaine.
    Identifie les pics d'activité.
    """
    try:
        result = analytics_service.get_job_posting_velocity(db, period)
        return result
    except Exception as e:
        logger.error(f"Erreur vélocité: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analytics/temporal/contract-evolution", response_model=List[ContractTypeEvolution])
async def get_contract_evolution(
    period: str = Query("180d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    📈 Évolution des types de contrat par mois.
    Parfait pour un graphique en aires empilées !
    """
    try:
        start_date, end_date = analytics_service._get_period_bounds(period)
        result = analytics_service.get_contract_type_evolution(db, start_date, end_date)
        return result
    except Exception as e:
        logger.error(f"Erreur évolution contrats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analytics/temporal/time-series", response_model=Dict[str, Any])
async def get_time_series_comparison(
    metrics: List[str] = Query(['offers', 'companies', 'sectors'], description="Métriques à comparer"),
    periods: List[str] = Query(['30d', '90d', '180d', '365d'], description="Périodes à analyser"),
    db: Session = Depends(get_db)
):
    """
    📊 Comparaison de séries temporelles.
    
    Compare l'évolution de différentes métriques sur plusieurs périodes.
    Parfait pour des graphiques multi-lignes !
    """
    try:
        result = analytics_service.get_time_series_comparison(db, metrics, periods)
        return result
    except Exception as e:
        logger.error(f"Erreur séries temporelles: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ENTREPRISES ====================

@app.get("/api/v1/analytics/companies/top-hiring", response_model=List[CompanyHiringStats])
async def get_top_hiring_companies(
    period: str = Query("90d", description="Période d'analyse"),
    limit: int = Query(20, ge=1, le=100, description="Nombre d'entreprises"),
    db: Session = Depends(get_db)
):
    """
    🏢 Top entreprises qui recrutent le plus.
    """
    try:
        start_date, end_date = analytics_service._get_period_bounds(period)
        result = analytics_service.get_top_hiring_companies(db, start_date, end_date, limit)
        return result
    except Exception as e:
        logger.error(f"Erreur top entreprises: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analytics/companies/{company_name}/insights", response_model=Dict[str, Any])
async def get_company_insights(
    company_name: str,
    period: str = Query("365d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    🔍 Insights détaillés sur une entreprise spécifique.
    
    Analyse complète:
    - Secteurs de recrutement
    - Compétences recherchées
    - Types de contrat
    - Niveaux d'expérience
    - Tendance de recrutement
    """
    try:
        result = analytics_service.get_company_insights(db, company_name, period)
        return result
    except Exception as e:
        logger.error(f"Erreur insights entreprise: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analytics/companies/sources-performance", response_model=List[Dict[str, Any]])
async def get_source_performance(
    period: str = Query("90d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    📊 Performance des sources de scraping.
    
    Analyse la qualité et le volume de données de chaque spider.
    Utile pour optimiser la collecte de données !
    """
    try:
        start_date, end_date = analytics_service._get_period_bounds(period)
        result = analytics_service.get_source_performance(db, start_date, end_date)
        return result
    except Exception as e:
        logger.error(f"Erreur performance sources: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ANALYSES POUR CANDIDATS ====================

@app.post("/api/v1/analytics/career/path-analysis", response_model=Dict[str, Any])
async def get_career_path_analysis(
    current_skills: List[str],
    target_sector: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    🎯 Analyse de parcours de carrière personnalisée.
    
    Suggère:
    - Compétences à acquérir
    - Progression de carrière possible
    - Secteurs d'opportunités
    
    Body: { "current_skills": ["Python", "SQL"], "target_sector": "IT" }
    """
    try:
        result = analytics_service.get_career_path_analysis(db, current_skills, target_sector)
        return result
    except Exception as e:
        logger.error(f"Erreur analyse carrière: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analytics/career/job-clusters", response_model=List[Dict[str, Any]])
async def get_similar_job_clusters(
    period: str = Query("180d", description="Période d'analyse"),
    min_cluster_size: int = Query(3, description="Taille minimum des clusters"),
    db: Session = Depends(get_db)
):
    """
    🔗 Clusters d'emplois similaires.
    
    Identifie des groupes d'emplois avec compétences communes.
    Utile pour les recommandations !
    """
    try:
        start_date, end_date = analytics_service._get_period_bounds(period)
        result = analytics_service.get_similar_job_clusters(db, start_date, end_date, min_cluster_size)
        return result
    except Exception as e:
        logger.error(f"Erreur clusters: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== SALAIRES ====================

@app.get("/api/v1/analytics/salary/by-experience", response_model=List[SalaryByExperience])
async def get_salary_by_experience(
    period: str = Query("180d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    💰 Salaires par niveau d'expérience.
    
    Note: Peut contenir des valeurs None si peu de données salariales.
    """
    try:
        start_date, end_date = analytics_service._get_period_bounds(period)
        result = analytics_service.get_salary_by_experience(db, start_date, end_date)
        return result
    except Exception as e:
        logger.error(f"Erreur salaires par expérience: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/analytics/salary/trends", response_model=List[Dict[str, Any]])
async def get_salary_trends(
    period: str = Query("365d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    📊 Tendances salariales mensuelles.
    """
    try:
        start_date, end_date = analytics_service._get_period_bounds(period)
        result = analytics_service.get_salary_trends(db, start_date, end_date)
        return result
    except Exception as e:
        logger.error(f"Erreur tendances salariales: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== QUALITÉ & RAPPORTS ====================

@app.get("/api/v1/analytics/quality/data-report", response_model=Dict[str, Any])
async def get_data_quality_report(db: Session = Depends(get_db)):
    """
    📊 Rapport sur la qualité des données collectées.
    
    Analyse:
    - Complétude des champs
    - Taux d'enrichissement NLP
    - Qualité par source
    """
    try:
        result = analytics_service.get_data_quality_report(db)
        return result
    except Exception as e:
        logger.error(f"Erreur rapport qualité: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.router.get("/api/v1/analytics/reports/executive-summary", response_model=Dict[str, Any])
async def get_executive_summary(
    period: str = Query("90d", description="Période d'analyse"),
    db: Session = Depends(get_db)
):
    """
    📋 Résumé exécutif complet du marché.
    
    Génère un rapport avec:
    - KPIs principaux
    - Insights automatiques
    - Top opportunités
    - Recommandations stratégiques
    
    Parfait pour des exports PDF ou présentations !
    """
    try:
        result = analytics_service.generate_executive_summary(db, period)
        return result
    except Exception as e:
        logger.error(f"Erreur résumé exécutif: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.router.get("/api/v1/analytics/reports/comprehensive", response_model=Dict[str, Any])
async def export_comprehensive_report(
    period: str = Query("90d", description="Période d'analyse"),
    format: str = Query("json", description="Format d'export (json)"),
    db: Session = Depends(get_db)
):
    """
    📦 EXPORT COMPLET - Toutes les analyses en un seul rapport.
    
    Inclut ABSOLUMENT TOUTES les analyses disponibles :
    - Vue d'ensemble
    - Analyses sectorielles
    - Compétences (toutes les dimensions)
    - Géographie
    - Entreprises
    - Tendances temporelles
    - Salaires
    - Qualité des données
    - Configurations de visualisation
    
    Format JSON prêt pour export PDF/Excel ou intégration frontend.
    Parfait pour des rapports périodiques automatisés !
    """
    try:
        result = analytics_service.export_comprehensive_report(db, period, format)
        return result
    except Exception as e:
        logger.error(f"Erreur export complet: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== VISUALISATIONS ====================

@app.get("/api/v1/analytics/visualizations/config/{analysis_type}", response_model=Dict[str, Any])
async def get_visualization_config(analysis_type: str):
    """
    🎨 Configuration recommandée pour les visualisations.
    
    Retourne le type de graphique optimal pour chaque analyse:
    - Type de chart (bar, line, heatmap, etc.)
    - Palette de couleurs
    - Librairie recommandée
    
    Types disponibles:
    - market_overview
    - sector_analysis
    - skills_heatmap
    - geographic_distribution
    - contract_evolution
    - skill_co_occurrence
    - seasonal_trends
    - company_ranking
    - skill_value
    - experience_distribution
    """
    try:
        result = analytics_service.get_visualization_config(analysis_type)
        return result
    except Exception as e:
        logger.error(f"Erreur config visualisation: {e}")
        raise HTTPException(status_code=500, detail=str(e))







from app.core.exceptions import AppError, ValidationError

svc = AdminBoundaryService()

@app.get(
    "/boundaries",
    response_model=List[AdminBoundaryOut],
    summary="Récupère les limites administratives",
    description="Retourne les limites pour un niveau donné (quartier, commune, etc.)"
)
def read_boundaries(
    level: str = Query(..., description="Niveau administratif"),
    db: Session = Depends(get_db),
):
    """
    Endpoint principal avec gestion d'erreurs centralisée.
    """
    try:
        return svc.get_boundaries(db, level)
    except ValidationError as e:
        # 400 Bad Request
        raise HTTPException(status_code=400, detail=e.message)
    except AppError as e:
        # Erreurs métier (500, 503, etc.)
        raise HTTPException(status_code=e.status_code, detail=e.message)

@app.post(
    "/refresh",
    summary="Recalcule les compteurs d'offres",
    description="Opération longue, peut prendre plusieurs minutes"
)
def refresh_counts(
    level: str = Query(...),
    db: Session = Depends(get_db),  
):
    """
    Endpoint pour recalculer les compteurs (nécessite droits admin).
    """
    try:
        result = svc.refresh_offer_counts(db, level)
        return {"status": "success", "detail": result}
    except AppError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)