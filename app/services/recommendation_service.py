"""
Service pour les recommandations d'emploi personnalisées.
Utilise des techniques de matching et de scoring pour suggérer les meilleures offres.
"""

from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
import logging
from datetime import datetime, timedelta
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import json
import uuid

from ..models.database_models import (
    OffreEmploiBrute, OffreEmploiEnrichie, UserProfile, 
    JobRecommendation
)
from ..models.api_models import RecommendationRequest, RecommendationResponse, JobRecommendationResponse

logger = logging.getLogger(__name__)

class RecommendationService:
    """Service pour générer des recommandations d'emploi personnalisées."""
    
    def __init__(self):
        """Initialise le service de recommandations."""
        pass
    
    def get_recommendations(
        self, 
        db: Session, 
        user_id: str, 
        request: RecommendationRequest
    ) -> RecommendationResponse:
        """
        Génère des recommandations d'emploi pour un utilisateur.
        
        Args:
            db: Session de base de données
            user_id: ID de l'utilisateur
            request: Paramètres de recommandation
            
        Returns:
            Recommandations personnalisées
        """
        try:
            # Récupérer le profil utilisateur
            user_profile = db.query(UserProfile).filter(UserProfile.id == user_id).first()
            if not user_profile:
                raise ValueError("Profil utilisateur non trouvé")
            
            # Construire la requête de base pour les offres
            query = db.query(OffreEmploiBrute, OffreEmploiEnrichie).join(
                OffreEmploiEnrichie, OffreEmploiBrute.id == OffreEmploiEnrichie.offre_id
            ).filter(
                OffreEmploiBrute.posted_date >= datetime.now() - timedelta(days=60)  # Offres récentes
            )
            
            # Appliquer les filtres de l'utilisateur
            if request.preferred_sectors:
                query = query.filter(
                    OffreEmploiEnrichie.extracted_sector.in_(request.preferred_sectors)
                )
            
            if request.preferred_contract_types:
                query = query.filter(
                    OffreEmploiEnrichie.extracted_contract_type.in_(request.preferred_contract_types)
                )
            
            if request.min_salary:
                query = query.filter(
                    OffreEmploiEnrichie.extracted_salary_max >= request.min_salary
                )
            
            if request.max_salary:
                query = query.filter(
                    OffreEmploiEnrichie.extracted_salary_min <= request.max_salary
                )
            
            # Récupérer les offres candidates
            candidate_jobs = query.all()
            
            # Calculer les scores de matching
            scored_jobs = []
            for brute, enrichie in candidate_jobs:
                match_score, match_reasons = self._calculate_match_score(
                    user_profile, brute, enrichie
                )
                
                if match_score >= request.min_match_score:
                    scored_jobs.append({
                        "job": (brute, enrichie),
                        "score": match_score,
                        "reasons": match_reasons
                    })
            
            # Trier par score décroissant
            scored_jobs.sort(key=lambda x: x["score"], reverse=True)
            
            # Limiter aux meilleures recommandations
            top_recommendations = scored_jobs[:request.max_results]
            
            # Créer les objets de recommandation
            recommendations = []
            for rec in top_recommendations:
                brute, enrichie = rec["job"]
                
                # Sauvegarder la recommandation en base
                recommendation = JobRecommendation(
                    user_id=self._get_valid_uuid(user_id),
                    job_id=enrichie.id,
                    match_score=rec["score"],
                    match_reasons=json.dumps(rec["reasons"])  # Sérialiser les raisons
                )
                db.add(recommendation)
                
                # Créer la réponse API - Gérer les valeurs NULL
                job_recommendation = JobRecommendationResponse(
                    job_id=str(brute.id) if brute.id else "",
                    title=brute.title or "Titre non spécifié",
                    company_name=brute.company_name or "Entreprise non spécifiée",
                    location=brute.location or "Localisation non spécifiée",
                    match_score=rec["score"],
                    match_reasons=rec["reasons"],
                    salary_range=self._format_salary_range(enrichie),
                    skills_match=self._find_skill_matches(list(user_profile.skills) if isinstance(user_profile.skills, (list, tuple)) else (user_profile.skills.split(",") if user_profile.skills else []), enrichie.extracted_skills or []),
                    sector_match=enrichie.extracted_sector in (user_profile.skills or []) if enrichie.extracted_sector else False,
                    contract_type_match=enrichie.extracted_contract_type in (user_profile.preferred_contract_type or []) if enrichie.extracted_contract_type else False,
                    location_match=self._is_location_match(getattr(user_profile, "location", None), brute.location)
                )
                recommendations.append(job_recommendation)
            
            db.commit()
            
            # Calculer les métriques globales
            total_recommendations = len(recommendations)
            average_match_score = float(np.mean([r.match_score for r in recommendations])) if recommendations else 0.0
            
            return RecommendationResponse(
                user_id=str(self._get_valid_uuid(user_id)),
                recommendations=recommendations,
                total_recommendations=total_recommendations,
                average_match_score=average_match_score,
                generated_at=datetime.now()
            )
            
        except Exception as e:
            logger.error(f"Error generating recommendations: {e}")
            db.rollback()
            raise
    
    def match_cv_with_jobs(
        self, 
        db: Session, 
        cv_text: str, 
        user_id: Optional[str] = None
    ) -> RecommendationResponse:
        """
        Match un CV avec les offres d'emploi disponibles.
        
        Args:
            db: Session de base de données
            cv_text: Texte extrait du CV
            user_id: ID de l'utilisateur (optionnel)
            
        Returns:
            Recommandations basées sur le CV
        """
        try:
            # Extraire les informations du CV
            cv_skills, cv_experience, cv_sectors = self._extract_cv_info(cv_text)
            
            # Récupérer les offres récentes
            recent_jobs = db.query(OffreEmploiBrute, OffreEmploiEnrichie).join(
                OffreEmploiEnrichie, OffreEmploiBrute.id == OffreEmploiEnrichie.offre_id
            ).filter(
                OffreEmploiBrute.posted_date >= datetime.now() - timedelta(days=30)
            ).limit(1000).all()
            
            # Calculer les scores de matching basés sur le texte
            job_texts = []
            job_data = []
            
            for brute, enrichie in recent_jobs:
                job_text = f"{brute.title or ''} {brute.description or ''} {' '.join(enrichie.extracted_skills or [])}"
                job_texts.append(job_text)
                job_data.append((brute, enrichie))
            
            # Utiliser TF-IDF pour calculer la similarité
            vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
            
            # Vectoriser les textes des offres
            job_vectors = vectorizer.fit_transform(job_texts)
            
            # Vectoriser le CV
            cv_vector = vectorizer.transform([cv_text])
            
            # Calculer les similarités
            similarities = cosine_similarity(cv_vector, job_vectors).flatten()
            
            # Créer les recommandations
            recommendations = []
            for i, (brute, enrichie) in enumerate(job_data):
                similarity_score = similarities[i]
                
                if similarity_score >= 0.1:  # Seuil minimum
                    # Calculer un score composite
                    skill_match_score = self._calculate_skill_match(cv_skills, enrichie.extracted_skills or [])
                    experience_match_score = self._calculate_experience_match(cv_experience, enrichie.extracted_experience_years)
                    
                    final_score = (similarity_score * 0.5 + skill_match_score * 0.3 + experience_match_score * 0.2)
                    
                    if final_score >= 0.2:
                        reasons = [
                            f"Similarité de contenu: {similarity_score:.2f}",
                            f"Matching compétences: {skill_match_score:.2f}",
                            f"Matching expérience: {experience_match_score:.2f}"
                        ]
                        
                        job_recommendation = JobRecommendationResponse(
                            job_id=str(brute.id) if brute.id else "",
                            title=brute.title or "Titre non spécifié",
                            company_name=brute.company_name or "Entreprise non spécifiée",
                            location=brute.location or "Localisation non spécifiée",
                            match_score=final_score,
                            match_reasons=reasons,
                            salary_range=self._format_salary_range(enrichie),
                            skills_match=self._find_skill_matches(cv_skills, enrichie.extracted_skills or []),
                            sector_match=enrichie.extracted_sector in cv_sectors if enrichie.extracted_sector else False,
                            contract_type_match=True,  # À déterminer selon le contexte
                            location_match=True  # À déterminer selon le contexte
                        )
                        recommendations.append(job_recommendation)
            
            # Trier par score et limiter
            recommendations.sort(key=lambda x: x.match_score, reverse=True)
            recommendations = recommendations[:20]
            
            # Calculer les métriques
            total_recommendations = len(recommendations)
            average_match_score = float(np.mean([r.match_score for r in recommendations])) if recommendations else 0.0

            return RecommendationResponse(
                user_id=str(self._get_valid_uuid(user_id)),
                recommendations=recommendations,
                total_recommendations=total_recommendations,
                average_match_score=average_match_score,
                generated_at=datetime.now()
            )
            
        except Exception as e:
            logger.error(f"Error matching CV with jobs: {e}")
            raise
    
    def _calculate_match_score(
        self, 
        user_profile: UserProfile, 
        brute: OffreEmploiBrute, 
        enrichie: OffreEmploiEnrichie
    ) -> tuple[float, List[str]]:
        """
        Calcule un score de matching entre un profil utilisateur et une offre.
        
        Args:
            user_profile: Profil de l'utilisateur
            brute: Offre d'emploi brute
            enrichie: Offre d'emploi enrichie
            
        Returns:
            Score de matching et raisons
        """
        score = 0.0
        reasons = []
        
        # Matching des compétences (40% du score)
        user_skills = list(user_profile.skills) if isinstance(user_profile.skills, (list, tuple)) else (user_profile.skills.split(",") if user_profile.skills else [])
        job_skills = list(enrichie.extracted_skills) if isinstance(enrichie.extracted_skills, (list, tuple)) else (enrichie.extracted_skills.split(",") if enrichie.extracted_skills else [])
        if user_skills and job_skills:
            skill_matches = self._find_skill_matches(user_skills, job_skills)
            skill_score = len(skill_matches) / max(len(user_skills), len(job_skills))
            score += skill_score * 0.4
            if skill_matches:
                reasons.append(f"Compétences en commun: {', '.join(skill_matches[:3])}")
        
        # Matching du secteur (20% du score)
        if user_profile.skills is not None and enrichie.extracted_sector is not None:
            if enrichie.extracted_sector.lower() in [skill.lower() for skill in user_profile.skills]:
                score += 0.2
                reasons.append(f"Secteur d'intérêt: {enrichie.extracted_sector}")
        
        # Matching du type de contrat (15% du score)
        if user_profile.preferred_contract_type is not None and enrichie.extracted_contract_type is not None:
            if enrichie.extracted_contract_type in user_profile.preferred_contract_type:
                score += 0.15
                reasons.append(f"Type de contrat préféré: {enrichie.extracted_contract_type}")
        
        # Matching du salaire (15% du score)
        if getattr(user_profile, "preferred_salary_min", None) is not None and getattr(enrichie, "extracted_salary_max", None) is not None:
            try:
                salary_max = float(getattr(enrichie, "extracted_salary_max"))
                salary_min = float(getattr(user_profile, "preferred_salary_min"))
                if salary_max >= salary_min:
                    score += 0.15
                    reasons.append("Salaire compatible")
            except (TypeError, ValueError):
                pass
        
        # Matching de l'expérience (10% du score)
        if user_profile.experience_years is not None and enrichie.extracted_experience_years is not None:
            exp_diff = abs(float(user_profile.experience_years) - float(enrichie.extracted_experience_years))
            if exp_diff <= 1:
                score += 0.1
                reasons.append("Niveau d'expérience compatible")
        
        return min(score, 1.0), reasons
    
    def _find_skill_matches(self, user_skills: List[str], job_skills: List[str]) -> List[str]:
        """Trouve les compétences en commun entre le profil et l'offre."""
        if not user_skills or not job_skills:
            return []
        
        matches = []
        user_skills_lower = [skill.lower().strip() for skill in user_skills]
        job_skills_lower = [skill.lower().strip() for skill in job_skills]
        
        for i, user_skill in enumerate(user_skills_lower):
            for j, job_skill in enumerate(job_skills_lower):
                if user_skill in job_skill or job_skill in user_skill:
                    matches.append(user_skills[i])
                    break
        
        return matches[:5]  # Limiter à 5 compétences
    
    def _format_salary_range(self, enrichie: OffreEmploiEnrichie) -> Optional[str]:
        """Formate la fourchette salariale."""
        if enrichie.extracted_salary_min and enrichie.extracted_salary_max:
            try:
                return f"{float(enrichie.extracted_salary_min):,.0f} - {float(enrichie.extracted_salary_max):,.0f} {enrichie.extracted_salary_currency or 'XOF'}"
            except (TypeError, ValueError):
                return None
        return None
    
    def _is_location_match(self, user_location: Optional[str], job_location: Optional[str]) -> bool:
        """Vérifie si les localisations correspondent."""
        if not user_location or not job_location:
            return True  # Pas de contrainte de localisation
        
        user_loc = user_location.lower().strip()
        job_loc = job_location.lower().strip()
        
        return user_loc in job_loc or job_loc in user_loc
    
    def _extract_cv_info(self, cv_text: str) -> tuple[List[str], int, List[str]]:
        """Extrait les informations clés du CV."""
        # TODO: Implémenter l'extraction NLP du CV
        # Pour l'instant, retourner des valeurs par défaut
        return [], 0, []
    
    def _calculate_skill_match(self, cv_skills: List[str], job_skills: List[str]) -> float:
        """Calcule le score de matching des compétences."""
        if not cv_skills or not job_skills:
            return 0.0
        
        matches = len(set(cv_skills) & set(job_skills))
        return matches / max(len(cv_skills), len(job_skills))
    
    def _calculate_experience_match(self, cv_experience: int, job_experience: Optional[int]) -> float:
        """Calcule le score de matching de l'expérience."""
        if not job_experience:
            return 0.5  # Score neutre
        
        if cv_experience >= job_experience:
            return 1.0
        else:
            return cv_experience / job_experience

    def _get_valid_uuid(self, user_id) -> uuid.UUID:
        """Assure que user_id est un objet UUID valide."""
        if user_id is None:
            return uuid.uuid4()
        if isinstance(user_id, uuid.UUID):
            return user_id
        try:
            return uuid.UUID(str(user_id))
        except Exception:
            return uuid.uuid4()