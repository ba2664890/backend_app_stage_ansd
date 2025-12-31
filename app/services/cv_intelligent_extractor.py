# cv_intelligent_extractor.py
import spacy
from spacy.matcher import PhraseMatcher
from dataclasses import dataclass
import re
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

@dataclass
class CVExtractedData:
    """Structure optimisée pour l'embedding."""
    experience_years: int
    skills: List[str]
    sectors: List[str]
    job_titles: List[str]
    raw_text: str
    clean_text: str  # Texte normalisé pour embedding

class CVIntelligentExtractor:
    """Remplacement direct de votre _extract_cv_info_robust()."""
    
    def __init__(self, model_name: str = "fr_dep_news_trf"):
        self.nlp = None
        self.model_name = model_name
        self._matcher = None
        self._skill_patterns = None
    
    def _load_model(self):
        """Lazy loading - n'initialise spaCy qu'au premier appel."""
        if self.nlp is None:
            try:
                self.nlp = spacy.load(self.model_name)
            except OSError:
                self.nlp = spacy.load("fr_core_news_lg")
                
            # Charger le référentiel de compétences de votre DB
            self._load_skills_from_referentiel()
    
    def _load_skills_from_referentiel(self):
        """Charge les compétences depuis votre table CompetenceReferentiel."""
        # À appeler une fois au démarrage avec votre session DB
        # Exemple: 
        # skills = db.query(CompetenceReferentiel.competence_name).all()
        skills = ["Python", "JavaScript", "React", "Docker", "Kubernetes"]  # simulation
        self._skill_patterns = [self.nlp(skill.lower()) for skill in skills]
        self._matcher = PhraseMatcher(self.nlp.vocab, attr="LOWER")
        self._matcher.add("TECH_SKILLS", self._skill_patterns)
    
    def extract(self, text: str) -> CVExtractedData:
        """Méthode principale - Remplace _extract_cv_info_robust()."""
        if not text or len(text.strip()) < 50:
            return CVExtractedData(0, [], [], [], text, "")
        
        self._load_model()
        doc = self.nlp(text)
        
        # Extraction parallèle des features
        experience = self._extract_experience(doc)
        skills = self._extract_skills(doc)
        sectors = self._extract_sectors(doc)
        titles = self._extract_job_titles(doc)
        clean_text = self._clean_for_embedding(doc)
        
        return CVExtractedData(
            experience_years=experience,
            skills=skills,
            sectors=sectors,
            job_titles=titles,
            raw_text=text,
            clean_text=clean_text
        )
    
    def _extract_experience(self, doc) -> int:
        """Extraction robuste de l'expérience."""
        max_years = 0
        
        # 1. Entités DATE de spaCy
        for ent in doc.ents:
            if ent.label_ == "DATE":
                years = self._parse_date_to_years(ent.text)
                if years:
                    max_years = max(max_years, years)
        
        # 2. Patterns regex comme fallback
        if max_years == 0:
            patterns = [
                r"(\d+)\s*ans?\s+d'\s*exp[ée]rience",
                r"(\d+)\s*ans?",
                r"(\d+)\s*years?",
            ]
            text_lower = doc.text.lower()
            for pattern in patterns:
                matches = re.findall(pattern, text_lower)
                if matches:
                    max_years = max(max_years, max(map(int, matches)))
        
        return min(max_years, 50)
    
    def _extract_skills(self, doc) -> List[str]:
        """Extraction sémantique des compétences."""
        matches = self._matcher(doc)
        skills = {doc[start:end].text for _, start, end in matches}
        
        # Ajouter les entités TECH détectées
        for ent in doc.ents:
            if ent.label_ in ["PRODUCT", "TECH"]:
                skills.add(ent.text)
        
        return list(skills)[:20]  # Top 20
    
    def _extract_sectors(self, doc) -> List[str]:
        """Extraction des secteurs."""
        # Utilisez votre référentiel de secteurs
        sectors_ref = ["informatique", "finance", "santé", "éducation"]
        text_lower = doc.text.lower()
        return [s for s in sectors_ref if s in text_lower][:3]
    
    def _extract_job_titles(self, doc, section_text: str = None) -> List[str]:
        """Extraction des titres de poste."""
        if section_text:
            doc_exp = self.nlp(section_text)
        else:
            doc_exp = doc
        
        # Patterns de titres
        title_patterns = [r"\b(d[eé]veloppeur|ing[eé]nieur|chef|manager|consultant)\b"]
        titles = []
        for pattern in title_patterns:
            matches = re.findall(pattern, doc_exp.text, re.I)
            titles.extend(matches)
        
        return list(set(titles))[:5]
    
    def _clean_for_embedding(self, doc) -> str:
        """Prépare le texte pour l'embedding."""
        # 1. Supprimer les stopwords
        tokens = [token.lemma_.lower() for token in doc 
                 if not token.is_stop and not token.is_punct and not token.is_space]
        
        # 2. Garder les phrases importantes
        important_sents = []
        for sent in doc.sents:
            if any(keyword in sent.text.lower() for keyword in 
                   ["expérience", "compétence", "projet", "réalisation"]):
                important_sents.append(sent.text)
        
        return " | ".join(important_sents + [" ".join(tokens[:200])])