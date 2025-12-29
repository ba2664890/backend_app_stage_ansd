"""
Service pour l'analyse des compétences et GEPP (Gestion des Emplois et Parcours Professionnels).
"""

from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import UUID
import logging

from ..models.database_models import (
    CompanySkillNeed, CompetenceReferentiel, Company, OffreEmploiEnrichie, UserProfile
)
from ..models.api_models import CompanySkillNeedCreate

logger = logging.getLogger(__name__)


class SkillGapService:
    """Service pour analyser les écarts de compétences."""
    
    def add_skill_need(
        self,
        db: Session,
        company_id: UUID,
        skill_data: CompanySkillNeedCreate
    ) -> CompanySkillNeed:
        """Ajoute un besoin en compétence pour une entreprise."""
        # Vérifier si existe déjà
        existing = db.query(CompanySkillNeed).filter(
            CompanySkillNeed.company_id == company_id,
            CompanySkillNeed.competence_id == skill_data.competence_id
        ).first()
        
        if existing:
            # Mettre à jour la priorité
            existing.priority = skill_data.priority
            db.commit()
            db.refresh(existing)
            return existing
        
        # Créer nouveau besoin
        skill_need = CompanySkillNeed(
            company_id=company_id,
            competence_id=skill_data.competence_id,
            priority=skill_data.priority
        )
        db.add(skill_need)
        db.commit()
        db.refresh(skill_need)
        
        logger.info(f"Besoin en compétence ajouté: Company {company_id}, Priority {skill_data.priority}")
        return skill_need
    
    def get_company_skill_needs(
        self,
        db: Session,
        company_id: UUID
    ) -> List[CompanySkillNeed]:
        """Récupère tous les besoins en compétences d'une entreprise."""
        return db.query(CompanySkillNeed).filter(
            CompanySkillNeed.company_id == company_id
        ).order_by(CompanySkillNeed.priority.asc()).all()
    
    def analyze_skill_gaps(
        self,
        db: Session,
        company_id: UUID
    ) -> Dict:
        """
        Analyse les écarts entre besoins et disponibilité des compétences.
        
        Returns:
            Dict: Analyse avec compétences critiques, disponibilité, recommandations
        """
        # Récupérer les besoins de l'entreprise
        skill_needs = self.get_company_skill_needs(db, company_id)
        
        if not skill_needs:
            return {
                "critical_skills": [],
                "skill_availability": {},
                "recommendations": ["Définir les besoins en compétences de votre entreprise"]
            }
        
        # Analyser la disponibilité sur le marché
        skill_availability = {}
        critical_skills = []
        
        for need in skill_needs:
            competence = need.competence
            
            # Compter combien de candidats ont cette compétence
            candidates_with_skill = db.query(UserProfile).filter(
                UserProfile.skills.contains([competence.competence_name])
            ).count()
            
            # Compter combien d'offres demandent cette compétence
            jobs_requiring_skill = db.query(OffreEmploiEnrichie).filter(
                OffreEmploiEnrichie.extracted_skills.contains([competence.competence_name])
            ).count()
            
            availability_ratio = candidates_with_skill / max(jobs_requiring_skill, 1)
            
            skill_availability[competence.competence_name] = {
                "priority": need.priority,
                "candidates_available": candidates_with_skill,
                "jobs_requiring": jobs_requiring_skill,
                "availability_ratio": round(availability_ratio, 2),
                "status": "abundant" if availability_ratio > 1.5 else "balanced" if availability_ratio > 0.8 else "scarce"
            }
            
            if need.priority == 1 and availability_ratio < 0.8:
                critical_skills.append({
                    "skill": competence.competence_name,
                    "availability": availability_ratio
                })
        
        # Générer des recommandations
        recommendations = self._generate_recommendations(critical_skills, skill_availability)
        
        return {
            "critical_skills": critical_skills,
            "skill_availability": skill_availability,
            "recommendations": recommendations
        }

    def get_skill_gaps_list(self, db: Session, company_id: UUID) -> List[Dict]:
        """Retourne une liste d'écarts de compétences au format attendu par le frontend."""
        analysis = self.analyze_skill_gaps(db, company_id)
        availability = analysis.get("skill_availability", {})
        
        gaps = []
        for skill_name, data in availability.items():
            # Conversion status -> difficulty_level
            status = data.get("status", "balanced")
            diff_level = "hard" if status == "scarce" else "medium" if status == "balanced" else "easy"
            
            # Calcul du pourcentage de gap
            ratio = data.get("availability_ratio", 1.0)
            gap_pct = max(0, 100 * (1 - ratio)) if ratio < 1 else 0
            
            gaps.append({
                "skill": skill_name,
                "needed_count": data.get("jobs_requiring", 0),
                "gap_percentage": round(gap_pct, 1),
                "difficulty_level": diff_level
            })
            
        return sorted(gaps, key=lambda x: x["gap_percentage"], reverse=True)
    
    def _generate_recommendations(
        self,
        critical_skills: List[Dict],
        skill_availability: Dict
    ) -> List[str]:
        """Génère des recommandations basées sur l'analyse."""
        recommendations = []
        
        if critical_skills:
            recommendations.append(
                f"⚠️ {len(critical_skills)} compétence(s) critique(s) en pénurie détectée(s)"
            )
            recommendations.append(
                "Envisager des formations internes ou partenariats avec des écoles"
            )
        
        scarce_skills = [
            skill for skill, data in skill_availability.items()
            if data["status"] == "scarce"
        ]
        
        if scarce_skills:
            recommendations.append(
                f"Compétences rares: {', '.join(scarce_skills[:3])} - Augmenter l'attractivité des offres"
            )
        
        if not recommendations:
            recommendations.append("✅ Bonne disponibilité des compétences recherchées")
        
        return recommendations
    
    def suggest_training(
        self,
        db: Session,
        company_id: UUID
    ) -> List[Dict]:
        """
        Suggère des formations basées sur les écarts de compétences.
        
        Returns:
            List[Dict]: Suggestions de formation
        """
        analysis = self.analyze_skill_gaps(db, company_id)
        critical_skills = analysis["critical_skills"]
        
        training_suggestions = []
        
        for skill_data in critical_skills:
            skill = skill_data["skill"]
            training_suggestions.append({
                "skill": skill,
                "priority": "Haute",
                "training_type": "Formation interne ou externe",
                "estimated_duration": "2-4 semaines",
                "target_audience": "Équipes techniques",
                "providers": ["Écoles locales", "Plateformes en ligne", "Consultants"]
            })
        
        return training_suggestions
    
    def get_market_skill_trends(self, db: Session, limit: int = 20) -> List[Dict]:
        """
        Analyse les tendances des compétences sur le marché.
        
        Returns:
            List[Dict]: Top compétences demandées
        """
        # Compter les compétences dans les offres enrichies
        skill_counts = {}
        
        offers = db.query(OffreEmploiEnrichie).filter(
            OffreEmploiEnrichie.extracted_skills.isnot(None)
        ).all()
        
        for offer in offers:
            if offer.extracted_skills:
                for skill in offer.extracted_skills:
                    skill_counts[skill] = skill_counts.get(skill, 0) + 1
        
        # Trier par fréquence
        sorted_skills = sorted(skill_counts.items(), key=lambda x: x[1], reverse=True)[:limit]
        
        return [
            {
                "skill": skill,
                "demand_count": count,
                "trend": "rising" if count > 10 else "stable"
            }
            for skill, count in sorted_skills
        ]
