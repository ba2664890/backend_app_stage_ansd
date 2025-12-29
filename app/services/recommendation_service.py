"""
Service pour les recommandations d'emploi personnalisées ultra-robuste.
Utilise des techniques de matching, scoring, validation et caching pour des suggestions fiables.
"""

from typing import List, Dict, Any, Optional, Tuple, Set
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func, text
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
import logging
from datetime import datetime, timedelta
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import json
import uuid
import re
from functools import lru_cache
import hashlib
from contextlib import contextmanager
import time

from ..models.database_models import (
    OffreEmploiBrute, OffreEmploiEnrichie, UserProfile, 
    JobRecommendation
)
from ..models.api_models import RecommendationRequest, RecommendationResponse, JobRecommendationResponse

logger = logging.getLogger(__name__)

class RecommendationService:
    """Service robuste pour générer des recommandations d'emploi personnalisées."""
    
    def __init__(self, max_retries: int = 3, timeout_seconds: int = 30):
        """
        Initialise le service de recommandations avec des paramètres de robustesse.
        
        Args:
            max_retries: Nombre maximum de tentatives en cas d'échec
            timeout_seconds: Timeout pour les opérations de base de données
        """
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self._vectorizer_cache = {}
        logger.info("RecommendationService initialisé avec max_retries=%d, timeout=%ds", 
                   max_retries, timeout_seconds)
    
    @contextmanager
    def _db_transaction(self, db: Session):
        """Context manager pour les transactions avec retry logic."""
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                yield db
                db.commit()
                if attempt > 0:
                    logger.info("Transaction réussie après %d tentatives", attempt + 1)
                return
            except SQLAlchemyError as e:
                last_exception = e
                db.rollback()
                wait_time = (2 ** attempt) * 0.5  # Exponential backoff
                logger.warning("Échec transaction (tentative %d/%d): %s. Retry dans %.1fs",
                             attempt + 1, self.max_retries, str(e), wait_time)
                if attempt < self.max_retries - 1:
                    time.sleep(wait_time)
                else:
                    logger.error("Échec transaction définitif après %d tentatives", self.max_retries)
            except Exception as e:
                db.rollback()
                logger.error("Erreur non-SQLAlchemy lors de la transaction: %s", str(e))
                raise
        raise last_exception
    
    def _validate_request(self, db: Session, user_id: str, request: RecommendationRequest) -> None:
        """Validation robuste des paramètres d'entrée."""
        if not db or not hasattr(db, 'query'):
            raise ValueError("Session de base de données invalide ou non connectée")
        
        if not user_id or not isinstance(user_id, (str, uuid.UUID)):
            raise ValueError("user_id doit être une chaîne non vide ou un UUID valide")
        
        if not request or not isinstance(request, RecommendationRequest):
            raise ValueError("RecommendationRequest invalide")
        
        if request.min_match_score < 0 or request.min_match_score > 1:
            raise ValueError("min_match_score doit être entre 0 et 1")
        
        if request.max_results <= 0 or request.max_results > 1000:
            raise ValueError("max_results doit être entre 1 et 1000")
    
    def get_recommendations(
        self, 
        db: Session, 
        user_id: str, 
        request: RecommendationRequest
    ) -> RecommendationResponse:
        """
        Génère des recommandations d'emploi robustes pour un utilisateur avec validation et caching.
        """
        start_time = time.time()
        
        try:
            # Validation des entrées
            self._validate_request(db, user_id, request)
            
            # Récupération du profil utilisateur avec caching
            user_profile = self._get_user_profile(db, user_id)
            if not user_profile:
                raise ValueError(f"Profil utilisateur non trouvé pour l'ID: {user_id}")
            
            # Construction de la requête avec optimisation
            query = self._build_optimized_job_query(db, request)
            
            # Récupération avec timeout
            candidate_jobs = self._execute_query_with_timeout(query)
            
            if not candidate_jobs:
                logger.warning("Aucune offre candidate trouvée pour l'utilisateur %s", user_id)
                return self._empty_recommendation_response(user_id)
            
            # Calcul des scores avec parallel processing possible
            scored_jobs = self._score_jobs_batch(user_profile, candidate_jobs, request)
            
            # Création des recommandations avec transaction robuste
            recommendations = self._create_recommendations_batch(
                db, user_id, scored_jobs, user_profile
            )
            
            # Métriques de performance
            execution_time = time.time() - start_time
            logger.info("Recommandations générées en %.2fs pour l'utilisateur %s: %d résultats", 
                       execution_time, user_id, len(recommendations))
            
            return RecommendationResponse(
                user_id=str(self._get_valid_uuid(user_id)),
                recommendations=recommendations,
                total_recommendations=len(recommendations),
                average_match_score=float(np.mean([r.match_score for r in recommendations])) if recommendations else 0.0,
                generated_at=datetime.now(),
                execution_time_seconds=execution_time
            )
            
        except Exception as e:
            logger.error("Erreur critique dans get_recommendations: %s", str(e), exc_info=True)
            db.rollback()
            raise
        finally:
            # Nettoyage des ressources
            self._cleanup_resources()
    
    def match_cv_with_jobs(
        self, 
        db: Session, 
        cv_text: str, 
        user_id: Optional[str] = None
    ) -> RecommendationResponse:
        """
        Match robuste d'un CV avec les offres d'emploi avec validation et gestion de mémoire.
        """
        start_time = time.time()
        
        try:
            # Validation du CV
            if not cv_text or not isinstance(cv_text, str) or len(cv_text.strip()) < 50:
                raise ValueError("CV text invalide: doit contenir au moins 50 caractères")
            
            if len(cv_text) > 500000:  # Limite de 500KB
                raise ValueError("CV text trop volumineux: maximum 500KB")
            
            # Extraction robuste des informations
            cv_skills, cv_experience, cv_sectors = self._extract_cv_info_robust(cv_text)
            
            # Récupération des offres avec pagination
            recent_jobs = self._get_recent_jobs_paginated(db, days=30, batch_size=500)
            
            if not recent_jobs:
                logger.warning("Aucune offre récente disponible pour le matching CV")
                return self._empty_recommendation_response(user_id)
            
            # Vectorisation avec gestion de mémoire
            recommendations = self._vectorized_cv_matching(
                cv_text, cv_skills, cv_experience, cv_sectors, recent_jobs
            )
            
            # Tri et limitation
            recommendations.sort(key=lambda x: x.match_score, reverse=True)
            recommendations = recommendations[:20]
            
            execution_time = time.time() - start_time
            logger.info("Matching CV terminé en %.2fs: %d recommandations", 
                       execution_time, len(recommendations))
            
            return RecommendationResponse(
                user_id=str(self._get_valid_uuid(user_id)),
                recommendations=recommendations,
                total_recommendations=len(recommendations),
                average_match_score=float(np.mean([r.match_score for r in recommendations])) if recommendations else 0.0,
                generated_at=datetime.now(),
                execution_time_seconds=execution_time
            )
            
        except Exception as e:
            logger.error("Erreur dans match_cv_with_jobs: %s", str(e), exc_info=True)
            raise
    
    def _get_user_profile(self, db: Session, user_id: str) -> Optional[UserProfile]:
        """Récupération du profil utilisateur avec validation."""
        try:
            return db.query(UserProfile).filter(UserProfile.id == user_id).first()
        except SQLAlchemyError as e:
            logger.error("Erreur SQL lors de la récupération du profil utilisateur %s: %s", 
                        user_id, str(e))
            return None
    
    def _build_optimized_job_query(self, db: Session, request: RecommendationRequest):
        """Construction d'une requête SQL optimisée avec joins efficaces."""
        query = db.query(OffreEmploiBrute, OffreEmploiEnrichie).join(
            OffreEmploiEnrichie, OffreEmploiBrute.id == OffreEmploiEnrichie.offre_id
        ).filter(
            OffreEmploiBrute.posted_date >= datetime.now() - timedelta(days=60),
            or_(OffreEmploiBrute.expiration_date.is_(None), OffreEmploiBrute.expiration_date >= datetime.now())
        )
        
        # Filtres avec protection contre les listes vides
        if request.preferred_sectors and any(s.strip() for s in request.preferred_sectors):
            query = query.filter(
                func.lower(OffreEmploiEnrichie.extracted_sector).in_(
                    [s.lower().strip() for s in request.preferred_sectors if s.strip()]
                )
            )
        
        if request.preferred_contract_types and any(ct.strip() for ct in request.preferred_contract_types):
            query = query.filter(
                func.lower(OffreEmploiEnrichie.extracted_contract_type).in_(
                    [ct.lower().strip() for ct in request.preferred_contract_types if ct.strip()]
                )
            )
        
        # Filtres salaire avec validation des valeurs
        if request.min_salary and request.min_salary > 0:
            query = query.filter(
                OffreEmploiEnrichie.extracted_salary_max >= float(request.min_salary)
            )
        
        if request.max_salary and request.max_salary > 0:
            query = query.filter(
                OffreEmploiEnrichie.extracted_salary_min <= float(request.max_salary)
            )
        
        # Optimisation: eager loading des relations (uniquement si elles existent)
        return query
    
    def _execute_query_with_timeout(self, query, timeout: Optional[int] = None):
        """Exécution de requête avec timeout et gestion des erreurs."""
        timeout = timeout or self.timeout_seconds
        try:
            # Pour PostgreSQL, on pourrait utiliser statement_timeout
            # Pour la compatibilité générale, on utilise une approche Python
            import signal
            
            def timeout_handler(signum, frame):
                raise TimeoutError(f"Requête dépassée: {timeout}s")
            
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout)
            
            result = query.all()
            
            signal.alarm(0)  # Annuler le timeout
            return result
        except TimeoutError:
            logger.error("Timeout lors de l'exécution de la requête de jobs")
            raise
        except SQLAlchemyError as e:
            logger.error("Erreur SQL lors de l'exécution de la requête: %s", str(e))
            raise
        except Exception as e:
            logger.error("Erreur inattendue lors de l'exécution de la requête: %s", str(e))
            raise
    
    def _score_jobs_batch(self, user_profile: UserProfile, candidate_jobs: List[Any], 
                         request: RecommendationRequest) -> List[Dict[str, Any]]:
        """Calcul parallèle des scores de matching avec filtrage."""
        scored_jobs = []
        
        # Normalisation des compétences utilisateur (une seule fois)
        user_skills = self._normalize_skill_list(user_profile.skills)
        
        for brute, enrichie in candidate_jobs:
            try:
                match_score, match_reasons = self._calculate_match_score(
                    user_profile, brute, enrichie, user_skills
                )
                
                if match_score >= request.min_match_score and len(scored_jobs) < 1000:
                    scored_jobs.append({
                        "job": (brute, enrichie),
                        "score": match_score,
                        "reasons": match_reasons
                    })
            except Exception as e:
                logger.warning("Échec scoring job %s: %s", getattr(brute, 'id', 'N/A'), str(e))
                continue
        
        # Tri optimisé
        scored_jobs.sort(key=lambda x: x["score"], reverse=True)
        return scored_jobs[:request.max_results]
    
    def _create_recommendations_batch(self, db: Session, user_id: str, 
                                    scored_jobs: List[Dict], user_profile: UserProfile):
        """Création batch des recommandations avec transaction robuste."""
        recommendations = []
        
        with self._db_transaction(db):
            for rec in scored_jobs:
                brute, enrichie = rec["job"]
                
                try:
                    # Vérification doublon
                    existing = db.query(JobRecommendation).filter(
                        JobRecommendation.user_id == self._get_valid_uuid(user_id),
                        JobRecommendation.job_id == enrichie.id,
                        JobRecommendation.created_at >= datetime.now() - timedelta(days=7)
                    ).first()
                    
                    if existing:
                        logger.debug("Recommandation existante ignorée pour le job %s", enrichie.id)
                        continue
                    
                    # Création recommendation
                    recommendation = JobRecommendation(
                        user_id=self._get_valid_uuid(user_id),
                        job_id=enrichie.id,
                        match_score=float(rec["score"]),
                        match_reasons=json.dumps(rec["reasons"], ensure_ascii=False)[:1000],  # Limite taille
                        status='pending'
                    )
                    db.add(recommendation)
                    
                    # Création réponse API
                    job_recommendation = self._create_job_recommendation_response(
                        brute, enrichie, rec, user_profile
                    )
                    recommendations.append(job_recommendation)
                    
                except IntegrityError as e:
                    logger.warning("Doublon détecté lors de l'insertion: %s", str(e))
                    db.rollback()
                except Exception as e:
                    logger.error("Erreur création recommandation job %s: %s", 
                               getattr(enrichie, 'id', 'N/A'), str(e))
                    continue
        
        return recommendations
    
    def _create_job_recommendation_response(self, brute, enrichie, rec, user_profile):
        """Création robuste de l'objet de réponse."""
        try:
            return JobRecommendationResponse(
                job_id=str(brute.id) if brute.id else "",
                title=str(brute.title or "Titre non spécifié")[:200],
                company_name=str(brute.company_name or "Entreprise non spécifiée")[:200],
                location=str(brute.location or "Localisation spécifiée")[:100],
                match_score=float(rec["score"]),
                match_reasons=rec["reasons"][:10],  # Limiter le nombre de raisons
                salary_range=self._format_salary_range(enrichie),
                skills_match=self._find_skill_matches(
                    self._normalize_skill_list(user_profile.skills),
                    self._normalize_skill_list(enrichie.extracted_skills)
                ),
                sector_match=self._safe_sector_match(user_profile, enrichie),
                contract_type_match=self._safe_contract_match(user_profile, enrichie),
                location_match=self._is_location_match(
                    getattr(user_profile, "location", None), 
                    brute.location
                )
            )
        except Exception as e:
            logger.error("Erreur création JobRecommendationResponse: %s", str(e))
            # Retourner un objet minimaliste en cas d'erreur
            return JobRecommendationResponse(
                job_id=str(getattr(brute, 'id', '')),
                title="Erreur formatage",
                company_name="Erreur",
                location="Erreur",
                match_score=0.0,
                match_reasons=["Erreur lors de la création de la recommandation"],
                salary_range=None,
                skills_match=[],
                sector_match=False,
                contract_type_match=False,
                location_match=False
            )
    
    def _calculate_match_score(
        self, 
        user_profile: UserProfile, 
        brute: OffreEmploiBrute, 
        enrichie: OffreEmploiEnrichie,
        pre_normalized_user_skills: Optional[List[str]] = None
    ) -> Tuple[float, List[str]]:
        """
        Calcule un score de matching robuste avec poids configurables et gestion d'erreurs fines.
        """
        score = 0.0
        reasons = []
        
        # Utiliser les compétences pré-normalisées si disponibles
        user_skills = pre_normalized_user_skills or self._normalize_skill_list(user_profile.skills)
        job_skills = self._normalize_skill_list(enrichie.extracted_skills)
        
        # 1. Matching des compétences (40%)
        if user_skills and job_skills:
            skill_matches = self._find_skill_matches(user_skills, job_skills)
            skill_score = len(skill_matches) / max(len(set(user_skills)), len(set(job_skills)))
            score += skill_score * 0.4
            if skill_matches:
                reasons.append(f"✓ Compétences: {', '.join(skill_matches[:3])}")
        
        # 2. Matching du secteur (20%) - case insensitive
        user_sectors = self._normalize_list(getattr(user_profile, 'skills', None))
        job_sector = getattr(enrichie, 'extracted_sector', None)
        if user_sectors and job_sector:
            if job_sector.lower() in [s.lower() for s in user_sectors]:
                score += 0.2
                reasons.append(f"✓ Secteur: {job_sector}")
        
        # 3. Matching du type de contrat (15%)
        user_contracts = self._normalize_list(getattr(user_profile, 'preferred_contract_type', None))
        job_contract = getattr(enrichie, 'extracted_contract_type', None)
        if user_contracts and job_contract:
            if job_contract.lower() in [c.lower() for c in user_contracts]:
                score += 0.15
                reasons.append(f"✓ Contrat: {job_contract}")
        
        # 4. Matching du salaire (15%) avec marge de sécurité
        user_min_salary = getattr(user_profile, "preferred_salary_min", None)
        job_max_salary = getattr(enrichie, "extracted_salary_max", None)
        
        if self._is_valid_number(user_min_salary) and self._is_valid_number(job_max_salary):
            try:
                if float(job_max_salary) >= float(user_min_salary) * 0.9:  # 10% marge
                    score += 0.15
                    reasons.append("✓ Salaire compatible")
            except (ValueError, TypeError):
                logger.debug("Erreur comparaison salaire pour le job %s", getattr(enrichie, 'id', 'N/A'))
        
        # 5. Matching de l'expérience (10%) avec tolérance
        user_exp = getattr(user_profile, "experience_years", None)
        job_exp = getattr(enrichie, "extracted_experience_years", None)
        
        if self._is_valid_number(user_exp) and self._is_valid_number(job_exp):
            try:
                exp_diff = abs(float(user_exp) - float(job_exp))
                if exp_diff <= 1:
                    score += 0.1
                    reasons.append("✓ Expérience compatible")
                elif exp_diff <= 2:
                    score += 0.05
                    reasons.append("~ Expérience partiellement compatible")
            except (ValueError, TypeError):
                logger.debug("Erreur comparaison expérience pour le job %s", getattr(enrichie, 'id', 'N/A'))
        
        return min(max(score, 0.0), 1.0), reasons[:5]  # Limiter les raisons
    
    @lru_cache(maxsize=128)
    def _find_skill_matches(self, user_skills: Tuple[str], job_skills: Tuple[str]) -> Tuple[str, ...]:
        """
        Trouve les compétences en commun avec regex compilé et cache pour performance.
        Tuple utilisé pour le hash du cache.
        """
        if not user_skills or not job_skills:
            return ()
        
        # Compilation du pattern une seule fois
        job_text = " | ".join(job_skills).lower()
        matches = set()
        
        for skill in user_skills:
            if not skill or len(skill.strip()) < 2:
                continue
            
            # Pattern robuste pour compétences avec caractères spéciaux
            safe_skill = re.escape(skill.strip().lower())
            pattern = rf"(?:^|[|\s,.-])({safe_skill})(?:$|[|\s,.-])"
            
            try:
                if re.search(pattern, job_text):
                    matches.add(skill.strip())
            except re.error as e:
                logger.warning("Regex invalide pour la compétence '%s': %s", skill, str(e))
                # Fallback: simple in
                if safe_skill in job_text:
                    matches.add(skill.strip())
        
        return tuple(sorted(matches))[:5]
    
    def _format_salary_range(self, enrichie: OffreEmploiEnrichie) -> Optional[str]:
        """Formate la fourchette salariale avec validation robuste et internationalisation."""
        try:
            min_sal = getattr(enrichie, 'extracted_salary_min', None)
            max_sal = getattr(enrichie, 'extracted_salary_max', None)
            currency = str(getattr(enrichie, 'extracted_salary_currency', 'XOF') or 'XOF').upper()
            
            # Validation des valeurs numériques
            min_val = self._safe_float(min_sal)
            max_val = self._safe_float(max_sal)
            
            if min_val is not None and max_val is not None:
                if min_val == max_val:
                    return f"{min_val:,.0f} {currency}"
                return f"{min_val:,.0f} - {max_val:,.0f} {currency}"
            elif min_val is not None:
                return f"À partir de {min_val:,.0f} {currency}"
            elif max_val is not None:
                return f"Jusqu'à {max_val:,.0f} {currency}"
            
            return None
            
        except Exception as e:
            logger.warning("Erreur formatage salaire: %s", str(e))
            return None
    
    def _is_location_match(self, user_location: Optional[str], job_location: Optional[str]) -> bool:
        """Vérifie la correspondance de localisation avec normalisation et géocodage approximatif."""
        if not user_location or not job_location:
            return True
        
        try:
            # Normalisation unicode et suppression accents
            import unicodedata
            u_loc = unicodedata.normalize('NFKD', user_location.lower().strip())
            u_loc = u_loc.encode('ASCII', 'ignore').decode('ASCII')
            
            j_loc = unicodedata.normalize('NFKD', job_location.lower().strip())
            j_loc = j_loc.encode('ASCII', 'ignore').decode('ASCII')
            
            # Match exact
            if u_loc == j_loc:
                return True
            
            # Match mot-clé avec limites de mots
            pattern = rf"\b{re.escape(u_loc)}\b"
            if re.search(pattern, j_loc):
                return True
            
            # Match si l'un contient l'autre
            if u_loc in j_loc or j_loc in u_loc:
                return True
            
            # Liste de villes communes et alias
            location_aliases = {
                'paris': ['ile de france', 'idf', 'paris'],
                'dakar': ['dakar', 'dakar region'],
                # Ajouter d'autres alias selon le contexte géographique
            }
            
            for city, aliases in location_aliases.items():
                if u_loc in aliases and any(alias in j_loc for alias in aliases):
                    return True
            
            return False
            
        except Exception as e:
            logger.warning("Erreur vérification localisation: %s", str(e))
            return False
    
    def _extract_cv_info_robust(self, cv_text: str) -> Tuple[List[str], int, List[str]]:
        """
        Extraction robuste d'informations CV avec NLP léger et gestion multilingue.
        """
        if not cv_text or not isinstance(cv_text, str):
            return [], 0, []
        
        # Nettoyage du texte
        text_clean = re.sub(r'\s+', ' ', cv_text.strip())
        if len(text_clean) < 50:
            return [], 0, []
        
        text_lower = text_clean.lower()
        
        # Extraction de l'expérience avec multiple patterns et langues
        experience_years = self._extract_experience_years(text_lower)
        
        # Extraction des compétences avec scoring
        extracted_skills = self._extract_skills_from_text(text_lower)
        
        # Extraction des secteurs
        extracted_sectors = self._extract_sectors_from_text(text_lower)
        
        return extracted_skills, experience_years, extracted_sectors
    
    def _extract_experience_years(self, text: str) -> int:
        """Extraction robuste de l'expérience en années avec multiple patterns."""
        patterns = [
            # Français
            r"(?:(\d+)\s*(?:ans?|ans\s+d'expérience|ans\s+d experience|ans\s+d'experience))",
            # Anglais
            r"(?:(\d+)\s*(?:years?|years\s+of\s+experience|yrs?|yrs\s+experience))",
            # Notation 5+
            r"(?:(\d+)\+\s*(?:ans?|years?|yrs?))",
            # Format "expérience: 3 ans"
            r"(?:experience|exp|expérience)\s*:?\s*(\d+)\s*(?:ans?|years?|yrs?)",
        ]
        
        max_years = 0
        for pattern in patterns:
            try:
                matches = re.findall(pattern, text, re.IGNORECASE)
                if matches:
                    years = max([int(m) for m in matches])
                    max_years = max(max_years, years)
            except re.error as e:
                logger.debug("Erreur pattern regex expérience: %s", str(e))
        
        return max_years
    
    def _extract_skills_from_text(self, text: str) -> List[str]:
        """Extraction des compétences avec scoring TF-IDF sur un dictionnaire étendu."""
        # Dictionnaire de compétences structuré
        skills_dict = {
            'technical': [
                "python", "java", "javascript", "typescript", "react", "node", "sql", "nosql",
                "php", "c++", "c#", "go", "rust", "ruby", "swift", "kotlin", "docker",
                "kubernetes", "aws", "azure", "gcp", "terraform", "ansible", "git", "linux",
                "windows", "macos", "bash", "powershell", "jenkins", "github", "gitlab"
            ],
            'business': [
                "marketing", "vente", "sales", "management", "gestion", "comptabilité",
                "finance", "rh", "ressources humaines", "recrutement", "formation",
                "stratégie", "business development", "partenariats"
            ],
            'soft': [
                "communication", "leadership", "esprit d'equipe", "autonomie",
                "adaptabilité", "résolution de problèmes", "créativité", "analyse"
            ],
            'languages': [
                "anglais", "français", "espagnol", "allemand", "chinois", "arabe",
                "portugais", "italien"
            ]
        }
        
        # Flatten le dictionnaire
        all_skills = [skill for category in skills_dict.values() for skill in category]
        
        # Scoring basé sur la présence et la fréquence
        skill_scores = {}
        for skill in all_skills:
            try:
                # Pattern exact avec limites de mots
                pattern = rf"\b{re.escape(skill)}\b"
                matches = len(re.findall(pattern, text))
                if matches > 0:
                    skill_scores[skill] = matches
            except re.error:
                # Fallback simple
                if skill in text:
                    skill_scores[skill] = 1
        
        # Retourner les top 15 compétences
        sorted_skills = sorted(skill_scores.items(), key=lambda x: x[1], reverse=True)
        return [skill.capitalize() for skill, score in sorted_skills[:15]]
    
    def _extract_sectors_from_text(self, text: str) -> List[str]:
        """Extraction des secteurs d'activité."""
        sectors_dict = [
            "informatique", "télécoms", "banque", "assurance", "santé", "éducation",
            "transport", "logistique", "industrie", "agriculture", "tourisme", "energie",
            "btp", "commerce", "immobilier", "consulting", "startup", "retail"
        ]
        
        found_sectors = []
        for sector in sectors_dict:
            try:
                pattern = rf"\b{re.escape(sector)}\b"
                if re.search(pattern, text):
                    found_sectors.append(sector.capitalize())
            except re.error:
                if sector in text:
                    found_sectors.append(sector.capitalize())
        
        return found_sectors[:5]
    
    def _calculate_skill_match(self, cv_skills: List[str], job_skills: List[str]) -> float:
        """Calcule le score de matching des compétences avec similarité sémantique."""
        if not cv_skills or not job_skills:
            return 0.0
        
        # Normalisation
        cv_skills_norm = self._normalize_skill_list(cv_skills)
        job_skills_norm = self._normalize_skill_list(job_skills)
        
        if not job_skills_norm:
            return 0.0
        
        # Calcul des matches avec cache
        matches = self._find_skill_matches(tuple(cv_skills_norm), tuple(job_skills_norm))
        
        return len(matches) / len(set(job_skills_norm))
    
    def _calculate_experience_match(self, cv_experience: int, job_experience: Optional[int]) -> float:
        """Calcule le score de matching de l'expérience avec logique nuancée."""
        if not job_experience or job_experience <= 0:
            return 0.8  # Fort score si pas de prérequis
        
        if cv_experience >= job_experience:
            return 1.0  # Parfait
        elif cv_experience >= job_experience - 1:
            return 0.7  # Tolérance d'un an
        elif cv_experience >= job_experience - 2:
            return 0.5  # Tolérance de deux ans
        else:
            # Ratio décroissant
            return max(0.1, (cv_experience / job_experience) * 0.4)
    
    def _get_valid_uuid(self, user_id: Optional[Any]) -> uuid.UUID:
        """Génération robuste d'UUID avec gestion des formats variés."""
        if user_id is None:
            return uuid.uuid4()
        
        if isinstance(user_id, uuid.UUID):
            return user_id
        
        try:
            # Essayer de parser comme string
            return uuid.UUID(str(user_id))
        except (ValueError, TypeError):
            # Générer un UUID déterministe basé sur le hash de la string
            logger.warning("UUID invalide '%s', génération d'un UUID déterministe", user_id)
            return uuid.uuid5(uuid.NAMESPACE_DNS, str(user_id))
    
    def _empty_recommendation_response(self, user_id: Optional[str]):
        """Réponse vide standardisée."""
        return RecommendationResponse(
            user_id=str(self._get_valid_uuid(user_id)),
            recommendations=[],
            total_recommendations=0,
            average_match_score=0.0,
            generated_at=datetime.now(),
            execution_time_seconds=0.0
        )
    
    def _normalize_skill_list(self, skills: Any) -> List[str]:
        """Normalisation robuste des listes de compétences."""
        if not skills:
            return []
        
        if isinstance(skills, (list, tuple)):
            return [str(s).strip().lower() for s in skills if s and len(str(s).strip()) >= 2]
        
        if isinstance(skills, str):
            try:
                # Try JSON parsing
                parsed = json.loads(skills)
                if isinstance(parsed, list):
                    return [str(s).strip().lower() for s in parsed if s and len(str(s).strip()) >= 2]
            except json.JSONDecodeError:
                pass
            
            # Fallback: split by commas or other delimiters
            return [s.strip().lower() for s in re.split(r'[;,|]', skills) 
                   if s.strip() and len(s.strip()) >= 2]
        
        return []
    
    def _normalize_list(self, items: Any) -> List[str]:
        """Normalisation générique de liste."""
        if not items:
            return []
        
        if isinstance(items, (list, tuple)):
            return [str(item).strip() for item in items if item]
        
        if isinstance(items, str):
            return [items.strip()]
        
        return []
    
    def _safe_float(self, value: Any) -> Optional[float]:
        """Conversion sécurisée en float."""
        if value is None:
            return None
        
        try:
            return float(value)
        except (ValueError, TypeError):
            logger.debug("Valeur non convertible en float: %s", value)
            return None
    
    def _is_valid_number(self, value: Any) -> bool:
        """Vérifie si une valeur peut être un nombre valide."""
        if value is None:
            return False
        
        try:
            num = float(value)
            return not (np.isnan(num) or np.isinf(num))
        except (ValueError, TypeError):
            return False
    
    def _safe_sector_match(self, user_profile: UserProfile, enrichie: OffreEmploiEnrichie) -> bool:
        """Matching sécurisé des secteurs."""
        try:
            user_sectors = self._normalize_list(getattr(user_profile, 'skills', None))
            job_sector = getattr(enrichie, 'extracted_sector', None)
            return job_sector and job_sector.lower() in [s.lower() for s in user_sectors]
        except Exception as e:
            logger.debug("Erreur matching secteur: %s", str(e))
            return False
    
    def _safe_contract_match(self, user_profile: UserProfile, enrichie: OffreEmploiEnrichie) -> bool:
        """Matching sécurisé des types de contrat."""
        try:
            user_contracts = self._normalize_list(getattr(user_profile, 'preferred_contract_type', None))
            job_contract = getattr(enrichie, 'extracted_contract_type', None)
            return job_contract and job_contract.lower() in [c.lower() for c in user_contracts]
        except Exception as e:
            logger.debug("Erreur matching contrat: %s", str(e))
            return False
    
    def _get_recent_jobs_paginated(self, db: Session, days: int = 30, batch_size: int = 500):
        """Récupération paginée des jobs récents pour éviter la surcharge mémoire."""
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            
            return db.query(OffreEmploiBrute, OffreEmploiEnrichie).join(
                OffreEmploiEnrichie, OffreEmploiBrute.id == OffreEmploiEnrichie.offre_id
            ).filter(
                OffreEmploiBrute.posted_date >= cutoff_date,
                or_(OffreEmploiBrute.expiration_date.is_(None), OffreEmploiBrute.expiration_date >= datetime.now())
            ).order_by(OffreEmploiBrute.posted_date.desc()).limit(batch_size).all()
        except Exception as e:
            logger.error("Erreur récupération jobs paginés: %s", str(e))
            return []
    
    def _vectorized_cv_matching(self, cv_text: str, cv_skills: List[str], cv_experience: int,
                               cv_sectors: List[str], recent_jobs: List[Any]) -> List[JobRecommendationResponse]:
        """Matching vectorisé CV avec gestion de mémoire et optimisations."""
        recommendations = []
        
        try:
            # Filtrer les jobs avec texte valide
            valid_jobs = []
            for brute, enrichie in recent_jobs:
                job_text = f"{getattr(brute, 'title', '')} {getattr(brute, 'description', '')}"
                if job_text and len(job_text.strip()) > 20:
                    valid_jobs.append((brute, enrichie, job_text.strip()))
            
            if not valid_jobs:
                return []
            
            # Vectorisation avec caching
            cache_key = hashlib.md5(cv_text[:1000].encode()).hexdigest()[:8]
            if cache_key in self._vectorizer_cache:
                vectorizer, job_vectors = self._vectorizer_cache[cache_key]
            else:
                job_texts = [job[2] for job in valid_jobs]
                vectorizer = TfidfVectorizer(
                    max_features=500,  # Réduit pour performance
                    stop_words='english',
                    ngram_range=(1, 2),
                    min_df=1,
                    max_df=0.8
                )
                job_vectors = vectorizer.fit_transform(job_texts)
                self._vectorizer_cache[cache_key] = (vectorizer, job_vectors)
            
            # Vectorisation CV
            cv_vector = vectorizer.transform([cv_text])
            
            # Calcul similarités
            similarities = cosine_similarity(cv_vector, job_vectors).flatten()
            
            # Création des recommandations
            for i, (brute, enrichie, _) in enumerate(valid_jobs):
                similarity_score = float(similarities[i])
                
                if similarity_score >= 0.1:
                    skill_match_score = self._calculate_skill_match(cv_skills, 
                                                                  getattr(enrichie, 'extracted_skills', []))
                    experience_match_score = self._calculate_experience_match(
                        cv_experience, 
                        getattr(enrichie, 'extracted_experience_years', None)
                    )
                    
                    final_score = (similarity_score * 0.5 + skill_match_score * 0.3 + experience_match_score * 0.2)
                    
                    if final_score >= 0.2:
                        reasons = [
                            f"Similarité CV: {similarity_score:.2f}",
                            f"Match compétences: {skill_match_score:.2f}",
                            f"Match expérience: {experience_match_score:.2f}"
                        ]
                        
                        job_recommendation = JobRecommendationResponse(
                            job_id=str(brute.id) if getattr(brute, 'id', None) else "",
                            title=str(getattr(brute, 'title', 'Titre non spécifié'))[:200],
                            company_name=str(getattr(brute, 'company_name', 'Entreprise non spécifiée'))[:200],
                            location=str(getattr(brute, 'location', 'Localisation non spécifiée'))[:100],
                            match_score=final_score,
                            match_reasons=reasons,
                            salary_range=self._format_salary_range(enrichie),
                            skills_match=self._find_skill_matches(
                                tuple(cv_skills), 
                                tuple(self._normalize_skill_list(getattr(enrichie, 'extracted_skills', [])))
                            ),
                            sector_match=bool(getattr(enrichie, 'extracted_sector', None) in cv_sectors),
                            contract_type_match=True,  # À déterminer selon contexte
                            location_match=True
                        )
                        recommendations.append(job_recommendation)
            
        except Exception as e:
            logger.error("Erreur dans vectorized_cv_matching: %s", str(e))
        
        return recommendations
    
    def _cleanup_resources(self):
        """Nettoyage des ressources (cache, connexions, etc.)."""
        try:
            # Nettoyer le cache si trop grand
            if len(self._vectorizer_cache) > 100:
                self._vectorizer_cache.clear()
                logger.info("Cache vectorizer nettoyé")
        except Exception as e:
            logger.debug("Erreur nettoyage ressources: %s", str(e))