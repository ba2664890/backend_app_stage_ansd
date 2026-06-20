"""
Service de génération intelligente de documents (CV, Lettres, etc.)
- Gemini pour la rédaction anti-hallucination (données utilisateur uniquement)
- ReportLab pour l'export PDF professionnel
"""
import os
import io
import json
import logging
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    Table, TableStyle, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from .llm_client import LLMClient

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# PALETTE DE COULEURS
# ────────────────────────────────────────────────────────────
PRIMARY   = colors.HexColor("#1A3A5C")   # Bleu marine profond
ACCENT    = colors.HexColor("#E8A838")   # Or Sahel
LIGHT_BG  = colors.HexColor("#F5F7FA")  # Fond gris très clair
TEXT_DARK = colors.HexColor("#1E293B")   # Texte principal
TEXT_GREY = colors.HexColor("#64748B")   # Texte secondaire
WHITE     = colors.white

OUTPUT_DIR = "app/static/generated"
os.makedirs(OUTPUT_DIR, exist_ok=True)


@dataclass
class UserProfileData:
    """Données du profil candidat pour la génération."""
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    current_title: str = ""
    experience_years: int = 0
    education_level: str = ""
    skills: List[str] = field(default_factory=list)
    bio: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    languages: Optional[Any] = None
    experiences: Optional[Any] = None
    certifications: Optional[Any] = None


@dataclass
class GeneratedDocument:
    """Résultat de la génération."""
    content_text: str
    file_path: str
    file_name: str
    document_type: str


class DocumentGenerationService:
    """Génère des documents professionnels PDF via Gemini + ReportLab."""

    def __init__(self):
        self.llm = LLMClient()

    # ────────────────────────────────────────────────────────
    # API PUBLIQUE
    # ────────────────────────────────────────────────────────

    async def generate_cover_letter(
        self,
        profile: UserProfileData,
        job_title: str,
        company_name: str,
        job_description: str = "",
        tone: str = "professionnel",
    ) -> GeneratedDocument:
        """Génère une lettre de motivation sur mesure, strictement ancrée dans le profil."""
        content = await self._llm_cover_letter(profile, job_title, company_name, job_description, tone)
        file_path = self._build_letter_pdf(
            content=content,
            profile=profile,
            title=f"Lettre de motivation – {job_title} chez {company_name}",
            doc_type="cover_letter",
        )
        file_name = os.path.basename(file_path)
        return GeneratedDocument(content, file_path, file_name, "cover_letter")

    async def generate_cv(
        self,
        profile: UserProfileData,
        target_job: str = "",
    ) -> GeneratedDocument:
        """Génère un CV PDF structuré à partir du profil réel."""
        summary = await self._llm_cv_summary(profile, target_job)
        profile.bio = summary  # on injecte l'accroche IA
        file_path = self._build_cv_pdf(profile, target_job)
        file_name = os.path.basename(file_path)
        return GeneratedDocument(summary, file_path, file_name, "cv")

    async def generate_other_letter(
        self,
        profile: UserProfileData,
        letter_type: str,
        context: Dict[str, str],
    ) -> GeneratedDocument:
        """Génère une lettre administrative (démission, relance, stage, recommandation)."""
        content = await self._llm_other_letter(profile, letter_type, context)
        file_path = self._build_letter_pdf(
            content=content,
            profile=profile,
            title=self._letter_type_label(letter_type),
            doc_type=letter_type,
        )
        file_name = os.path.basename(file_path)
        return GeneratedDocument(content, file_path, file_name, letter_type)

    # ────────────────────────────────────────────────────────
    # GÉNÉRATION LLM (Gemini) — ANTI-HALLUCINATION
    # ────────────────────────────────────────────────────────

    async def _llm_cover_letter(
        self,
        profile: UserProfileData,
        job_title: str,
        company_name: str,
        job_description: str,
        tone: str,
    ) -> str:
        skills_str = ", ".join(profile.skills[:12]) if profile.skills else "Non précisé"
        exp_list = json.dumps(profile.experiences, ensure_ascii=False)[:800] if profile.experiences else "Non précisé"

        system = (
            "Tu es un expert RH sénégalais rédigeant des lettres de motivation professionnelles. "
            "RÈGLE ABSOLUE : n'invente AUCUNE information. Utilise UNIQUEMENT les données fournies. "
            "Si une donnée est manquante, construis une phrase générale sans mentir. "
            f"Ton : {tone}. Langue : français. Format : texte brut, sans markdown."
        )

        user = f"""Rédige une lettre de motivation complète (3 paragraphes) pour :
CANDIDAT :
- Nom : {profile.first_name} {profile.last_name}
- Poste actuel : {profile.current_title or 'Non précisé'}
- Expérience : {profile.experience_years} ans
- Compétences : {skills_str}
- Expériences détaillées : {exp_list}
- Bio : {profile.bio or 'Non fournie'}

OFFRE :
- Poste visé : {job_title}
- Entreprise : {company_name}
- Description (extrait) : {job_description[:500] if job_description else 'Non fournie'}

Structure :
Paragraphe 1 – Accroche + intérêt pour le poste (basé sur les données réelles)
Paragraphe 2 – Compétences et expériences pertinentes (UNIQUEMENT celles listées ci-dessus)
Paragraphe 3 – Motivation pour l'entreprise + formule de politesse

Commence directement par "Madame, Monsieur,"
"""
        return await self.llm.generate_response(system, user, temperature=0.4)

    async def _llm_cv_summary(self, profile: UserProfileData, target_job: str) -> str:
        skills_str = ", ".join(profile.skills[:10]) if profile.skills else "Non précisé"
        system = (
            "Tu es un expert en rédaction de CV. "
            "RÈGLE ABSOLUE : 2-3 phrases max, basées UNIQUEMENT sur les données fournies. "
            "Pas de markdown. Pas d'inventions."
        )
        user = f"""Rédige une accroche de profil percutante pour ce CV :
- Prénom/Nom : {profile.first_name} {profile.last_name}
- Titre : {profile.current_title or 'Professionnel en recherche'}
- Expérience : {profile.experience_years} ans
- Compétences clés : {skills_str}
- Poste visé : {target_job or 'Non précisé'}
- Bio existante : {profile.bio or 'Aucune'}
"""
        return await self.llm.generate_response(system, user, temperature=0.3)

    async def _llm_other_letter(
        self,
        profile: UserProfileData,
        letter_type: str,
        context: Dict[str, str],
    ) -> str:
        templates = {
            "resignation":      "une lettre de démission professionnelle et respectueuse",
            "internship_request": "une demande de stage formelle",
            "follow_up":        "une lettre de relance après candidature",
            "recommendation_request": "une demande de lettre de recommandation",
        }
        desc = templates.get(letter_type, "une lettre professionnelle")
        ctx_str = "\n".join(f"- {k}: {v}" for k, v in context.items())

        system = (
            f"Tu es expert en rédaction administrative. Rédige {desc}. "
            "RÈGLE : données fournies uniquement, pas d'invention. Texte brut, sans markdown."
        )
        user = f"""Candidat : {profile.first_name} {profile.last_name}
Titre actuel : {profile.current_title or 'Non précisé'}
Contexte supplémentaire :
{ctx_str}

Rédige la lettre complète avec formules de politesse adaptées.
"""
        return await self.llm.generate_response(system, user, temperature=0.3)

    # ────────────────────────────────────────────────────────
    # GÉNÉRATION PDF — LETTRE
    # ────────────────────────────────────────────────────────

    def _build_letter_pdf(
        self,
        content: str,
        profile: UserProfileData,
        title: str,
        doc_type: str,
    ) -> str:
        file_name = f"{doc_type}_{uuid.uuid4().hex[:8]}.pdf"
        file_path = os.path.join(OUTPUT_DIR, file_name)

        doc = SimpleDocTemplate(
            file_path, pagesize=A4,
            leftMargin=2.5*cm, rightMargin=2.5*cm,
            topMargin=2.5*cm, bottomMargin=2.5*cm,
        )

        styles = self._get_styles()
        story = []

        # ── En-tête candidat ──────────────────────────────
        header_data = [[
            Paragraph(f"<b>{profile.first_name} {profile.last_name}</b>", styles["header_name"]),
            Paragraph(
                f"{profile.email}<br/>{profile.phone}<br/>{profile.location}",
                styles["header_contact"]
            ),
        ]]
        header_table = Table(header_data, colWidths=[10*cm, 6*cm])
        header_table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), PRIMARY),
            ("TEXTCOLOR",  (0,0), (-1,-1), WHITE),
            ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING",(0,0), (-1,-1), 14),
            ("RIGHTPADDING",(0,0),(-1,-1), 10),
            ("TOPPADDING", (0,0), (-1,-1), 16),
            ("BOTTOMPADDING",(0,0),(-1,-1), 16),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 1.2*cm))

        # ── Date + destinataire ───────────────────────────
        story.append(Paragraph(f"Dakar, le {datetime.now().strftime('%d %B %Y')}", styles["date"]))
        story.append(Spacer(1, 0.8*cm))

        # ── Titre lettre ──────────────────────────────────
        story.append(Paragraph(f"<b>Objet : {title}</b>", styles["letter_object"]))
        story.append(HRFlowable(width="100%", thickness=1.5, color=ACCENT, spaceAfter=12))

        # ── Corps de la lettre ────────────────────────────
        for para in content.split("\n"):
            para = para.strip()
            if para:
                story.append(Paragraph(para, styles["body_justify"]))
                story.append(Spacer(1, 0.3*cm))

        story.append(Spacer(1, 1*cm))
        story.append(Paragraph(f"<b>{profile.first_name} {profile.last_name}</b>", styles["signature"]))

        doc.build(story)
        logger.info(f"PDF lettre généré : {file_path}")
        return file_path

    # ────────────────────────────────────────────────────────
    # GÉNÉRATION PDF — CV
    # ────────────────────────────────────────────────────────

    def _build_cv_pdf(self, profile: UserProfileData, target_job: str = "") -> str:
        file_name = f"cv_{uuid.uuid4().hex[:8]}.pdf"
        file_path = os.path.join(OUTPUT_DIR, file_name)

        doc = SimpleDocTemplate(
            file_path, pagesize=A4,
            leftMargin=0, rightMargin=0,
            topMargin=0, bottomMargin=0.6*cm,
        )

        styles = self._get_styles()
        story = []

        # ── Bandeau supérieur ─────────────────────────────
        full_name = f"{profile.first_name} {profile.last_name}"
        title_txt = target_job or profile.current_title or "Professionnel"

        banner = Table(
            [[Paragraph(f"<b>{full_name}</b>", styles["cv_name"]),
              Paragraph(title_txt, styles["cv_subtitle"])]],
            colWidths=[A4[0]*0.65, A4[0]*0.35]
        )
        banner.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), PRIMARY),
            ("TEXTCOLOR",  (0,0), (-1,-1), WHITE),
            ("LEFTPADDING",(0,0), (-1,-1), 1.5*cm),
            ("TOPPADDING", (0,0), (-1,-1), 0.7*cm),
            ("BOTTOMPADDING",(0,0),(-1,-1), 0.7*cm),
        ]))
        story.append(banner)

        # ── Corps en deux colonnes ────────────────────────
        left_col = self._cv_left_column(profile, styles)
        right_col = self._cv_right_column(profile, styles)

        body_table = Table(
            [[left_col, right_col]],
            colWidths=[6.2*cm, 12.8*cm],
            rowHeights=None,
        )
        body_table.setStyle(TableStyle([
            ("VALIGN",      (0,0), (-1,-1), "TOP"),
            ("BACKGROUND",  (0,0), (0,-1), LIGHT_BG),
            ("BACKGROUND",  (1,0), (1,-1), WHITE),
            ("LEFTPADDING", (0,0), (0,-1), 0.6*cm),
            ("RIGHTPADDING",(0,0), (0,-1), 0.5*cm),
            ("LEFTPADDING", (1,0), (1,-1), 0.7*cm),
            ("RIGHTPADDING",(1,0), (1,-1), 0.7*cm),
            ("TOPPADDING",  (0,0), (-1,-1), 0.5*cm),
        ]))
        story.append(body_table)

        doc.build(story)
        logger.info(f"PDF CV généré : {file_path}")
        return file_path

    def _cv_left_column(self, profile: UserProfileData, styles) -> List:
        """Colonne gauche : contact, compétences, langues."""
        items = []

        # Contact
        items.append(Paragraph("CONTACT", styles["cv_section_left"]))
        items.append(HRFlowable(width="100%", thickness=1, color=ACCENT, spaceAfter=4))
        for line in filter(None, [profile.email, profile.phone, profile.location,
                                   profile.linkedin, profile.github, profile.portfolio]):
            items.append(Paragraph(line, styles["cv_small"]))
            items.append(Spacer(1, 1))
        items.append(Spacer(1, 0.25*cm))

        # Compétences
        if profile.skills:
            items.append(Paragraph("COMPÉTENCES", styles["cv_section_left"]))
            items.append(HRFlowable(width="100%", thickness=1, color=ACCENT, spaceAfter=4))
            for skill in profile.skills[:8]:
                items.append(Paragraph(f"• {skill}", styles["cv_small"]))
                items.append(Spacer(1, 1))
            items.append(Spacer(1, 0.25*cm))

        # Langues
        if profile.languages:
            items.append(Paragraph("LANGUES", styles["cv_section_left"]))
            items.append(HRFlowable(width="100%", thickness=1, color=ACCENT, spaceAfter=4))
            langs = profile.languages if isinstance(profile.languages, list) else list(profile.languages.items())
            for lang in langs[:2]:
                label = f"{lang[0]} – {lang[1]}" if isinstance(lang, (list, tuple)) else str(lang)
                items.append(Paragraph(f"• {label}", styles["cv_small"]))
                items.append(Spacer(1, 1))
            items.append(Spacer(1, 0.25*cm))

        # Certifications
        if profile.certifications:
            items.append(Paragraph("CERTIFICATIONS", styles["cv_section_left"]))
            items.append(HRFlowable(width="100%", thickness=1, color=ACCENT, spaceAfter=4))
            certs = profile.certifications if isinstance(profile.certifications, list) else [profile.certifications]
            for cert in certs[:2]:
                label = cert.get("name", str(cert)) if isinstance(cert, dict) else str(cert)
                items.append(Paragraph(f"• {label}", styles["cv_small"]))
                items.append(Spacer(1, 1))

        return items

    def _cv_right_column(self, profile: UserProfileData, styles) -> List:
        """Colonne droite : accroche, expériences, formation."""
        items = []

        # Accroche
        if profile.bio:
            items.append(Paragraph("PROFIL", styles["cv_section_right"]))
            items.append(HRFlowable(width="100%", thickness=2, color=PRIMARY, spaceAfter=6))
            items.append(Paragraph(profile.bio, styles["body_justify"]))
            items.append(Spacer(1, 0.3*cm))

        # Expériences
        if profile.experiences:
            items.append(Paragraph("EXPÉRIENCES PROFESSIONNELLES", styles["cv_section_right"]))
            items.append(HRFlowable(width="100%", thickness=2, color=PRIMARY, spaceAfter=6))
            exps = profile.experiences if isinstance(profile.experiences, list) else [profile.experiences]
            for exp in exps[:3]:
                if isinstance(exp, dict):
                    job_title = exp.get("title", exp.get("poste", ""))
                    company   = exp.get("company", exp.get("entreprise", ""))
                    period    = exp.get("period", exp.get("periode", ""))
                    desc      = exp.get("description", exp.get("desc", ""))
                    items.append(Paragraph(f"<b>{job_title}</b>", styles["cv_exp_title"]))
                    items.append(Paragraph(f"{company} | {period}", styles["cv_exp_meta"]))
                    items.append(Paragraph(desc[:150] if desc else "", styles["cv_exp_desc"]))
                    items.append(Spacer(1, 0.15*cm))
                else:
                    items.append(Paragraph(f"• {str(exp)}", styles["body_normal"]))
            items.append(Spacer(1, 0.2*cm))

        # Formation
        if profile.education_level:
            items.append(Paragraph("FORMATION", styles["cv_section_right"]))
            items.append(HRFlowable(width="100%", thickness=2, color=PRIMARY, spaceAfter=6))
            items.append(Paragraph(profile.education_level, styles["body_normal"]))

        return items

    # ────────────────────────────────────────────────────────
    # STYLES REPORTLAB
    # ────────────────────────────────────────────────────────

    def _get_styles(self) -> Dict[str, ParagraphStyle]:
        base = getSampleStyleSheet()
        return {
            # Entêtes lettre
            "header_name":    ParagraphStyle("header_name",    fontSize=16, textColor=WHITE, fontName="Helvetica-Bold"),
            "header_contact": ParagraphStyle("header_contact", fontSize=8,  textColor=WHITE, fontName="Helvetica", leading=12),
            "date":           ParagraphStyle("date",           fontSize=10, textColor=TEXT_GREY, alignment=TA_RIGHT),
            "letter_object":  ParagraphStyle("letter_object",  fontSize=11, textColor=PRIMARY, spaceAfter=4),
            "signature":      ParagraphStyle("signature",      fontSize=10, textColor=TEXT_DARK, fontName="Helvetica-Bold", alignment=TA_RIGHT),

            # Corps texte
            "body_normal":    ParagraphStyle("body_normal",    fontSize=9.5, textColor=TEXT_DARK, leading=13, spaceAfter=4),
            "body_justify":   ParagraphStyle("body_justify",   fontSize=9.5, textColor=TEXT_DARK, leading=13, alignment=TA_JUSTIFY),

            # CV — bandeau
            "cv_name":        ParagraphStyle("cv_name",        fontSize=20, textColor=WHITE, fontName="Helvetica-Bold", leading=24),
            "cv_title":       ParagraphStyle("cv_title",       fontSize=12, textColor=ACCENT, fontName="Helvetica-Bold"),
            "cv_subtitle":    ParagraphStyle("cv_subtitle",    fontSize=11, textColor=ACCENT),

            # CV — sections
            "cv_section_left":  ParagraphStyle("cv_section_left",  fontSize=9,  textColor=PRIMARY, fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=2),
            "cv_section_right": ParagraphStyle("cv_section_right", fontSize=10.5, textColor=PRIMARY, fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=2),

            # CV — contenu
            "cv_small":       ParagraphStyle("cv_small",       fontSize=8,  textColor=TEXT_DARK, leading=10),
            "cv_exp_title":   ParagraphStyle("cv_exp_title",   fontSize=9.5, textColor=TEXT_DARK, fontName="Helvetica-Bold"),
            "cv_exp_meta":    ParagraphStyle("cv_exp_meta",    fontSize=8,  textColor=TEXT_GREY, fontName="Helvetica-Oblique"),
            "cv_exp_desc":    ParagraphStyle("cv_exp_desc",    fontSize=8.5,  textColor=TEXT_DARK, leading=11, alignment=TA_JUSTIFY),
        }

    @staticmethod
    def _letter_type_label(letter_type: str) -> str:
        labels = {
            "resignation":           "Lettre de démission",
            "internship_request":    "Demande de stage",
            "follow_up":             "Lettre de relance – Candidature",
            "recommendation_request":"Demande de lettre de recommandation",
        }
        return labels.get(letter_type, "Lettre professionnelle")
