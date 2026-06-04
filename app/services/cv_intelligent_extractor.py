# cv_intelligent_extractor.py
try:
    import spacy
    from spacy.matcher import PhraseMatcher
    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False
    
from dataclasses import dataclass
import re
from typing import List, Dict, Any, Optional
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
    urls: List[str] = None
    visual_metadata: Optional[str] = None
    links_metadata: Optional[str] = None
    
    def __post_init__(self):
        if self.urls is None:
            self.urls = []

class CVIntelligentExtractor:
    """Remplacement direct de votre _extract_cv_info_robust() avec prise en charge avancée des liens."""
    
    def __init__(self, model_name: str = "fr_dep_news_trf"):
        self.nlp = None
        self.model_name = model_name
        self._matcher = None
        self._skill_patterns = None
    
    def _load_model(self):
        """Lazy loading - n'initialise spaCy qu'au premier appel."""
        if not SPACY_AVAILABLE:
            logger.warning("spaCy n'est pas installé. Utilisation du mode dégradé (Regex uniquement).")
            return

        if self.nlp is None:
            try:
                self.nlp = spacy.load(self.model_name)
            except Exception:
                try:
                    self.nlp = spacy.load("fr_core_news_lg")
                except Exception:
                    logger.error(f"Impossible de charger le modèle spaCy {self.model_name}. Mode dégradé activé.")
                    return
                
            # Charger le référentiel de compétences de votre DB
            self._load_skills_from_referentiel()
    
    def _load_skills_from_referentiel(self):
        """Charge les compétences depuis votre table CompetenceReferentiel."""
        if not self.nlp:
            return
            
        skills = ["Python", "JavaScript", "React", "Docker", "Kubernetes", "AWS", "Azure"]  # simulation
        self._skill_patterns = [self.nlp(skill.lower()) for skill in skills]
        self._matcher = PhraseMatcher(self.nlp.vocab, attr="LOWER")
        self._matcher.add("TECH_SKILLS", self._skill_patterns)
    
    def extract(self, text: str) -> CVExtractedData:
        """Méthode principale."""
        if not text or len(text.strip()) < 50:
            return CVExtractedData(0, [], [], [], text, "")
        
        self._load_model()
        
        # Extraction des URLs universelle
        urls = self._extract_urls(text)
        
        if self.nlp:
            doc = self.nlp(text)
            experience = self._extract_experience(doc)
            skills = self._extract_skills(doc)
            sectors = self._extract_sectors(doc)
            titles = self._extract_job_titles(doc)
            clean_text = self._clean_for_embedding(doc)
        else:
            experience = self._extract_experience_fallback(text)
            skills = self._extract_skills_fallback(text)
            sectors = self._extract_sectors_fallback(text)
            titles = self._extract_job_titles_fallback(text)
            clean_text = text[:1000]

        return CVExtractedData(
            experience_years=experience,
            skills=skills,
            sectors=sectors,
            job_titles=titles,
            raw_text=text,
            clean_text=clean_text,
            urls=urls
        )

    def _extract_urls(self, text: str) -> List[str]:
        """Extrait les liens LinkedIn, GitHub, Portfolios."""
        # Regex basique pour les URLs
        url_pattern = r'https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)'
        urls = re.findall(url_pattern, text)
        return list(set(urls))
        
    def _extract_experience(self, doc) -> int:
        """Extraction robuste de l'expérience via spaCy."""
        max_years = 0
        
        # 1. Entités DATE de spaCy
        for ent in doc.ents:
            if ent.label_ == "DATE":
                years = self._parse_date_to_years(ent.text)
                if years:
                    max_years = max(max_years, years)
        
        # 2. Patterns regex comme fallback
        if max_years == 0:
            max_years = self._extract_experience_fallback(doc.text)
        
        return min(max_years, 50)

    def _extract_experience_fallback(self, text: str) -> int:
        """Extraction expérience via regex."""
        max_years = 0
        patterns = [
            r"(\d+)\s*ans?\s+d'\s*exp[ée]rience",
            r"(\d+)\s*ans?",
            r"(\d+)\s*years?",
        ]
        text_lower = text.lower()
        for pattern in patterns:
            matches = re.findall(pattern, text_lower)
            if matches:
                try:
                    max_years = max(max_years, max(map(int, matches)))
                except ValueError:
                    continue
        return max_years
    
    def _parse_date_to_years(self, text: str) -> int:
        # Simple stub pour le parsing de date
        return 0
    
    def _extract_skills(self, doc) -> List[str]:
        """Extraction sémantique des compétences via spaCy."""
        skills = set()
        if self._matcher:
            matches = self._matcher(doc)
            skills.update({doc[start:end].text for _, start, end in matches})
        
        # Ajouter les entités TECH détectées
        for ent in doc.ents:
            if ent.label_ in ["PRODUCT", "TECH"]:
                skills.add(ent.text)
        
        if not skills:
            return self._extract_skills_fallback(doc.text)
            
        return list(skills)[:20]

    def _extract_skills_fallback(self, text: str) -> List[str]:
        """Extraction compétences via mots-clés simples."""
        common_skills = ["python", "javascript", "react", "docker", "php", "java", "sql", "aws", "azure"]
        text_lower = text.lower()
        found = [s for s in common_skills if s in text_lower]
        return found
    
    def _extract_sectors(self, doc) -> List[str]:
        """Extraction des secteurs via spaCy/Text matching."""
        return self._extract_sectors_fallback(doc.text)

    def _extract_sectors_fallback(self, text: str) -> List[str]:
        """Extraction secteurs via regex."""
        sectors_ref = ["informatique", "finance", "santé", "éducation", "transport", "logistique", "commerce"]
        text_lower = text.lower()
        return [s for s in sectors_ref if s in text_lower][:3]
    
    def _extract_job_titles(self, doc, section_text: str = None) -> List[str]:
        """Extraction des titres de poste."""
        return self._extract_job_titles_fallback(section_text or doc.text)

    def _extract_job_titles_fallback(self, text: str) -> List[str]:
        """Extraction titres via regex."""
        title_patterns = [r"\b(d[eé]veloppeur|ing[eé]nieur|chef|manager|consultant|technicien|comptable)\b"]
        titles = []
        for pattern in title_patterns:
            matches = re.findall(pattern, text, re.I)
            titles.extend(matches)
        return list(set(titles))[:5]
    
    def _clean_for_embedding(self, doc) -> str:
        """Prépare le texte pour l'embedding via spaCy."""
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