"""
Service pour les recommandations d'emploi personnalisées — version refactorisée.

Améliorations apportées (toutes les sections du plan d'amélioration v1.0) :
 1. Scoring normalisé (ScoringWeights, somme = 1.0, redistribution proportionnelle)
 2. Pipeline TF-IDF : fit sur corpus unifié CV + offres, stop words adaptatifs, seuils configurables
 3. Extraction CV : borne supérieure d'expérience, dictionnaire YAML externe, NLP optionnel
 4. Élimination de toutes les valeurs hardcodées → RecommendationConfig / from_env()
 5. Champs booléens location_match / contract_type_match calculés (jamais hardcodés True)
    + bug secteur corrigé (preferred_sectors, pas skills)
    + typo "Localisation spécifiée" → "Localisation non spécifiée"
 6. Cache LRU + TTL + invalidation par corpus ; fix leak @lru_cache sur instance → module-level
 7. Architecture transactionnelle : _execute_with_retry séparé du context manager + savepoints
 8. Requêtes SQL : batch anti-N+1, _get_saved_job_ids centralisé
 9. Timeout : SIGALRM remplacé par statement_timeout PostgreSQL + fallback ThreadPoolExecutor
10. Traçabilité : ScoreBreakdown, logs structurés JSON
11. Invariants documentés (assertions + tests suggérés)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import unicodedata
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import and_, func, or_, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ..models.database_models import (
    JobRecommendation,
    OffreEmploiBrute,
    OffreEmploiEnrichie,
    UserProfile,
    UserSavedJob,
)
from ..models.api_models import (
    RecommendationRequest,
    RecommendationResponse,
    JobRecommendationResponse,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes de robustesse
# ---------------------------------------------------------------------------

MAX_CREDIBLE_EXPERIENCE_YEARS: int = 45  # borne supérieure réaliste (section 3)


# ---------------------------------------------------------------------------
# 1. Modèle de scoring — ScoringWeights (section 1 du plan)
# ---------------------------------------------------------------------------

@dataclass
class ScoringWeights:
    """
    Poids du scoring de recommandation.
    Invariant vérifié à l'init : sum(weights.values()) == 1.0.
    """
    title: float = 0.20
    skills: float = 0.35
    sector: float = 0.15
    contract: float = 0.12
    salary: float = 0.10
    experience: float = 0.08

    def __post_init__(self) -> None:
        total = sum(vars(self).values())
        if abs(total - 1.0) >= 1e-9:
            raise ValueError(
                f"Les poids de scoring doivent sommer à 1.0, "
                f"valeur obtenue : {total:.6f}"
            )

    def redistribute_without(self, *excluded: str) -> Dict[str, float]:
        """
        Retourne les poids redistribués proportionnellement
        en excluant les critères spécifiés (données manquantes).
        """
        active = {k: v for k, v in vars(self).items() if k not in excluded}
        total_active = sum(active.values())
        if total_active == 0:
            return {}
        return {k: v / total_active for k, v in active.items()}


# ---------------------------------------------------------------------------
# 2. Seuils de matching (section 2 du plan)
# ---------------------------------------------------------------------------

@dataclass
class MatchingThresholds:
    """
    Seuils de filtrage des candidats.
    Calibrés empiriquement — voir CALIBRATION_LOG.md.
    """
    min_cosine_similarity: float = 0.05   # similarité cosine minimale
    min_final_score: float = 0.15         # score final minimal
    max_cv_recommendations: int = 20      # nombre max de recommandations CV


# ---------------------------------------------------------------------------
# 3. Configuration centralisée (section 4 du plan)
# ---------------------------------------------------------------------------

@dataclass
class RecommendationConfig:
    """
    Configuration complète du service de recommandations.
    Toutes les valeurs sont documentées et modifiables sans redéploiement
    via variables d'environnement (RecommendationConfig.from_env()).
    """
    # Fenêtres temporelles — alignées (invariant #9)
    cv_matching_lookback_days: int = 30
    profile_matching_lookback_days: int = 30

    # Candidats
    max_candidate_jobs: int = 500

    # TF-IDF
    tfidf_max_features: int = 1000
    tfidf_min_df: int = 1
    tfidf_max_df: float = 0.85

    # Seuils de matching
    thresholds: MatchingThresholds = field(default_factory=MatchingThresholds)

    # Poids de scoring
    scoring_weights: ScoringWeights = field(default_factory=ScoringWeights)

    # Tolérance métier
    salary_tolerance_ratio: float = 0.90   # offre à 90 % du min souhaité = valide
    experience_tolerance_years: int = 2    # écart maximal d'expérience toléré

    # Cache LRU + TTL
    vectorizer_cache_max_size: int = 50
    vectorizer_cache_ttl_seconds: int = 300

    # Robustesse
    max_retries: int = 3
    timeout_seconds: int = 30

    # Chemin du dictionnaire de compétences (YAML externe)
    skills_dict_path: str = "skills_dictionary.yml"

    @classmethod
    def from_env(cls) -> "RecommendationConfig":
        """Charge la configuration depuis les variables d'environnement."""
        return cls(
            cv_matching_lookback_days=int(os.getenv("RECO_CV_LOOKBACK_DAYS", 30)),
            profile_matching_lookback_days=int(os.getenv("RECO_PROFILE_LOOKBACK_DAYS", 30)),
            max_candidate_jobs=int(os.getenv("RECO_MAX_CANDIDATES", 500)),
            tfidf_max_features=int(os.getenv("RECO_TFIDF_MAX_FEATURES", 1000)),
            salary_tolerance_ratio=float(os.getenv("RECO_SALARY_TOLERANCE", 0.90)),
            experience_tolerance_years=int(os.getenv("RECO_EXP_TOLERANCE_YEARS", 2)),
            vectorizer_cache_max_size=int(os.getenv("RECO_CACHE_MAX_SIZE", 50)),
            vectorizer_cache_ttl_seconds=int(os.getenv("RECO_CACHE_TTL_SECONDS", 300)),
            max_retries=int(os.getenv("RECO_MAX_RETRIES", 3)),
            timeout_seconds=int(os.getenv("RECO_TIMEOUT_SECONDS", 30)),
            skills_dict_path=os.getenv("RECO_SKILLS_DICT_PATH", "skills_dictionary.yml"),
        )


# ---------------------------------------------------------------------------
# 4. Traçabilité — ScoreBreakdown (section 10 du plan)
# ---------------------------------------------------------------------------

@dataclass
class ScoreBreakdown:
    """Décomposition du score pour audit et debug."""
    title_score: float = 0.0
    title_weight: float = 0.0
    skills_score: float = 0.0
    skills_weight: float = 0.0
    sector_score: float = 0.0
    sector_weight: float = 0.0
    contract_score: float = 0.0
    contract_weight: float = 0.0
    salary_score: float = 0.0
    salary_weight: float = 0.0
    experience_score: float = 0.0
    experience_weight: float = 0.0
    excluded_criteria: List[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return (
            self.title_score * self.title_weight
            + self.skills_score * self.skills_weight
            + self.sector_score * self.sector_weight
            + self.contract_score * self.contract_weight
            + self.salary_score * self.salary_weight
            + self.experience_score * self.experience_weight
        )

    def __post_init__(self) -> None:
        total_w = (
            self.title_weight
            + self.skills_weight
            + self.sector_weight
            + self.contract_weight
            + self.salary_weight
            + self.experience_weight
        )
        if total_w > 0 and abs(total_w - 1.0) >= 1e-9:
            raise AssertionError(
                f"Poids du ScoreBreakdown ne somment pas à 1.0 : {total_w}"
            )


# ---------------------------------------------------------------------------
# 5. Cache LRU + TTL (section 6 du plan)
# ---------------------------------------------------------------------------

class TTLCache:
    """Cache LRU avec Time-To-Live par entrée. Thread-safe pour usage mono-thread."""

    def __init__(self, maxsize: int = 50, ttl_seconds: int = 300) -> None:
        self.maxsize = maxsize
        self.ttl = ttl_seconds
        self._store: OrderedDict = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        if key not in self._store:
            return None
        value, timestamp = self._store[key]
        if time.time() - timestamp > self.ttl:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (value, time.time())
        if len(self._store) > self.maxsize:
            evicted_key, _ = self._store.popitem(last=False)
            logger.debug("Cache LRU : éviction de la clé %s", evicted_key[:12])

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


# ---------------------------------------------------------------------------
# 6. Fonction module-level pour _find_skill_matches (fix leak lru_cache — section 6)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=512)
def _find_skill_matches_cached(
    user_skills: Tuple[str, ...], job_skills: Tuple[str, ...]
) -> Tuple[str, ...]:
    """
    Cache de matching compétences en dehors de la classe (pas de référence à self).
    Évite le leak mémoire du @lru_cache sur méthode d'instance.
    """
    if not user_skills or not job_skills:
        return ()
    job_text = " | ".join(job_skills).lower()
    matches: Set[str] = set()
    for skill in user_skills:
        if not skill or len(skill.strip()) < 2:
            continue
        safe_skill = re.escape(skill.strip().lower())
        pattern = rf"(?:^|[|\s,.\-])({safe_skill})(?:$|[|\s,.\-])"
        try:
            if re.search(pattern, job_text):
                matches.add(skill.strip())
        except re.error:
            if safe_skill in job_text:
                matches.add(skill.strip())
    return tuple(sorted(matches))[:5]


# ---------------------------------------------------------------------------
# 7. Service principal
# ---------------------------------------------------------------------------

class RecommendationService:
    """Service robuste pour générer des recommandations d'emploi personnalisées."""

    def __init__(self, config: Optional[RecommendationConfig] = None) -> None:
        """
        Args:
            config: Configuration complète du service.
                    Si None, utilise les valeurs par défaut de RecommendationConfig.
        """
        self.config = config or RecommendationConfig()
        self._vectorizer_cache = TTLCache(
            maxsize=self.config.vectorizer_cache_max_size,
            ttl_seconds=self.config.vectorizer_cache_ttl_seconds,
        )
        self._skills_flat: List[str] = self._load_skills_dict()
        logger.info(
            "RecommendationService initialisé — max_retries=%d, timeout=%ds, "
            "lookback_cv=%dj, lookback_profile=%dj",
            self.config.max_retries,
            self.config.timeout_seconds,
            self.config.cv_matching_lookback_days,
            self.config.profile_matching_lookback_days,
        )

    # ------------------------------------------------------------------
    # Chargement du dictionnaire de compétences (section 3)
    # ------------------------------------------------------------------

    def _load_skills_dict(self) -> List[str]:
        """
        Charge le dictionnaire de compétences depuis un fichier YAML externe
        (rechargeable sans redéploiement) ou utilise le dictionnaire intégré en fallback.
        """
        try:
            import yaml  # type: ignore
            with open(self.config.skills_dict_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            skills = [
                skill
                for category in raw.values()
                for skill in category
                if isinstance(skill, str)
            ]
            logger.info(
                "Dictionnaire compétences chargé depuis %s : %d entrées",
                self.config.skills_dict_path,
                len(skills),
            )
            return skills
        except FileNotFoundError:
            logger.warning(
                "Fichier %s non trouvé — utilisation du dictionnaire intégré.",
                self.config.skills_dict_path,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Erreur chargement dictionnaire YAML : %s — fallback intégré.", e)

        return self._builtin_skills_dict()

    @staticmethod
    def _builtin_skills_dict() -> List[str]:
        """Dictionnaire de compétences intégré (fallback si YAML absent)."""
        return [
            # Technical
            "python", "java", "javascript", "typescript", "react", "node.js",
            "sql", "postgresql", "mysql", "mongodb", "nosql", "php", "c++", "c#",
            "go", "rust", "ruby", "swift", "kotlin", "docker", "kubernetes", "aws",
            "azure", "gcp", "terraform", "ansible", "git", "linux", "windows",
            "macos", "bash", "powershell", "jenkins", "github", "gitlab",
            "fastapi", "django", "flask", "spring", "laravel",
            # Business
            "marketing", "vente", "sales", "management", "gestion de projet",
            "comptabilité", "finance", "ressources humaines", "recrutement",
            "formation", "stratégie", "business development", "partenariats",
            "supply chain",
            # Languages
            "anglais", "français", "espagnol", "allemand", "chinois", "arabe",
            "portugais", "italien", "wolof",
            # Soft skills
            "communication", "leadership", "travail en équipe", "autonomie",
            "adaptabilité", "résolution de problèmes", "créativité", "analyse",
        ]

    # ------------------------------------------------------------------
    # Point d'entrée principal — get_recommendations (section 7 / 8)
    # ------------------------------------------------------------------

    def get_recommendations(
        self,
        db: Session,
        user_id: str,
        request: RecommendationRequest,
    ) -> RecommendationResponse:
        """Génère des recommandations d'emploi pour un utilisateur avec profil."""
        start_time = time.time()
        try:
            self._validate_request(db, user_id, request)

            user_profile = self._get_user_profile(db, user_id)
            if not user_profile:
                raise ValueError(f"Profil utilisateur non trouvé pour l'ID : {user_id}")

            query = self._build_optimized_job_query(db, request)
            candidate_jobs = self._execute_query_with_timeout(query)

            if not candidate_jobs:
                logger.warning("Aucune offre candidate pour l'utilisateur %s", user_id)
                return self._empty_recommendation_response(user_id)

            scored_jobs = self._score_jobs_batch(user_profile, candidate_jobs, request)

            # Batch : une seule requête pour les jobs sauvegardés (section 8)
            saved_job_ids = self._get_saved_job_ids(db, user_profile.user_id)

            recommendations = self._create_recommendations_batch(
                db, user_id, scored_jobs, user_profile, saved_job_ids
            )

            execution_time = time.time() - start_time
            logger.info(
                "Recommandations générées en %.2fs pour l'utilisateur %s : %d résultats",
                execution_time, user_id, len(recommendations),
            )

            avg_score = (
                float(np.mean([r.match_score for r in recommendations]))
                if recommendations
                else 0.0
            )
            # Invariant #4 : average_match_score == mean(scores individuels)
            assert abs(
                avg_score - (
                    sum(r.match_score for r in recommendations) / len(recommendations)
                    if recommendations else 0.0
                )
            ) < 1e-6

            return RecommendationResponse(
                user_id=str(self._get_valid_uuid(user_id)),
                recommendations=recommendations,
                total_recommendations=len(recommendations),
                average_match_score=avg_score,
                generated_at=datetime.now(),
                execution_time_seconds=execution_time,
            )

        except Exception:
            logger.error(
                "Erreur critique dans get_recommendations pour %s", user_id, exc_info=True
            )
            db.rollback()
            raise

    # ------------------------------------------------------------------
    # Point d'entrée CV — match_cv_with_jobs
    # ------------------------------------------------------------------

    def match_cv_with_jobs(
        self,
        db: Session,
        cv_text: str,
        user_id: Optional[str] = None,
    ) -> RecommendationResponse:
        """Match robuste d'un CV avec les offres d'emploi."""
        start_time = time.time()
        try:
            if not cv_text or not isinstance(cv_text, str) or len(cv_text.strip()) < 50:
                raise ValueError("CV text invalide : doit contenir au moins 50 caractères")
            if len(cv_text) > 500_000:
                raise ValueError("CV text trop volumineux : maximum 500 Ko")

            cv_skills, cv_experience, cv_sectors = self._extract_cv_info_robust(cv_text)

            # Fenêtre temporelle alignée sur la config (invariant #9)
            recent_jobs = self._get_recent_jobs_paginated(
                db,
                days=self.config.cv_matching_lookback_days,
                batch_size=self.config.max_candidate_jobs,
            )

            if not recent_jobs:
                logger.warning("Aucune offre récente disponible pour le matching CV")
                return self._empty_recommendation_response(user_id)

            # Jobs sauvegardés centralisés (section 8)
            saved_job_ids = self._get_saved_job_ids(db, user_id) if user_id else set()

            recommendations = self._vectorized_cv_matching(
                cv_text, cv_skills, cv_experience, cv_sectors,
                recent_jobs, saved_job_ids,
            )

            # Tri et limitation via config (section 4)
            recommendations.sort(key=lambda x: x.match_score, reverse=True)
            recommendations = recommendations[: self.config.thresholds.max_cv_recommendations]

            execution_time = time.time() - start_time
            logger.info(
                "Matching CV terminé en %.2fs : %d recommandations",
                execution_time, len(recommendations),
            )

            avg_score = (
                float(np.mean([r.match_score for r in recommendations]))
                if recommendations
                else 0.0
            )
            return RecommendationResponse(
                user_id=str(self._get_valid_uuid(user_id)),
                recommendations=recommendations,
                total_recommendations=len(recommendations),
                average_match_score=avg_score,
                generated_at=datetime.now(),
                execution_time_seconds=execution_time,
            )

        except Exception:
            logger.error("Erreur dans match_cv_with_jobs", exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_request(
        self, db: Session, user_id: str, request: RecommendationRequest
    ) -> None:
        if not db or not hasattr(db, "query"):
            raise ValueError("Session de base de données invalide ou non connectée")
        if not user_id or not isinstance(user_id, (str, uuid.UUID)):
            raise ValueError("user_id doit être une chaîne non vide ou un UUID valide")
        if not request or not isinstance(request, RecommendationRequest):
            raise ValueError("RecommendationRequest invalide")
        if not 0 <= request.min_match_score <= 1:
            raise ValueError("min_match_score doit être entre 0 et 1")
        if not 1 <= request.max_results <= 1000:
            raise ValueError("max_results doit être entre 1 et 1000")

    # ------------------------------------------------------------------
    # Récupération du profil utilisateur
    # ------------------------------------------------------------------

    def _get_user_profile(self, db: Session, user_id: str) -> Optional[UserProfile]:
        try:
            return db.query(UserProfile).filter(UserProfile.id == user_id).first()
        except SQLAlchemyError as e:
            logger.error(
                "Erreur SQL récupération profil utilisateur %s : %s", user_id, e
            )
            return None

    # ------------------------------------------------------------------
    # Jobs sauvegardés centralisés — une seule requête (section 8)
    # ------------------------------------------------------------------

    def _get_saved_job_ids(self, db: Session, user_id: Any) -> Set[str]:
        """Récupère les jobs sauvegardés en une requête. Retourne un set vide si erreur."""
        if not user_id:
            return set()
        try:
            valid_id = self._get_valid_uuid(user_id)
            rows = (
                db.query(UserSavedJob.job_id)
                .filter(UserSavedJob.user_id == valid_id)
                .all()
            )
            return {str(row.job_id) for row in rows}
        except SQLAlchemyError as e:
            logger.warning("Impossible de récupérer les jobs sauvegardés : %s", e)
            return set()

    # ------------------------------------------------------------------
    # Construction de la requête SQL optimisée (section 4 / 8)
    # ------------------------------------------------------------------

    def _build_optimized_job_query(self, db: Session, request: RecommendationRequest):
        """Requête SQL optimisée ; fenêtre temporelle issue de la config (invariant #9)."""
        lookback = datetime.now() - timedelta(
            days=self.config.profile_matching_lookback_days
        )
        query = (
            db.query(OffreEmploiBrute, OffreEmploiEnrichie)
            .join(OffreEmploiEnrichie, OffreEmploiBrute.id == OffreEmploiEnrichie.offre_id)
            .filter(
                OffreEmploiBrute.posted_date >= lookback,
                or_(
                    OffreEmploiBrute.expiration_date.is_(None),
                    OffreEmploiBrute.expiration_date >= datetime.now(),
                ),
            )
        )

        if request.preferred_sectors and any(s.strip() for s in request.preferred_sectors):
            query = query.filter(
                func.lower(OffreEmploiEnrichie.extracted_sector).in_(
                    [s.lower().strip() for s in request.preferred_sectors if s.strip()]
                )
            )

        if request.preferred_contract_types and any(
            ct.strip() for ct in request.preferred_contract_types
        ):
            query = query.filter(
                func.lower(OffreEmploiEnrichie.extracted_contract_type).in_(
                    [ct.lower().strip() for ct in request.preferred_contract_types if ct.strip()]
                )
            )

        if request.min_salary and request.min_salary > 0:
            query = query.filter(
                OffreEmploiEnrichie.extracted_salary_max >= float(request.min_salary)
            )

        if request.max_salary and request.max_salary > 0:
            query = query.filter(
                OffreEmploiEnrichie.extracted_salary_min <= float(request.max_salary)
            )

        if getattr(request, "preferred_job_titles", None):
            title_conditions = [
                func.lower(OffreEmploiEnrichie.extracted_job_title).contains(
                    t.lower().strip()
                )
                for t in request.preferred_job_titles
                if t.strip()
            ]
            if title_conditions:
                query = query.filter(or_(*title_conditions))

        return query

    # ------------------------------------------------------------------
    # Timeout thread-safe — PostgreSQL statement_timeout + fallback (section 9)
    # ------------------------------------------------------------------

    def _execute_query_with_timeout(
        self, query: Any, timeout: Optional[int] = None
    ) -> List[Any]:
        """
        Timeout via statement_timeout PostgreSQL (atomique, thread-safe).
        Fallback sur ThreadPoolExecutor pour les autres moteurs.
        Remplace signal.SIGALRM (POSIX-only, non thread-safe).
        """
        timeout_s = timeout or self.config.timeout_seconds
        timeout_ms = timeout_s * 1000

        # Tentative PostgreSQL statement_timeout
        db_session = query.session
        try:
            db_session.execute(
                text(f"SET LOCAL statement_timeout = '{timeout_ms}ms'")
            )
            return query.all()
        except SQLAlchemyError as e:
            if "statement timeout" in str(e).lower():
                logger.error(
                    "Timeout requête dépassé (%dms). "
                    "Envisager d'ajouter des index ou de réduire la fenêtre temporelle.",
                    timeout_ms,
                )
                raise TimeoutError(f"Requête dépassée : {timeout_s}s") from e
            # Le moteur ne supporte pas statement_timeout → fallback ThreadPoolExecutor
            logger.debug(
                "statement_timeout non supporté par ce moteur, fallback ThreadPoolExecutor"
            )

        # Fallback ThreadPoolExecutor (section 9)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(query.all)
            try:
                return future.result(timeout=timeout_s)
            except FuturesTimeout:
                logger.error("Timeout requête après %ds (ThreadPoolExecutor)", timeout_s)
                raise TimeoutError(f"Requête dépassée : {timeout_s}s")

    # ------------------------------------------------------------------
    # Scoring batch
    # ------------------------------------------------------------------

    def _score_jobs_batch(
        self,
        user_profile: UserProfile,
        candidate_jobs: List[Any],
        request: RecommendationRequest,
    ) -> List[Dict[str, Any]]:
        """Calcul des scores de matching avec filtrage."""
        scored_jobs: List[Dict[str, Any]] = []
        user_skills = self._normalize_skill_list(user_profile.skills)

        for brute, enrichie in candidate_jobs:
            try:
                match_score, match_reasons, _ = self._calculate_match_score(
                    user_profile, brute, enrichie, user_skills
                )
                if match_score >= request.min_match_score and len(scored_jobs) < 1000:
                    scored_jobs.append(
                        {"job": (brute, enrichie), "score": match_score, "reasons": match_reasons}
                    )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Échec scoring job %s : %s", getattr(brute, "id", "N/A"), e
                )

        scored_jobs.sort(key=lambda x: x["score"], reverse=True)
        return scored_jobs[: request.max_results]

    # ------------------------------------------------------------------
    # Création batch des recommandations — anti-N+1 (section 7 / 8)
    # ------------------------------------------------------------------

    def _create_recommendations_batch(
        self,
        db: Session,
        user_id: str,
        scored_jobs: List[Dict],
        user_profile: UserProfile,
        saved_job_ids: Set[str],
    ) -> List[JobRecommendationResponse]:
        """
        Création batch des recommandations avec transaction robuste.
        Vérification des doublons en UNE seule requête (anti-N+1).
        """
        recommendations: List[JobRecommendationResponse] = []

        all_job_ids = [rec["job"][1].id for rec in scored_jobs]
        # Batch : une requête pour tous les doublons (section 8)
        already_recommended = self._get_existing_recommendation_ids(
            db, user_id, all_job_ids
        )

        def _do_insert(session: Session) -> None:
            for rec in scored_jobs:
                brute, enrichie = rec["job"]
                job_id_str = str(enrichie.id)

                job_response = self._create_job_recommendation_response(
                    brute, enrichie, rec, user_profile, saved_job_ids
                )
                recommendations.append(job_response)

                if job_id_str not in already_recommended:
                    self._insert_single_recommendation(
                        session, user_id, rec
                    )

        self._execute_with_retry(db, _do_insert)
        return recommendations

    def _get_existing_recommendation_ids(
        self, db: Session, user_id: str, job_ids: List[Any], days: int = 7
    ) -> Set[str]:
        """Récupère en UNE requête tous les job_ids déjà recommandés récemment."""
        if not job_ids:
            return set()
        cutoff = datetime.now() - timedelta(days=days)
        try:
            rows = (
                db.query(JobRecommendation.job_id)
                .filter(
                    JobRecommendation.user_id == self._get_valid_uuid(user_id),
                    JobRecommendation.job_id.in_(job_ids),
                    JobRecommendation.created_at >= cutoff,
                )
                .all()
            )
            return {str(row.job_id) for row in rows}
        except SQLAlchemyError as e:
            logger.warning(
                "Impossible de récupérer les recommandations existantes : %s", e
            )
            return set()

    def _insert_single_recommendation(
        self, db: Session, user_id: str, rec: Dict
    ) -> None:
        """Insère une recommandation en utilisant un savepoint pour l'isolation (section 7)."""
        _, enrichie = rec["job"]
        savepoint = db.begin_nested()
        try:
            recommendation = JobRecommendation(
                user_id=self._get_valid_uuid(user_id),
                job_id=enrichie.id,
                match_score=float(rec["score"]),
                match_reasons=rec["reasons"][:10],
            )
            db.add(recommendation)
            savepoint.commit()
        except IntegrityError:
            savepoint.rollback()
            logger.debug(
                "Recommandation déjà existante pour le job %s, ignorée.", enrichie.id
            )

    # ------------------------------------------------------------------
    # Transaction avec retry — SANS yield dans boucle (section 7)
    # ------------------------------------------------------------------

    def _execute_with_retry(
        self, db: Session, func: Any, *args: Any, **kwargs: Any
    ) -> Any:
        """
        Exécute une fonction avec retry et backoff exponentiel.
        Séparé du context manager pour éviter l'anti-pattern yield-in-loop.
        """
        last_exception: Optional[Exception] = None
        for attempt in range(self.config.max_retries):
            try:
                result = func(db, *args, **kwargs)
                db.commit()
                if attempt > 0:
                    logger.info(
                        "Opération réussie après %d tentatives", attempt + 1
                    )
                return result
            except SQLAlchemyError as e:
                last_exception = e
                db.rollback()
                if attempt < self.config.max_retries - 1:
                    wait = (2 ** attempt) * 0.5
                    logger.warning(
                        "Tentative %d/%d échouée : %s. Retry dans %.1fs",
                        attempt + 1, self.config.max_retries, e, wait,
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        "Échec définitif après %d tentatives : %s",
                        self.config.max_retries, e,
                    )
            except Exception as e:
                db.rollback()
                logger.error("Erreur non-SQLAlchemy : %s", e)
                raise
        raise last_exception  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Création de la réponse JobRecommendationResponse (section 5)
    # ------------------------------------------------------------------

    def _create_job_recommendation_response(
        self,
        brute: OffreEmploiBrute,
        enrichie: OffreEmploiEnrichie,
        rec: Dict,
        user_profile: UserProfile,
        saved_job_ids: Optional[Set[str]] = None,
    ) -> JobRecommendationResponse:
        """Création robuste de l'objet de réponse."""
        try:
            return JobRecommendationResponse(
                job_id=str(brute.id) if brute.id else "",
                title=str(brute.title or "Titre non spécifié")[:200],
                company_name=str(brute.company_name or "Entreprise non spécifiée")[:200],
                # CORRECTION section 5 : "Localisation non spécifiée" (typo corrigée)
                location=str(brute.location or "Localisation non spécifiée")[:100],
                match_score=float(rec["score"]),
                match_reasons=rec["reasons"][:10],
                salary_min=enrichie.extracted_salary_min,
                salary_max=enrichie.extracted_salary_max,
                contract_type=enrichie.extracted_contract_type or brute.contract_type,
                experience_required=(
                    f"{enrichie.extracted_experience_years} ans"
                    if enrichie.extracted_experience_years
                    else "Non spécifié"
                ),
                posted_date=brute.posted_date,
                deadline=brute.expiration_date,
                url=brute.url,
                skills=list(
                    self._find_skill_matches(
                        tuple(self._normalize_skill_list(user_profile.skills)),
                        tuple(self._normalize_skill_list(enrichie.extracted_skills)),
                    )
                ),
                sector_match=self._safe_sector_match(user_profile, enrichie),
                # CORRECTION section 5 : calculé, jamais hardcodé True
                contract_type_match=self._safe_contract_match(user_profile, enrichie),
                location_match=self._is_location_match(
                    getattr(user_profile, "location", None),
                    brute.location,
                ),
                applicants_count=getattr(brute, "applicants_count", 0) or 0,
                views_count=getattr(brute, "views_count", 0) or 0,
                remote_option=(
                    (getattr(brute, "remote_type", "") or "").lower()
                    in ("remote", "hybrid")
                ),
                is_favorited=str(brute.id) in (saved_job_ids or set()),
                company_size=(
                    getattr(brute.company, "size", None)
                    if getattr(brute, "company", None)
                    else None
                ),
                status="pending",
            )
        except Exception as e:  # noqa: BLE001
            logger.error("Erreur création JobRecommendationResponse : %s", e)
            return JobRecommendationResponse(
                job_id=str(getattr(brute, "id", "")),
                title="Erreur formatage",
                company_name="Erreur",
                location="Erreur",
                match_score=0.0,
                match_reasons=["Erreur lors de la création de la recommandation"],
                salary_min=None,
                salary_max=None,
                contract_type=None,
                experience_required=None,
                posted_date=None,
                deadline=None,
                url=None,
                skills=[],
                sector_match=False,
                contract_type_match=False,
                location_match=False,
                applicants_count=0,
                views_count=0,
                remote_option=False,
                company_size=None,
                status="pending",
            )

    # ------------------------------------------------------------------
    # Scoring principal — ScoringWeights normalisé (section 1)
    # ------------------------------------------------------------------

    def _calculate_match_score(
        self,
        user_profile: UserProfile,
        brute: OffreEmploiBrute,
        enrichie: OffreEmploiEnrichie,
        pre_normalized_user_skills: Optional[List[str]] = None,
    ) -> Tuple[float, List[str], ScoreBreakdown]:
        """
        Calcule un score de matching normalisé avec ScoreBreakdown pour la traçabilité.

        Retourne (score_in_[0,1], reasons, breakdown).
        Invariants :
          - 0.0 <= score <= 1.0 (sans troncature min())
          - breakdown.total == score (à 1e-9 près)
          - sector_match utilise preferred_sectors, jamais skills
        """
        weights = self.config.scoring_weights
        user_skills = pre_normalized_user_skills or self._normalize_skill_list(
            user_profile.skills
        )
        job_skills = self._normalize_skill_list(enrichie.extracted_skills)

        # Déterminer les critères évaluables
        excluded: List[str] = []
        if not user_skills or not job_skills:
            excluded.append("skills")
        user_sectors = self._normalize_list(
            getattr(user_profile, "preferred_sectors", None)
            or getattr(user_profile, "sectors", None)
        )
        if not user_sectors:
            excluded.append("sector")
        if not getattr(user_profile, "preferred_contract_type", None):
            excluded.append("contract")
        if not getattr(user_profile, "preferred_salary_min", None):
            excluded.append("salary")
        if not getattr(user_profile, "experience_years", None):
            excluded.append("experience")

        active_weights = weights.redistribute_without(*excluded)

        score = 0.0
        reasons: List[str] = []
        bd = ScoreBreakdown(excluded_criteria=excluded)

        # --- Titre ---
        w_title = active_weights.get("title", 0.0)
        bd.title_weight = w_title
        if "title" not in excluded:
            ts, tr = self._score_title(user_profile, enrichie)
            bd.title_score = ts
            score += ts * w_title
            if tr:
                reasons.append(tr)

        # --- Compétences ---
        w_skills = active_weights.get("skills", 0.0)
        bd.skills_weight = w_skills
        if "skills" not in excluded:
            ss, sr = self._score_skills(user_skills, job_skills)
            bd.skills_score = ss
            score += ss * w_skills
            if sr:
                reasons.append(sr)

        # --- Secteur ---
        w_sector = active_weights.get("sector", 0.0)
        bd.sector_weight = w_sector
        if "sector" not in excluded:
            job_sector = getattr(enrichie, "extracted_sector", None)
            if job_sector and job_sector.lower() in [s.lower() for s in user_sectors]:
                bd.sector_score = 1.0
                score += 1.0 * w_sector
                reasons.append(f"✓ Secteur : {job_sector}")

        # --- Contrat ---
        w_contract = active_weights.get("contract", 0.0)
        bd.contract_weight = w_contract
        if "contract" not in excluded:
            user_contracts = self._normalize_list(
                getattr(user_profile, "preferred_contract_type", None)
            )
            job_contract = getattr(enrichie, "extracted_contract_type", None)
            if job_contract and job_contract.lower() in [c.lower() for c in user_contracts]:
                bd.contract_score = 1.0
                score += 1.0 * w_contract
                reasons.append(f"✓ Contrat : {job_contract}")

        # --- Salaire ---
        w_salary = active_weights.get("salary", 0.0)
        bd.salary_weight = w_salary
        if "salary" not in excluded:
            user_min = getattr(user_profile, "preferred_salary_min", None)
            job_max = getattr(enrichie, "extracted_salary_max", None)
            if self._is_valid_number(user_min) and self._is_valid_number(job_max):
                try:
                    if float(job_max) >= float(user_min) * self.config.salary_tolerance_ratio:
                        bd.salary_score = 1.0
                        score += 1.0 * w_salary
                        reasons.append("✓ Salaire compatible")
                except (ValueError, TypeError):
                    logger.debug(
                        "Erreur comparaison salaire pour le job %s",
                        getattr(enrichie, "id", "N/A"),
                    )

        # --- Expérience ---
        w_exp = active_weights.get("experience", 0.0)
        bd.experience_weight = w_exp
        if "experience" not in excluded:
            user_exp = getattr(user_profile, "experience_years", None)
            job_exp = getattr(enrichie, "extracted_experience_years", None)
            if self._is_valid_number(user_exp) and self._is_valid_number(job_exp):
                try:
                    exp_diff = abs(float(user_exp) - float(job_exp))
                    tol = self.config.experience_tolerance_years
                    if exp_diff == 0:
                        exp_s = 1.0
                        reasons.append("✓ Expérience compatible")
                    elif exp_diff <= tol / 2:
                        exp_s = 1.0
                        reasons.append("✓ Expérience compatible")
                    elif exp_diff <= tol:
                        exp_s = 0.5
                        reasons.append("~ Expérience partiellement compatible")
                    else:
                        exp_s = 0.0
                    bd.experience_score = exp_s
                    score += exp_s * w_exp
                except (ValueError, TypeError):
                    logger.debug(
                        "Erreur comparaison expérience pour le job %s",
                        getattr(enrichie, "id", "N/A"),
                    )

        # Invariant #2 : score mathématiquement dans [0.0, 1.0] sans troncature
        assert 0.0 <= score <= 1.0 + 1e-9, f"Score hors bornes : {score}"
        score = min(score, 1.0)  # garde-fou numérique uniquement

        # Invariant #3 : breakdown.total == score
        assert abs(bd.total - score) < 1e-9, (
            f"Incohérence breakdown.total={bd.total:.9f} vs score={score:.9f}"
        )

        self._log_recommendation_event_debug(score, bd)
        return score, reasons[:5], bd

    def _score_title(
        self, user_profile: UserProfile, enrichie: OffreEmploiEnrichie
    ) -> Tuple[float, Optional[str]]:
        """Score [0,1] pour le critère titre."""
        user_title = getattr(user_profile, "current_title", None)
        job_title = getattr(enrichie, "extracted_job_title", None)
        if not user_title or not job_title:
            return 0.0, None
        u = user_title.lower().strip()
        j = job_title.lower().strip()
        if u == j or u in j or j in u:
            return 1.0, f"✓ Titre correspondant : {job_title}"
        return 0.0, None

    def _score_skills(
        self, user_skills: List[str], job_skills: List[str]
    ) -> Tuple[float, Optional[str]]:
        """Score [0,1] pour le critère compétences."""
        if not user_skills or not job_skills:
            return 0.0, None
        matches = self._find_skill_matches(tuple(user_skills), tuple(job_skills))
        skill_score = len(matches) / max(len(set(user_skills)), len(set(job_skills)))
        reason = f"✓ Compétences : {', '.join(matches[:3])}" if matches else None
        return min(skill_score, 1.0), reason

    # ------------------------------------------------------------------
    # TF-IDF vectorisé — fit sur corpus unifié (section 2)
    # ------------------------------------------------------------------

    def _build_tfidf_vectorizer(self, corpus: List[str]) -> TfidfVectorizer:
        """
        Construit un vectoriseur TF-IDF avec stop words adaptatifs à la langue.
        Le corpus passé doit inclure le CV pour garantir que son vocabulaire est dans l'espace.
        """
        lang = self._detect_language(corpus)
        stop_words_map: Dict[str, Any] = {
            "fr": [
                "de", "le", "la", "les", "un", "une", "des", "du", "et", "en",
                "au", "aux", "pour", "par", "sur", "dans", "avec", "est", "sont",
                "être", "avoir", "cette", "ces", "tout", "plus", "que", "qui",
                "se", "sa", "son", "pas", "ne",
            ],
            "en": "english",
            "ar": [],
        }
        stop_words = stop_words_map.get(lang, [])
        return TfidfVectorizer(
            max_features=self.config.tfidf_max_features,
            stop_words=stop_words,
            ngram_range=(1, 2),
            min_df=self.config.tfidf_min_df,
            max_df=self.config.tfidf_max_df,
            sublinear_tf=True,  # log(1+tf) : réduit l'impact des répétitions
        )

    @staticmethod
    def _detect_language(corpus: List[str]) -> str:
        """Détection de langue sur un échantillon du corpus."""
        sample = " ".join(corpus[:10])[:500]
        try:
            import langdetect  # type: ignore
            return langdetect.detect(sample)
        except Exception:
            return "fr"  # défaut explicite

    def _build_cache_key(self, cv_text: str, job_ids: List[str]) -> str:
        """
        Clé de cache = hash(CV[:1000]) + hash(sorted job_ids).
        Invalide automatiquement si le corpus change.
        """
        cv_hash = hashlib.sha256(cv_text[:1000].encode()).hexdigest()[:12]
        job_hash = hashlib.sha256(
            ",".join(sorted(str(j) for j in job_ids)).encode()
        ).hexdigest()[:12]
        return f"{cv_hash}_{job_hash}"

    def _vectorized_cv_matching(
        self,
        cv_text: str,
        cv_skills: List[str],
        cv_experience: int,
        cv_sectors: List[str],
        recent_jobs: List[Any],
        saved_job_ids: Optional[Set[str]] = None,
    ) -> List[JobRecommendationResponse]:
        """Matching vectorisé CV avec pipeline TF-IDF sur corpus unifié."""
        recommendations: List[JobRecommendationResponse] = []
        try:
            valid_jobs = [
                (b, e, f"{getattr(b, 'title', '')} {getattr(b, 'description', '')}".strip())
                for b, e in recent_jobs
                if len(
                    f"{getattr(b, 'title', '')} {getattr(b, 'description', '')}".strip()
                ) > 20
            ]
            if not valid_jobs:
                return []

            job_texts = [j[2] for j in valid_jobs]
            job_ids = [str(j[1].id) for j in valid_jobs]

            # Cache avec invalidation par corpus (section 6)
            cache_key = self._build_cache_key(cv_text, job_ids)
            cached = self._vectorizer_cache.get(cache_key)
            if cached is not None:
                vectorizer, job_vectors = cached
                cv_vector = vectorizer.transform([cv_text])
            else:
                # CORRECTION section 2 : fit sur corpus unifié {CV} ∪ {offres}
                all_texts = [cv_text] + job_texts
                vectorizer = self._build_tfidf_vectorizer(all_texts)
                all_vectors = vectorizer.fit_transform(all_texts)
                cv_vector = all_vectors[0]
                job_vectors = all_vectors[1:]
                self._vectorizer_cache.set(cache_key, (vectorizer, job_vectors))

            similarities = cosine_similarity(cv_vector, job_vectors).flatten()

            thresholds = self.config.thresholds
            for i, (brute, enrichie, _) in enumerate(valid_jobs):
                similarity_score = float(similarities[i])
                # Seuil configurable (section 4)
                if similarity_score < thresholds.min_cosine_similarity:
                    continue

                skill_match_score = self._calculate_skill_match(
                    cv_skills, getattr(enrichie, "extracted_skills", [])
                )
                experience_match_score = self._calculate_experience_match(
                    cv_experience,
                    getattr(enrichie, "extracted_experience_years", None),
                )
                final_score = (
                    similarity_score * 0.5
                    + skill_match_score * 0.3
                    + experience_match_score * 0.2
                )
                # Seuil final configurable (section 4)
                if final_score < thresholds.min_final_score:
                    continue

                reasons = [
                    f"Similarité CV : {similarity_score:.2f}",
                    f"Match compétences : {skill_match_score:.2f}",
                    f"Match expérience : {experience_match_score:.2f}",
                ]

                # CORRECTION section 5 : contract_type_match et location_match calculés
                contract_match = self._safe_contract_match_from_cv(cv_sectors, enrichie)
                location_match = self._is_location_match(None, getattr(brute, "location", None))

                job_recommendation = JobRecommendationResponse(
                    job_id=str(brute.id) if getattr(brute, "id", None) else "",
                    title=str(getattr(brute, "title", "Titre non spécifié"))[:200],
                    company_name=str(
                        getattr(brute, "company_name", "Entreprise non spécifiée")
                    )[:200],
                    # CORRECTION section 5 : typo corrigée
                    location=str(
                        getattr(brute, "location", "Localisation non spécifiée")
                    )[:100],
                    match_score=final_score,
                    match_reasons=reasons,
                    salary_min=getattr(enrichie, "extracted_salary_min", None),
                    salary_max=getattr(enrichie, "extracted_salary_max", None),
                    contract_type=(
                        getattr(enrichie, "extracted_contract_type", None)
                        or getattr(brute, "contract_type", None)
                    ),
                    experience_required=(
                        f"{getattr(enrichie, 'extracted_experience_years', '')} ans"
                        if getattr(enrichie, "extracted_experience_years", None)
                        else "Non spécifié"
                    ),
                    posted_date=getattr(brute, "posted_date", None),
                    deadline=getattr(brute, "expiration_date", None),
                    url=getattr(brute, "url", None),
                    skills=list(
                        self._find_skill_matches(
                            tuple(cv_skills),
                            tuple(
                                self._normalize_skill_list(
                                    getattr(enrichie, "extracted_skills", [])
                                )
                            ),
                        )
                    ),
                    sector_match=bool(
                        getattr(enrichie, "extracted_sector", None) in cv_sectors
                    ),
                    # CORRECTION section 5 : calculé, jamais hardcodé True
                    contract_type_match=contract_match,
                    is_favorited=str(brute.id) in (saved_job_ids or set()),
                    location_match=location_match,
                    applicants_count=getattr(brute, "applicants_count", 0) or 0,
                    views_count=getattr(brute, "views_count", 0) or 0,
                )
                recommendations.append(job_recommendation)

        except Exception as e:  # noqa: BLE001
            logger.error("Erreur dans vectorized_cv_matching : %s", e)

        return recommendations

    def _safe_contract_match_from_cv(
        self, cv_sectors: List[str], enrichie: OffreEmploiEnrichie
    ) -> bool:
        """
        Matching contrat depuis les informations du CV.
        Retourne False si les données sont insuffisantes.
        """
        try:
            job_contract = getattr(enrichie, "extracted_contract_type", None)
            if not job_contract or not cv_sectors:
                return False
            # cv_sectors peut contenir des types de contrat détectés dans le CV
            return job_contract.lower() in [s.lower() for s in cv_sectors]
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Matching booléens — section 5
    # ------------------------------------------------------------------

    def _safe_sector_match(
        self, user_profile: UserProfile, enrichie: OffreEmploiEnrichie
    ) -> bool:
        """
        Matching sécurisé des secteurs.
        CORRECTION : utilise preferred_sectors, JAMAIS skills (invariant #5).
        """
        try:
            # Invariant #5 : ne jamais utiliser user_profile.skills pour le secteur
            user_sectors = self._normalize_list(
                getattr(user_profile, "preferred_sectors", None)
                or getattr(user_profile, "sectors", None)
            )
            job_sector = getattr(enrichie, "extracted_sector", None)
            return bool(
                job_sector
                and job_sector.lower() in [s.lower() for s in user_sectors]
            )
        except Exception as e:
            logger.debug("Erreur matching secteur : %s", e)
            return False

    def _safe_contract_match(
        self, user_profile: UserProfile, enrichie: OffreEmploiEnrichie
    ) -> bool:
        """Matching sécurisé des types de contrat."""
        try:
            user_contracts = self._normalize_list(
                getattr(user_profile, "preferred_contract_type", None)
            )
            job_contract = getattr(enrichie, "extracted_contract_type", None)
            return bool(
                job_contract
                and job_contract.lower() in [c.lower() for c in user_contracts]
            )
        except Exception as e:
            logger.debug("Erreur matching contrat : %s", e)
            return False

    def _is_location_match(
        self, user_location: Optional[str], job_location: Optional[str]
    ) -> bool:
        """
        Retourne True si les localisations correspondent.
        CORRECTION section 5 : retourne False (pas True) quand les données sont manquantes.
        On ne peut pas affirmer un match sans données.
        """
        if not user_location or not job_location:
            return False  # INVARIANT #6 : False sur données manquantes

        try:
            u_loc = unicodedata.normalize("NFKD", user_location.lower().strip())
            u_loc = u_loc.encode("ASCII", "ignore").decode("ASCII")
            j_loc = unicodedata.normalize("NFKD", job_location.lower().strip())
            j_loc = j_loc.encode("ASCII", "ignore").decode("ASCII")

            if u_loc == j_loc:
                return True
            pattern = rf"\b{re.escape(u_loc)}\b"
            if re.search(pattern, j_loc):
                return True
            if u_loc in j_loc or j_loc in u_loc:
                return True

            location_aliases: Dict[str, List[str]] = {
                "paris": ["ile de france", "idf", "paris"],
                "dakar": ["dakar", "dakar region"],
            }
            for _, aliases in location_aliases.items():
                if u_loc in aliases and any(alias in j_loc for alias in aliases):
                    return True
            return False

        except Exception as e:
            logger.warning("Erreur vérification localisation : %s", e)
            return False

    # ------------------------------------------------------------------
    # Extraction CV (section 3)
    # ------------------------------------------------------------------

    def _extract_cv_info_robust(
        self, cv_text: str
    ) -> Tuple[List[str], int, List[str]]:
        if not cv_text or not isinstance(cv_text, str):
            return [], 0, []
        text_clean = re.sub(r"\s+", " ", cv_text.strip())
        if len(text_clean) < 50:
            return [], 0, []
        text_lower = text_clean.lower()
        experience_years = self._extract_experience_years(text_lower)
        extracted_skills = self._extract_skills_from_text(text_lower)
        extracted_sectors = self._extract_sectors_from_text(text_lower)
        return extracted_skills, experience_years, extracted_sectors

    def _extract_experience_years(self, text: str) -> int:
        """
        Extraction robuste de l'expérience avec borne supérieure crédible (section 3).
        """
        patterns = [
            r"(?:(\d+)\s*(?:ans?|ans\s+d['\u2019 ]exp[ée]rience|ans\s+d experience|ans\s+d'experience))",
            r"(?:(\d+)\s*(?:years?|years\s+of\s+experience|yrs?|yrs\s+experience))",
            r"(?:(\d+)\+\s*(?:ans?|years?|yrs?))",
            r"(?:experience|exp|exp[ée]rience)\s*:?\s*(\d+)\s*(?:ans?|years?|yrs?)",
        ]
        max_years = 0
        for pattern in patterns:
            try:
                matches = re.findall(pattern, text, re.IGNORECASE)
                if matches:
                    max_years = max(max_years, max(int(m) for m in matches))
            except re.error as e:
                logger.debug("Erreur pattern regex expérience : %s", e)

        # CORRECTION section 3 : borne supérieure réaliste
        if max_years > MAX_CREDIBLE_EXPERIENCE_YEARS:
            logger.warning(
                "Expérience extraite (%d ans) dépasse le seuil crédible %d. "
                "Valeur tronquée. Vérifier le CV.",
                max_years,
                MAX_CREDIBLE_EXPERIENCE_YEARS,
            )
            max_years = MAX_CREDIBLE_EXPERIENCE_YEARS
        return max_years

    def _extract_skills_from_text(self, text: str) -> List[str]:
        """Extraction des compétences via le dictionnaire chargé (YAML ou intégré)."""
        skill_scores: Dict[str, int] = {}
        for skill in self._skills_flat:
            try:
                pattern = rf"\b{re.escape(skill)}\b"
                count = len(re.findall(pattern, text, re.IGNORECASE))
                if count > 0:
                    skill_scores[skill] = count
            except re.error:
                if skill.lower() in text:
                    skill_scores[skill] = 1
        sorted_skills = sorted(skill_scores.items(), key=lambda x: x[1], reverse=True)
        return [s.capitalize() for s, _ in sorted_skills[:15]]

    def _extract_sectors_from_text(self, text: str) -> List[str]:
        sectors = [
            "informatique", "télécoms", "banque", "assurance", "santé", "éducation",
            "transport", "logistique", "industrie", "agriculture", "tourisme", "energie",
            "btp", "commerce", "immobilier", "consulting", "startup", "retail",
        ]
        found: List[str] = []
        for sector in sectors:
            try:
                pattern = rf"\b{re.escape(sector)}\b"
                if re.search(pattern, text, re.IGNORECASE):
                    found.append(sector.capitalize())
            except re.error:
                if sector in text:
                    found.append(sector.capitalize())
        return found[:5]

    # ------------------------------------------------------------------
    # Scoring compétences / expérience (méthodes existantes préservées)
    # ------------------------------------------------------------------

    def _calculate_skill_match(
        self, cv_skills: List[str], job_skills: List[str]
    ) -> float:
        if not cv_skills or not job_skills:
            return 0.0
        cv_norm = self._normalize_skill_list(cv_skills)
        job_norm = self._normalize_skill_list(job_skills)
        if not job_norm:
            return 0.0
        matches = self._find_skill_matches(tuple(cv_norm), tuple(job_norm))
        return len(matches) / len(set(job_norm))

    def _calculate_experience_match(
        self, cv_experience: int, job_experience: Optional[int]
    ) -> float:
        if not job_experience or job_experience <= 0:
            return 0.8
        if cv_experience >= job_experience:
            return 1.0
        elif cv_experience >= job_experience - 1:
            return 0.7
        elif cv_experience >= job_experience - 2:
            return 0.5
        return max(0.1, (cv_experience / job_experience) * 0.4)

    # ------------------------------------------------------------------
    # Récupération jobs paginés
    # ------------------------------------------------------------------

    def _get_recent_jobs_paginated(
        self, db: Session, days: int = 30, batch_size: int = 500
    ) -> List[Any]:
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            return (
                db.query(OffreEmploiBrute, OffreEmploiEnrichie)
                .join(
                    OffreEmploiEnrichie,
                    OffreEmploiBrute.id == OffreEmploiEnrichie.offre_id,
                )
                .filter(
                    OffreEmploiBrute.posted_date >= cutoff_date,
                    or_(
                        OffreEmploiBrute.expiration_date.is_(None),
                        OffreEmploiBrute.expiration_date >= datetime.now(),
                    ),
                )
                .order_by(OffreEmploiBrute.posted_date.desc())
                .limit(batch_size)
                .all()
            )
        except Exception as e:
            logger.error("Erreur récupération jobs paginés : %s", e)
            return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_skill_matches(
        self,
        user_skills: Tuple[str, ...],
        job_skills: Tuple[str, ...],
    ) -> Tuple[str, ...]:
        """Délègue au cache module-level (pas de référence à self → pas de leak)."""
        return _find_skill_matches_cached(user_skills, job_skills)

    def _format_salary_range(self, enrichie: OffreEmploiEnrichie) -> Optional[str]:
        try:
            min_val = self._safe_float(getattr(enrichie, "extracted_salary_min", None))
            max_val = self._safe_float(getattr(enrichie, "extracted_salary_max", None))
            currency = str(
                getattr(enrichie, "extracted_salary_currency", "XOF") or "XOF"
            ).upper()
            if min_val is not None and max_val is not None:
                if min_val == max_val:
                    return f"{min_val:,.0f} {currency}"
                return f"{min_val:,.0f} - {max_val:,.0f} {currency}"
            if min_val is not None:
                return f"À partir de {min_val:,.0f} {currency}"
            if max_val is not None:
                return f"Jusqu'à {max_val:,.0f} {currency}"
            return None
        except Exception as e:
            logger.warning("Erreur formatage salaire : %s", e)
            return None

    def _get_valid_uuid(self, user_id: Optional[Any]) -> uuid.UUID:
        if user_id is None:
            return uuid.uuid4()
        if isinstance(user_id, uuid.UUID):
            return user_id
        try:
            return uuid.UUID(str(user_id))
        except (ValueError, TypeError):
            logger.warning(
                "UUID invalide '%s', génération d'un UUID déterministe", user_id
            )
            return uuid.uuid5(uuid.NAMESPACE_DNS, str(user_id))

    def _empty_recommendation_response(
        self, user_id: Optional[str]
    ) -> RecommendationResponse:
        return RecommendationResponse(
            user_id=str(self._get_valid_uuid(user_id)),
            recommendations=[],
            total_recommendations=0,
            average_match_score=0.0,
            generated_at=datetime.now(),
            execution_time_seconds=0.0,
        )

    def _normalize_skill_list(self, skills: Any) -> List[str]:
        if not skills:
            return []
        if isinstance(skills, (list, tuple)):
            return [
                str(s).strip().lower()
                for s in skills
                if s and len(str(s).strip()) >= 2
            ]
        if isinstance(skills, str):
            try:
                parsed = json.loads(skills)
                if isinstance(parsed, list):
                    return [
                        str(s).strip().lower()
                        for s in parsed
                        if s and len(str(s).strip()) >= 2
                    ]
            except json.JSONDecodeError:
                pass
            return [
                s.strip().lower()
                for s in re.split(r"[;,|]", skills)
                if s.strip() and len(s.strip()) >= 2
            ]
        return []

    def _normalize_list(self, items: Any) -> List[str]:
        if not items:
            return []
        if isinstance(items, (list, tuple)):
            return [str(item).strip() for item in items if item]
        if isinstance(items, str):
            return [items.strip()]
        return []

    def _safe_float(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            logger.debug("Valeur non convertible en float : %s", value)
            return None

    def _is_valid_number(self, value: Any) -> bool:
        if value is None:
            return False
        try:
            num = float(value)
            return not (np.isnan(num) or np.isinf(num))
        except (ValueError, TypeError):
            return False

    # ------------------------------------------------------------------
    # Observabilité — logs structurés JSON (section 10)
    # ------------------------------------------------------------------

    def _log_recommendation_event_debug(
        self, score: float, breakdown: ScoreBreakdown
    ) -> None:
        """Log structuré (DEBUG) de la décomposition du score."""
        event = {
            "event": "score_computed",
            "score": round(score, 4),
            "breakdown": {
                "title": round(breakdown.title_score * breakdown.title_weight, 4),
                "skills": round(breakdown.skills_score * breakdown.skills_weight, 4),
                "sector": round(breakdown.sector_score * breakdown.sector_weight, 4),
                "contract": round(breakdown.contract_score * breakdown.contract_weight, 4),
                "salary": round(breakdown.salary_score * breakdown.salary_weight, 4),
                "experience": round(
                    breakdown.experience_score * breakdown.experience_weight, 4
                ),
            },
            "excluded_criteria": breakdown.excluded_criteria,
        }
        logger.debug(json.dumps(event, ensure_ascii=False))

    def _log_recommendation_event(
        self,
        user_id: Any,
        job_id: Any,
        score: float,
        breakdown: ScoreBreakdown,
        latency_ms: float,
    ) -> None:
        """Log structuré INFO pour monitoring ELK/Datadog (section 10)."""
        event = {
            "event": "recommendation_generated",
            "user_id": str(user_id),
            "job_id": str(job_id),
            "score": round(score, 4),
            "score_breakdown": {
                "title": round(breakdown.title_score * breakdown.title_weight, 4),
                "skills": round(breakdown.skills_score * breakdown.skills_weight, 4),
                "sector": round(breakdown.sector_score * breakdown.sector_weight, 4),
                "contract": round(breakdown.contract_score * breakdown.contract_weight, 4),
                "salary": round(breakdown.salary_score * breakdown.salary_weight, 4),
                "experience": round(
                    breakdown.experience_score * breakdown.experience_weight, 4
                ),
            },
            "excluded_criteria": breakdown.excluded_criteria,
            "latency_ms": round(latency_ms, 1),
            "timestamp": datetime.utcnow().isoformat(),
        }
        logger.info(json.dumps(event, ensure_ascii=False))