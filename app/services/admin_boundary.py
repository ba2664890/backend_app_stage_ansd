# backend/app/services/admin_boundary.py

import logging
import time
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from sqlalchemy.exc import OperationalError, DBAPIError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from app.core.constants import AdminLevel
from app.db.init_postgis import PostGISManager
from app.models.database_models import SenegalAdminBoundary, OffreEmploiBrute
from app.models.api_models import AdminBoundaryOut
from app.core.exceptions import AppError, NotFoundError, ValidationError
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)


class AdminBoundaryService:
    """
    Service pour gérer les limites administratives avec :
    - Retry automatique sur erreurs réseau
    - Timeout sur les requêtes longues
    - Gestion fine des erreurs PostGIS
    """
    
    def __init__(self):
        self.postgis_manager = PostGISManager()
    
    # ============================================================
    # DECORATOR : Retry sur erreurs réseau (Neon)
    # ============================================================
    @staticmethod
    def with_network_retry(func):
        """Décorateur pour retry sur OperationalError (problèmes réseau)."""
        return retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type(OperationalError),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )(func)
    
    # ============================================================
    # METHODES PRINCIPALES
    # ============================================================
    
    @with_network_retry
    def get_boundaries(self, db: Session, level: str) -> List[AdminBoundaryOut]:
        """
        Récupère les limites administratives avec vérification PostGIS.
        
        Args:
            db: Session SQLAlchemy
            level: Niveau admin ('quartier', 'commune', etc.)
        
        Returns:
            Liste des limites avec leurs métadonnées
        
        Raises:
            AppError: Si PostGIS manque ou erreur réseau persistante
            ValidationError: Si level invalide
        """
        # Validation du level
        valid_levels = {"region", "departement", "commune", "arrondissement", "quartier"}
        if level not in valid_levels:
            raise ValidationError(
                field="level",
                reason=f"Valeur '{level}' non autorisée",
                context={"valid_values": list(valid_levels)},
            )
        
        # Vérifie PostGIS (une fois par session)
        self.postgis_manager.ensure_postgis(db)
        
        try:
            # Requête principale avec timeout
            query = db.query(SenegalAdminBoundary).filter_by(level=level)
            
            # Timeout de 30s pour éviter blocages (Neon peut être lent)
            boundaries = query.execution_options(timeout=30).all()
            
            if not boundaries:
                logger.warning(f"Aucune limite trouvée pour level='{level}'")
            
            return [AdminBoundaryOut.from_orm(b) for b in boundaries]
            
        except OperationalError as e:
            # Erreur réseau même après retry
            logger.error(f"❌ Erreur réseau persistante : {e}")
            raise AppError(
                message="Impossible de se connecter à la base de données",
                context={"network_error": True, "level": level},
                status_code=503,
            ) from e
            
        except DBAPIError as e:
            # Erreur SQL (ex: PostGIS mal installé)
            logger.exception("❌ Erreur SQL lors de la récupération des limites")
            raise AppError(
                message="Erreur de requête géospatiale",
                context={"postgis_error": True, "sql_message": str(e.orig)},
                status_code=500,
            ) from e

    # ------------------------------------------------------------
    # Normalisation des noms
    # ------------------------------------------------------------
    def _normalize_name(self, name: Optional[str]) -> str:
        import unicodedata

        if not isinstance(name, str):
            return ""

        # Garder seulement avant la virgule → "Dakar, Sénégal" → "Dakar"
        if "," in name:
            name = name.split(",")[0]

        name = name.lower().strip()

        # Supprimer accents
        name = "".join(
            c for c in unicodedata.normalize("NFD", name)
            if unicodedata.category(c) != "Mn"
        )

        # Remplacer séparateurs
        name = name.replace("-", " ").replace("_", " ")

        # Compacter espaces
        return " ".join(name.split())


    from sqlalchemy import func
    from sqlalchemy.sql import expression
    from typing import Optional

    @with_network_retry
    def refresh_offer_counts(self, db: Session, level: str) -> Dict[str, Any]:
        """
        Recalcule les compteurs d'offres d'emploi pour un niveau administratif donné.
        Utilise la session fournie par FastAPI (pas de db.begin()).
        """

        self.postgis_manager.ensure_postgis(db)

        try:
            logger.info(f"🔄 Début du refresh des compteurs pour level={level}")

            boundaries = (
                db.query(SenegalAdminBoundary)
                .filter(SenegalAdminBoundary.level == level)
                .all()
            )

            if not boundaries:
                logger.warning(f"⚠️ Aucun boundary trouvé pour level='{level}'")
                return {
                    "status": "success",
                    "updated_rows": 0,
                    "level": level,
                    "total_boundaries": 0,
                }

            total_updated = 0

            for boundary in boundaries:

                # --- 🔥 Normalisation Python ---
                normalized_boundary_name = self._normalize_name(str(boundary.name))

                # --- 🔥 Normalisation SQL ÉQUIVALENTE ---
                sql_location_normalized = func.lower(
                    func.unaccent(
                        func.split_part(OffreEmploiBrute.location, ",", 1)  # -> avant virgule
                    )
                )

                sql_location_normalized = func.replace(sql_location_normalized, "-", " ")
                sql_location_normalized = func.replace(sql_location_normalized, "_", " ")

                # Nettoyage espaces multiples
                sql_location_normalized = func.regexp_replace(
                    sql_location_normalized, r"\s+", " ", "g"
                )

                # Trim
                sql_location_normalized = func.trim(sql_location_normalized)

                # ---- Calcul du count ----
                count = (
                    db.query(func.sum(func.coalesce(OffreEmploiBrute.nb_positions, 1)))
                    .filter(sql_location_normalized == normalized_boundary_name)
                    .scalar() or 0
                )

                # ---- Mise à jour si différent ----
                if boundary.offer_count != count:
                    boundary.offer_count = count
                    total_updated += 1

            if total_updated > 0:
                db.commit()
                logger.info(f"✅ {total_updated} compteurs mis à jour pour level={level}")
            else:
                logger.info("ℹ️ Aucun changement")

            return {
                "status": "success",
                "updated_rows": total_updated,
                "level": level,
                "total_boundaries": len(boundaries),
            }

        except OperationalError as e:
            db.rollback()
            raise AppError(
                message="Timeout ou problème réseau.",
                context={"level": level},
                status_code=503,
            ) from e

        except Exception as e:
            db.rollback()
            raise AppError(
                message="Erreur inattendue.",
                context={"error": str(e), "level": level},
                status_code=500,
            ) from e


        
    @with_network_retry
    def get_boundary_by_name(self, db: Session, name: str, level: str) -> AdminBoundaryOut:
        """
        Récupère une limite spécifique par son nom.
        Utile pour les tests et le débugging.
        """
        self.postgis_manager.ensure_postgis(db)
        
        boundary = db.query(SenegalAdminBoundary).filter_by(
            name=name,
            level=level
        ).first()
        
        if not boundary:
            raise NotFoundError(
                resource="AdminBoundary",
                identifier=f"{level}/{name}",
                context={"search_params": {"name": name, "level": level}},
            )
        
        return AdminBoundaryOut.from_orm(boundary)

    @with_network_retry
    def get_boundary_analytics_by_name(self, db: Session, name: str, level: AdminLevel) -> Dict[str, Any]:
        """
        Récupère les statistiques détaillées (entreprises, compétences) pour une localité par son nom.
        """
        # Trouver la limite
        boundary = db.query(SenegalAdminBoundary).filter(
            func.lower(SenegalAdminBoundary.name) == name.lower(),
            SenegalAdminBoundary.level == level.value
        ).first()

        if not boundary:
            # Fallback : recherche par nom uniquement si level est imprécis
            boundary = db.query(SenegalAdminBoundary).filter(
                func.lower(SenegalAdminBoundary.name) == name.lower()
            ).first()

        if not boundary:
            return {"top_companies": [], "top_skills": [], "message": "Location not found"}

        # Top Recruteurs
        top_companies = db.query(
            OffreEmploiBrute.company_name,
            func.count(OffreEmploiBrute.id).label('count')
        ).filter(
            OffreEmploiBrute.admin_boundary_id == boundary.id,
            OffreEmploiBrute.company_name.isnot(None)
        ).group_by(OffreEmploiBrute.company_name).order_by(func.desc('count')).limit(10).all()

        # Écosystème Compétences
        top_skills = db.query(
            func.unnest(OffreEmploiEnrichie.extracted_skills).label('skill'),
            func.count(OffreEmploiEnrichie.id).label('count')
        ).join(
            OffreEmploiBrute, OffreEmploiEnrichie.offre_id == OffreEmploiBrute.id
        ).filter(
            OffreEmploiBrute.admin_boundary_id == boundary.id,
            OffreEmploiEnrichie.extracted_skills.isnot(None)
        ).group_by('skill').order_by(func.desc('count')).limit(15).all()

        return {
            "location": boundary.name,
            "level": boundary.level,
            "top_companies": [{"company": c[0], "offers": c[1]} for c in top_companies],
            "top_skills": [{"skill": s[0], "count": s[1]} for s in top_skills]
        }
    
# backend/app/services/admin_boundary.py


# backend/app/services/carte_service.py

import logging
import json
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.models.database_models import SenegalAdminBoundary, OffreEmploiBrute, OffreEmploiEnrichie, UserProfile, User, UserRole
from app.models.api_models import ChoroplethResponse, OfferGeoJSON, AdminLevel
from app.core.exceptions import AppError, ValidationError
from app.services.admin_boundary import AdminBoundaryService

logger = logging.getLogger(__name__)

from datetime import datetime, timedelta
from sqlalchemy import case

class CarteService:

    """
    Service optimisé pour générer la carte choroplèthe avec navigation hiérarchique.
    Utilise les compteurs pré-calculés (offer_count) au lieu de recalculer à chaque fois.
    """
    
    def __init__(self, admin_service: AdminBoundaryService):
        self.admin_service = admin_service

    @staticmethod
    def with_network_retry(func):
        """Décorateur pour retry sur erreurs réseau."""
        return retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )(func)

    def _calculate_regional_growth(self, db: Session, level: str) -> Dict[str, float]:
        """Calcule la croissance (ou décroissance) des offres par région sur 30 jours."""
        try:
            today = datetime.now()
            last_30_days = today - timedelta(days=30)
            prev_30_days = last_30_days - timedelta(days=30)
            
            # 1. Offres du dernier mois
            current_counts = db.query(
                OffreEmploiBrute.location, 
                func.sum(func.coalesce(OffreEmploiBrute.nb_positions, 1))
            ).filter(
                OffreEmploiBrute.posted_date >= last_30_days
            ).group_by(OffreEmploiBrute.location).all()

            # 2. Offres du mois précédent
            prev_counts = db.query(
                OffreEmploiBrute.location, 
                func.sum(func.coalesce(OffreEmploiBrute.nb_positions, 1))
            ).filter(
                OffreEmploiBrute.posted_date >= prev_30_days,
                OffreEmploiBrute.posted_date < last_30_days
            ).group_by(OffreEmploiBrute.location).all()

            # Normalisation et mapping
            curr_map = {}
            for loc, count in current_counts:
                if loc and isinstance(loc, str):
                    norm = self.admin_service._normalize_name(loc)
                    curr_map[norm] = curr_map.get(norm, 0) + count

            prev_map = {}
            for loc, count in prev_counts:
                 if loc and isinstance(loc, str):
                    norm = self.admin_service._normalize_name(loc)
                    prev_map[norm] = prev_map.get(norm, 0) + count
            
            # Calcul du % de croissance
            growth_map = {}
            all_locs = set(curr_map.keys()) | set(prev_map.keys())
            
            for loc in all_locs:
                curr = curr_map.get(loc, 0)
                prev = prev_map.get(loc, 0)
                
                if prev == 0:
                    growth = 100.0 if curr > 0 else 0.0
                else:
                    growth = ((curr - prev) / prev) * 100.0
                
                growth_map[loc] = round(growth, 1)
                
            return growth_map

        except Exception as e:
            logger.error(f"Error calculating growth: {e}")
            return {}

    async def get_map_insights(self, db: Session) -> Dict[str, Any]:
        """
        Génère des insights et alertes de pénurie basés sur les données réelles et l'IA.
        """
        try:
            # 1. Identifier les pénuries (Ratio Offres / Candidats)
            level = "region"
            
            # Offres par région
            offers_query = db.query(
                SenegalAdminBoundary.name, 
                SenegalAdminBoundary.offer_count
            ).filter(SenegalAdminBoundary.level == level).all()
            
            offer_map = {self.admin_service._normalize_name(r.name): r.offer_count for r in offers_query}
            
            # Talents par région
            talent_results = db.query(
                UserProfile.location,
                func.count(UserProfile.id)
            ).join(User, UserProfile.user_id == User.id).filter(User.role == UserRole.CANDIDATE).group_by(UserProfile.location).all()
            
            talent_map = {}
            for loc, count in talent_results:
                if loc:
                    norm = self.admin_service._normalize_name(loc)
                    talent_map[norm] = talent_map.get(norm, 0) + count
            
            # Calcul du ratio de tension
            shortages = []
            for region, offers in offer_map.items():
                talents = talent_map.get(region, 0)
                # Ratio : Plus il est haut, plus la pénurie est forte (bcp d'offres / peu de talents)
                ratio = offers / (talents if talents > 0 else 0.1) 
                
                if ratio > 0.5: # Seuil abaissé pour détecter plus de tensions
                    shortages.append({
                        "region": region.title(),
                        "ratio": ratio,
                        "offers": offers,
                        "talents": talents,
                        "top_skill": "Multi-secteur" # Placeholder, improved by LLM later
                    })
            
            # Top 3 pénuries
            shortages.sort(key=lambda x: x['ratio'], reverse=True)
            top_shortages = shortages[:3]
            
            # Formater pour le frontend
            formatted_shortages = [
                {
                    "skill": s["top_skill"],
                    "regions": [s["region"]]
                }
                for s in top_shortages
            ]

            # 2. Génération de l'Insight IA
            llm = LLMClient()
            
            if top_shortages:
                context_str = "\n".join([f"- {s['region']}: {s['offers']} offres vs {s['talents']} talents (Ratio: {s['ratio']:.1f})" for s in top_shortages])
                prompt = (
                    f"Analyse ces zones de tension sur le marché de l'emploi au Sénégal :\n{context_str}\n"
                    "Génère une alerte stratégique courte (max 2 phrases) pour un décideur RH, expliquant où recruter est difficile et pourquoi."
                    "Ne mentionne pas 'ratio' explicitement, parle de tension."
                )
                insight_text = await llm.generate_response(
                    system_prompt="Tu es un expert en intelligence économique et marché du travail sénégalais.",
                    user_message=prompt,
                    temperature=0.7
                )
            else:
                insight_text = await llm.generate_response(
                    system_prompt="Tu es un expert RH.",
                    user_message="Le marché de l'emploi sénégalais semble équilibré sans régions en forte tension actuellement. Écris une courte observation positive pour un tableau de bord (1 phrase).",
                    temperature=0.7
                )

            return {
                "shortage_areas": formatted_shortages,
                "ai_insight": insight_text.replace('"', '').strip()
            }

        except Exception as e:
            logger.error(f"Error generating insights: {e}")
            return {"shortage_areas": [], "ai_insight": "Analyse IA temporairement indisponible."}

    @with_network_retry
    def get_choropleth_data(
        self,
        db: Session,
        level: AdminLevel,
        min_offers: int = 0,
        parent_name: Optional[str] = None
    ) -> ChoroplethResponse:
        """
        Récupère les données choroplèthe avec filtrage par parent.
        Utilise les compteurs pré-calculés pour les performances.
        
        Args:
            db: Session SQLAlchemy
            level: Niveau administratif (AdminLevel)
            min_offers: Nombre minimum d'offres pour afficher la zone
            parent_name: Nom du parent pour filtrage hiérarchique (ex: "Dakar")
        """
        
        # Validation
        if not isinstance(level, AdminLevel):
            raise ValidationError(
                field="level",
                reason="Doit être une valeur AdminLevel",
                context={"valid_values": [x.value for x in AdminLevel]}
            )

        # Vérifie PostGIS
        self.admin_service.postgis_manager.ensure_postgis(db)

        # Construction de la query avec filtre
        query = db.query(SenegalAdminBoundary).filter(
            SenegalAdminBoundary.level == level.value,
            SenegalAdminBoundary.offer_count >= min_offers
        )
        
        # Filtrage par parent si spécifié
        if parent_name:
            query = query.filter(
                func.lower(SenegalAdminBoundary.parent_name) == func.lower(parent_name)
            )

        boundaries = query.all()

        if not boundaries:
            logger.warning(f"Aucune limite trouvée pour level='{level.value}', parent='{parent_name}'")
            return ChoroplethResponse(
                type="FeatureCollection",
                features=[],
                offers=[],
                total_boundaries=0,
                total_offers=0
            )

        # --- Récupération des Talents (Candidats) ---
        talent_query = db.query(
            UserProfile.location,
            func.count(UserProfile.id)
        ).join(User, UserProfile.user_id == User.id).filter(User.role == UserRole.CANDIDATE)
        
        # Filtre approximatif pour talents (basé sur string contain)
        if parent_name:
             talent_query = talent_query.filter(UserProfile.location.ilike(f"%{parent_name}%"))
             
        talent_results = talent_query.group_by(UserProfile.location).all()
        # Création d'une map normalisée : "dakar" -> count
        talent_map = {}
        for loc, count in talent_results:
            if loc:
                norm = self.admin_service._normalize_name(loc)
                talent_map[norm] = talent_map.get(norm, 0) + count

        # --- Calcul de la croissance ---
        growth_map = self._calculate_regional_growth(db, level.value)

        features = []
        total_offers = 0

        # Construction des features GeoJSON
        for b in boundaries:
            total_offers += b.offer_count

            # Convertit geometry
            geometry = b.geojson if isinstance(b.geojson, dict) else {}
            if isinstance(b.geojson, str):
                try:
                    geometry = json.loads(b.geojson)
                except:
                    geometry = {}

            # Convertit centroid
            centroid_value = b.centroid
            if hasattr(centroid_value, "desc"):
                try:
                    from shapely.geometry import mapping, shape
                    centroid_value = mapping(shape(centroid_value))
                except:
                    centroid_value = None

            features.append({
                "type": "Feature",
                "properties": {
                    "id": b.id,
                    "name": b.name,
                    "level": b.level,
                    "offer_count": b.offer_count,  # ✅ Utilise le compteur pré-calculé
                    "talent_count": talent_map.get(self.admin_service._normalize_name(b.name), 0), # ✅ Vrais chiffres
                    "growth": growth_map.get(self.admin_service._normalize_name(b.name), 0.0), # ✅ Croissance réelle
                    "centroid": centroid_value,
                    "parent_name": b.parent_name  # ✅ IMPORTANT pour la navigation
                },
                "geometry": geometry
            })

        # Récupération des offres liées (optionnel, pour debug)
        offres = []
        if hasattr(OffreEmploiBrute, 'admin_boundary_id'):
            offres = (
                db.query(
                    OffreEmploiBrute.id,
                    OffreEmploiBrute.title,
                    OffreEmploiBrute.location,
                    OffreEmploiBrute.contract_type,
                )
                .join(SenegalAdminBoundary, OffreEmploiBrute.admin_boundary_id == SenegalAdminBoundary.id)
                .filter(
                    SenegalAdminBoundary.level == level.value,
                    SenegalAdminBoundary.offer_count >= min_offers
                )
                .limit(500)
                .all()
            )

        return ChoroplethResponse(
            type="FeatureCollection",
            features=features,
            offers=[
                OfferGeoJSON(
                    id=str(o.id),
                    title=o.title,
                    location=o.location,
                    contract=o.contract_type,
                    boundary=self.admin_service._normalize_name(o.location)
                )
                for o in offres
            ],
            total_boundaries=len(features),
            total_offers=total_offers,
        )

    @with_network_retry
    def get_locations_list(
        self,
        db: Session,
        level: AdminLevel,
        parent_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Récupère une liste légère des lieux (pour les dropdowns).
        """
        self.admin_service.postgis_manager.ensure_postgis(db)

        query = db.query(SenegalAdminBoundary.id, SenegalAdminBoundary.name).filter(
            SenegalAdminBoundary.level == level.value
        )

        if parent_name:
             query = query.filter(
                func.lower(SenegalAdminBoundary.parent_name) == func.lower(parent_name)
            )
            
        return [{"id": r.id, "name": r.name} for r in query.all()]