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
PRIMARY   = colors.HexColor("#0D9488")   # Turquoise / Sahel Teal
ACCENT    = colors.HexColor("#0EA5E9")   # Cyan / Turquoise Accent
LIGHT_BG  = colors.HexColor("#F1F5F9")  # Fond gris clair
TEXT_DARK = colors.HexColor("#1E293B")   # Texte principal Slate
TEXT_GREY = colors.HexColor("#475569")   # Texte secondaire Slate
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
    avatar_url: Optional[str] = None
    interests: Optional[List[str]] = field(default_factory=list)


@dataclass
class GeneratedDocument:
    """Résultat de la génération."""
    content_text: str
    file_path: str
    file_name: str
    document_type: str
    docx_file_path: Optional[str] = None
    docx_file_name: Optional[str] = None


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
        
        # PDF
        file_path = self._build_letter_pdf(
            content=content,
            profile=profile,
            title=f"Lettre de motivation – {job_title} chez {company_name}",
            doc_type="cover_letter",
        )
        file_name = os.path.basename(file_path)
        
        # Word (.docx)
        docx_file_path = self._build_letter_docx(
            content=content,
            profile=profile,
            title=f"Lettre de motivation – {job_title} chez {company_name}",
            doc_type="cover_letter",
        )
        docx_file_name = os.path.basename(docx_file_path)
        
        return GeneratedDocument(
            content_text=content,
            file_path=file_path,
            file_name=file_name,
            document_type="cover_letter",
            docx_file_path=docx_file_path,
            docx_file_name=docx_file_name
        )

    async def generate_cv(
        self,
        profile: UserProfileData,
        target_job: str = "",
    ) -> GeneratedDocument:
        """Génère un CV PDF et Word structuré à partir du profil réel."""
        summary = await self._llm_cv_summary(profile, target_job)
        profile.bio = summary  # on injecte l'accroche IA
        
        # PDF
        file_path = self._build_cv_pdf(profile, target_job)
        file_name = os.path.basename(file_path)
        
        # Word (.docx)
        docx_file_path = self._build_cv_docx(profile, target_job)
        docx_file_name = os.path.basename(docx_file_path)
        
        return GeneratedDocument(
            content_text=summary,
            file_path=file_path,
            file_name=file_name,
            document_type="cv",
            docx_file_path=docx_file_path,
            docx_file_name=docx_file_name
        )

    async def generate_other_letter(
        self,
        profile: UserProfileData,
        letter_type: str,
        context: Dict[str, str],
    ) -> GeneratedDocument:
        """Génère une lettre administrative (démission, relance, stage, recommandation)."""
        content = await self._llm_other_letter(profile, letter_type, context)
        
        # PDF
        file_path = self._build_letter_pdf(
            content=content,
            profile=profile,
            title=self._letter_type_label(letter_type),
            doc_type=letter_type,
        )
        file_name = os.path.basename(file_path)
        
        # Word (.docx)
        docx_file_path = self._build_letter_docx(
            content=content,
            profile=profile,
            title=self._letter_type_label(letter_type),
            doc_type=letter_type,
        )
        docx_file_name = os.path.basename(docx_file_path)
        
        return GeneratedDocument(
            content_text=content,
            file_path=file_path,
            file_name=file_name,
            document_type=letter_type,
            docx_file_path=docx_file_path,
            docx_file_name=docx_file_name
        )

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

        # ── En-tête candidat & destinataire ───────────────
        header_left = [
            Paragraph(f"<b>{profile.first_name} {profile.last_name}</b>", styles["body_normal"]),
            Paragraph(f"Tél : {profile.phone}", styles["body_normal"]) if profile.phone else "",
            Paragraph(f"Email : {profile.email}", styles["body_normal"]) if profile.email else "",
            Paragraph(f"Adresse : {profile.location}", styles["body_normal"]) if profile.location else "",
        ]

        recipient_name = "Responsable du Recrutement"
        company_lbl = ""
        if "chez" in title:
            parts = title.split("chez")
            company_lbl = parts[-1].strip()

        header_right = [
            Paragraph(f"Dakar, le {datetime.now().strftime('%d %B %Y')}", styles["date"]),
            Spacer(1, 15),
            Paragraph(f"<b>À l'attention du</b><br/><b>{recipient_name}</b>", styles["body_normal"]),
        ]
        if company_lbl:
            header_right.append(Paragraph(f"<i>{company_lbl}</i>", styles["body_normal"]))

        header_table = Table([[header_left, header_right]], colWidths=[10 * cm, 6 * cm])
        header_table.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING", (0,0), (-1,-1), 0),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 1.2 * cm))

        # ── Titre lettre / Objet ──────────────────────────
        story.append(Paragraph(f"<b>Objet : {title}</b>", styles["letter_object"]))
        story.append(Spacer(1, 0.8 * cm))

        # ── Corps de la lettre ────────────────────────────
        for para in content.split("\n"):
            para = para.strip()
            if para:
                story.append(Paragraph(para, styles["body_justify"]))
                story.append(Spacer(1, 0.3 * cm))

        story.append(Spacer(1, 1.2 * cm))
        
        # Signature
        sig_data = [
            ["", Paragraph("<b>Le Candidat,</b>", styles["body_normal"])],
            ["", Paragraph(f"<b>{profile.first_name} {profile.last_name}</b>", styles["body_normal"])]
        ]
        sig_table = Table(sig_data, colWidths=[10 * cm, 6 * cm])
        sig_table.setStyle(TableStyle([
            ("ALIGN", (1,0), (1,-1), "LEFT"),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ]))
        story.append(sig_table)

        doc.build(story)
        logger.info(f"PDF lettre générée : {file_path}")
        return file_path

    def _build_letter_docx(
        self,
        content: str,
        profile: UserProfileData,
        title: str,
        doc_type: str,
    ) -> str:
        import docx
        from docx.shared import Inches, Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml import OxmlElement, parse_xml
        from docx.oxml.ns import qn, nsdecls

        file_name = f"{doc_type}_{uuid.uuid4().hex[:8]}.docx"
        file_path = os.path.join(OUTPUT_DIR, file_name)

        doc = docx.Document()

        # Marges à 1 pouce (2.5 cm)
        margin = Inches(1)
        for section in doc.sections:
            section.top_margin = margin
            section.bottom_margin = margin
            section.left_margin = margin
            section.right_margin = margin

        # Couleurs
        primary_color = RGBColor(13, 148, 136)     # #0D9488
        text_dark = RGBColor(30, 41, 59)          # #1E293B
        text_grey = RGBColor(71, 85, 105)         # #475569

        # Police de base
        style = doc.styles['Normal']
        font = style.font
        font.name = 'Arial'
        font.size = Pt(10.5)
        font.color.rgb = text_dark

        # En-tête expéditeur & destinataire
        table = doc.add_table(rows=1, cols=2)
        tblPr = table._tbl.tblPr
        tblBorders = OxmlElement('w:tblBorders')
        for border_name in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
            b = OxmlElement(f'w:{border_name}')
            b.set(qn('w:val'), 'none')
            tblBorders.append(b)
        tblPr.append(tblBorders)

        col_widths = [Inches(3.8), Inches(2.7)]
        for row in table.rows:
            row.cells[0].width = col_widths[0]
            row.cells[1].width = col_widths[1]

        left_cell = table.rows[0].cells[0]
        right_cell = table.rows[0].cells[1]

        # Gauche : Expéditeur
        p_left = left_cell.paragraphs[0]
        p_left.paragraph_format.line_spacing = 1.15
        run_name = p_left.add_run(f"{profile.first_name} {profile.last_name}\n")
        run_name.bold = True
        run_name.font.size = Pt(11)
        run_name.font.color.rgb = primary_color
        
        contacts = []
        if profile.phone: contacts.append(f"Tél : {profile.phone}")
        if profile.email: contacts.append(f"Email : {profile.email}")
        if profile.location: contacts.append(f"Adresse : {profile.location}")
        
        run_contacts = p_left.add_run("\n".join(contacts))
        run_contacts.font.size = Pt(9.5)
        run_contacts.font.color.rgb = text_dark

        # Droite : Date et Destinataire
        p_right = right_cell.paragraphs[0]
        p_right.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p_right.paragraph_format.line_spacing = 1.15
        run_date = p_right.add_run(f"Dakar, le {datetime.now().strftime('%d %B %Y')}\n\n")
        run_date.font.size = Pt(9.5)
        run_date.font.color.rgb = text_grey
        
        recipient_name = "Responsable du Recrutement"
        company_lbl = ""
        if "chez" in title:
            parts = title.split("chez")
            company_lbl = parts[-1].strip()
            
        run_to = p_right.add_run("À l'attention du\n")
        run_to.bold = True
        run_to.font.size = Pt(9.5)
        run_to.font.color.rgb = text_dark
        
        run_rec = p_right.add_run(f"{recipient_name}\n")
        run_rec.bold = True
        run_rec.font.size = Pt(9.5)
        run_rec.font.color.rgb = text_dark
        
        if company_lbl:
            run_comp = p_right.add_run(company_lbl)
            run_comp.italic = True
            run_comp.font.size = Pt(9.5)
            run_comp.font.color.rgb = text_dark

        # Espace après le tableau d'en-tête
        p_space = doc.add_paragraph()
        p_space.paragraph_format.space_before = Pt(12)

        # Objet
        p_obj = doc.add_paragraph()
        p_obj.paragraph_format.space_after = Pt(18)
        run_obj = p_obj.add_run(f"Objet : {title}")
        run_obj.bold = True
        run_obj.font.size = Pt(11)
        run_obj.font.color.rgb = primary_color

        # Corps
        for para in content.split("\n"):
            para = para.strip()
            if para:
                p_body = doc.add_paragraph()
                p_body.paragraph_format.space_after = Pt(8)
                p_body.paragraph_format.line_spacing = 1.15
                p_body.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                run_body = p_body.add_run(para)
                run_body.font.size = Pt(10.5)

        # Signature
        p_sig = doc.add_paragraph()
        p_sig.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p_sig.paragraph_format.space_before = Pt(24)
        run_sig_lbl = p_sig.add_run("Le Candidat,\n\n")
        run_sig_lbl.bold = True
        run_sig_lbl.font.size = Pt(10.5)
        run_sig_lbl.font.color.rgb = text_dark
        
        run_sig = p_sig.add_run(f"{profile.first_name} {profile.last_name}")
        run_sig.bold = True
        run_sig.font.size = Pt(10.5)
        run_sig.font.color.rgb = primary_color

        doc.save(file_path)
        logger.info(f"DOCX lettre générée : {file_path}")
        return file_path

    def _build_cv_docx(
        self,
        profile: UserProfileData,
        target_job: str = "",
    ) -> str:
        import docx
        from docx.shared import Inches, Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml import OxmlElement, parse_xml
        from docx.oxml.ns import qn, nsdecls

        file_name = f"cv_{uuid.uuid4().hex[:8]}.docx"
        file_path = os.path.join(OUTPUT_DIR, file_name)

        doc = docx.Document()

        # Marges étroites à 0.5 pouce
        margin = Inches(0.5)
        for section in doc.sections:
            section.top_margin = margin
            section.bottom_margin = margin
            section.left_margin = margin
            section.right_margin = margin

        # Couleurs
        teal_color = RGBColor(13, 148, 136)      # #0D9488
        text_dark = RGBColor(30, 41, 59)         # #1E293B
        text_grey = RGBColor(71, 85, 105)        # #475569
        line_grey = "CBD5E1"

        # Style de base
        normal_style = doc.styles['Normal']
        normal_style.font.name = 'Arial'
        normal_style.font.size = Pt(9.5)
        normal_style.font.color.rgb = text_dark

        # Helpers XML internes
        def set_cell_shading(cell, color_hex):
            shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>')
            cell._tc.get_or_add_tcPr().append(shd)

        def set_cell_left_border(cell, color_hex="CBD5E1", size="12"):
            tcPr = cell._tc.get_or_add_tcPr()
            tcBorders = OxmlElement('w:tcBorders')
            left = OxmlElement('w:left')
            left.set(qn('w:val'), 'single')
            left.set(qn('w:sz'), str(size))
            left.set(qn('w:space'), '0')
            left.set(qn('w:color'), color_hex)
            tcBorders.append(left)
            for side in ('top', 'bottom', 'right'):
                b = OxmlElement(f'w:{side}')
                b.set(qn('w:val'), 'none')
                tcBorders.append(b)
            tcPr.append(tcBorders)

        def remove_table_borders(table):
            tblPr = table._tbl.tblPr
            tblBorders = OxmlElement('w:tblBorders')
            for border_name in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
                b = OxmlElement(f'w:{border_name}')
                b.set(qn('w:val'), 'none')
                tblBorders.append(b)
            tblPr.append(tblBorders)

        # ── Tableau Principal à 2 colonnes ────────────────
        outer_table = doc.add_table(rows=1, cols=2)
        remove_table_borders(outer_table)
        
        col_widths = [Inches(2.3), Inches(4.9)]
        for row in outer_table.rows:
            row.cells[0].width = col_widths[0]
            row.cells[1].width = col_widths[1]

        left_cell = outer_table.rows[0].cells[0]
        right_cell = outer_table.rows[0].cells[1]
        
        set_cell_shading(left_cell, "F1F5F9")
        set_cell_shading(right_cell, "FFFFFF")

        # ── Colonne Gauche (Sidebar) ──────────────────────
        # Monogramme / Initiales
        initials = ""
        if profile.first_name: initials += profile.first_name[0]
        if profile.last_name: initials += profile.last_name[0]
        if not initials: initials = "CV"
        
        p_mono = left_cell.paragraphs[0]
        p_mono.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_mono.paragraph_format.space_before = Pt(12)
        p_mono.paragraph_format.space_after = Pt(12)
        
        run_mono = p_mono.add_run(f" {initials.upper()} ")
        run_mono.bold = True
        run_mono.font.size = Pt(22)
        run_mono.font.color.rgb = RGBColor(255, 255, 255)
        
        shd_mono = parse_xml(f'<w:shd {nsdecls("w")} w:fill="0D9488"/>')
        run_mono._r.get_or_add_rPr().append(shd_mono)

        # Coordonnées
        def add_left_contact(label, text):
            p = left_cell.add_paragraph()
            p.paragraph_format.space_after = Pt(3)
            p.paragraph_format.line_spacing = 1.15
            run_lbl = p.add_run(f"{label} ")
            run_lbl.bold = True
            run_lbl.font.color.rgb = teal_color
            p.add_run(text)

        if profile.location: add_left_contact("📍", profile.location)
        if profile.phone: add_left_contact("📞", profile.phone)
        if profile.email: add_left_contact("✉️", profile.email)
        
        if profile.linkedin: add_left_contact("🔗", f"LinkedIn: {profile.linkedin}")
        if profile.github: add_left_contact("🔗", f"GitHub: {profile.github}")
        if profile.portfolio: add_left_contact("🔗", f"Portfolio: {profile.portfolio}")

        # Séparateur
        p_sep = left_cell.add_paragraph()
        p_sep.paragraph_format.space_before = Pt(8)
        p_sep.paragraph_format.space_after = Pt(8)
        p_sep.add_run("—" * 28).font.color.rgb = text_grey

        # Profil / Bio
        if profile.bio:
            p_bio_lbl = left_cell.add_paragraph()
            p_bio_lbl.paragraph_format.space_after = Pt(4)
            run_lbl = p_bio_lbl.add_run("PROFIL")
            run_lbl.bold = True
            run_lbl.font.color.rgb = teal_color
            run_lbl.font.size = Pt(10)
            
            p_bio = left_cell.add_paragraph()
            p_bio.paragraph_format.space_after = Pt(8)
            p_bio.paragraph_format.line_spacing = 1.15
            p_bio.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            run_bio = p_bio.add_run(profile.bio)
            run_bio.font.size = Pt(8.5)
            
            # Séparateur
            p_sep2 = left_cell.add_paragraph()
            p_sep2.paragraph_format.space_after = Pt(8)
            p_sep2.add_run("—" * 28).font.color.rgb = text_grey

        # Compétences
        if profile.skills:
            p_skills_lbl = left_cell.add_paragraph()
            p_skills_lbl.paragraph_format.space_after = Pt(4)
            run_lbl = p_skills_lbl.add_run("COMPÉTENCES")
            run_lbl.bold = True
            run_lbl.font.color.rgb = teal_color
            run_lbl.font.size = Pt(10)
            
            for skill in profile.skills:
                p_skill = left_cell.add_paragraph()
                p_skill.paragraph_format.space_after = Pt(2)
                p_skill.paragraph_format.left_indent = Inches(0.1)
                run_bullet = p_skill.add_run("• ")
                run_bullet.bold = True
                run_bullet.font.color.rgb = teal_color
                p_skill.add_run(skill).font.size = Pt(8.5)

        # ── Colonne Droite (Main Area) ────────────────────
        # Nom et titre
        p_name = right_cell.paragraphs[0]
        p_name.paragraph_format.space_before = Pt(8)
        p_name.paragraph_format.space_after = Pt(2)
        run_name = p_name.add_run(f"{profile.first_name} {profile.last_name}".upper())
        run_name.bold = True
        run_name.font.size = Pt(22)
        run_name.font.color.rgb = teal_color
        
        p_title = right_cell.add_paragraph()
        p_title.paragraph_format.space_after = Pt(16)
        title_txt = target_job or profile.current_title or "Professionnel"
        run_title = p_title.add_run(title_txt.upper())
        run_title.bold = True
        run_title.font.size = Pt(11)
        run_title.font.color.rgb = text_grey

        # Timeline en tableau imbriqué
        timeline_table = right_cell.add_table(rows=0, cols=2)
        remove_table_borders(timeline_table)
        
        time_widths = [Inches(0.3), Inches(4.3)]

        def add_timeline_section(title_text):
            row = timeline_table.add_row()
            row.cells[0].width = time_widths[0]
            row.cells[1].width = time_widths[1]
            
            set_cell_left_border(row.cells[1], color_hex=line_grey)
            
            p0 = row.cells[0].paragraphs[0]
            p0.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run0 = p0.add_run("■")
            run0.bold = True
            run0.font.color.rgb = teal_color
            run0.font.size = Pt(12)
            
            p1 = row.cells[1].paragraphs[0]
            p1.paragraph_format.space_after = Pt(6)
            run1 = p1.add_run(title_text.upper())
            run1.bold = True
            run1.font.color.rgb = teal_color
            run1.font.size = Pt(10.5)

        def add_timeline_item(bold_title, italic_meta, description_text=""):
            row = timeline_table.add_row()
            row.cells[0].width = time_widths[0]
            row.cells[1].width = time_widths[1]
            
            set_cell_left_border(row.cells[1], color_hex=line_grey)
            
            p0 = row.cells[0].paragraphs[0]
            p0.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run0 = p0.add_run("▪")
            run0.font.color.rgb = text_dark
            run0.font.size = Pt(10)
            
            p1 = row.cells[1].paragraphs[0]
            p1.paragraph_format.space_after = Pt(2)
            run_title = p1.add_run(bold_title)
            run_title.bold = True
            run_title.font.size = Pt(9.5)
            
            p_meta = row.cells[1].add_paragraph()
            p_meta.paragraph_format.space_after = Pt(4)
            run_meta = p_meta.add_run(italic_meta)
            run_meta.italic = True
            run_meta.font.size = Pt(8.5)
            run_meta.font.color.rgb = text_grey
            
            if description_text:
                p_desc = row.cells[1].add_paragraph()
                p_desc.paragraph_format.space_after = Pt(6)
                p_desc.paragraph_format.line_spacing = 1.15
                p_desc.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                run_desc = p_desc.add_run(description_text)
                run_desc.font.size = Pt(8.5)

        # 1. Experiences
        if profile.experiences:
            add_timeline_section("Parcours Professionnel")
            exps = profile.experiences if isinstance(profile.experiences, list) else [profile.experiences]
            for exp in exps:
                if isinstance(exp, dict):
                    job_title = exp.get("title", exp.get("poste", ""))
                    company   = exp.get("company", exp.get("entreprise", ""))
                    period    = exp.get("period", exp.get("periode", ""))
                    desc      = exp.get("description", exp.get("desc", ""))
                    add_timeline_item(job_title, f"{company} | {period}", desc)
                else:
                    add_timeline_item(str(exp), "")

        # 2. Formation
        if profile.education_level:
            add_timeline_section("Formation")
            edu_lines = [line.strip() for line in profile.education_level.split("\n") if line.strip()]
            for line in edu_lines:
                add_timeline_item(line, "")

        # 3. Langues
        if profile.languages:
            add_timeline_section("Langues")
            row = timeline_table.add_row()
            row.cells[0].width = time_widths[0]
            row.cells[1].width = time_widths[1]
            set_cell_left_border(row.cells[1], color_hex=line_grey)
            
            p_lang = row.cells[1].paragraphs[0]
            p_lang.paragraph_format.space_after = Pt(6)
            
            langs = profile.languages if isinstance(profile.languages, list) else list(profile.languages.items())
            lang_strings = []
            for lang in langs:
                label = f"{lang[0]} ({lang[1]})" if isinstance(lang, (list, tuple)) else str(lang)
                lang_strings.append(label)
            p_lang.add_run(", ".join(lang_strings)).font.size = Pt(9)

        # 4. Centres d'intérêt
        interests_list = []
        if hasattr(profile, 'interests') and profile.interests:
            if isinstance(profile.interests, list):
                interests_list.extend(profile.interests)
            else:
                interests_list.append(str(profile.interests))
                
        title_text = "Centres d'Intérêt"
        if not interests_list and hasattr(profile, 'certifications') and profile.certifications:
            title_text = "Certifications"
            certs = profile.certifications if isinstance(profile.certifications, list) else [profile.certifications]
            for cert in certs:
                label = cert.get("name", str(cert)) if isinstance(cert, dict) else str(cert)
                interests_list.append(label)

        if interests_list:
            add_timeline_section(title_text)
            row = timeline_table.add_row()
            row.cells[0].width = time_widths[0]
            row.cells[1].width = time_widths[1]
            set_cell_left_border(row.cells[1], color_hex=line_grey)
            
            p_int = row.cells[1].paragraphs[0]
            p_int.paragraph_format.space_after = Pt(6)
            p_int.add_run(", ".join(interests_list)).font.size = Pt(9)

        doc.save(file_path)
        logger.info(f"DOCX CV généré : {file_path}")
        return file_path

    # ────────────────────────────────────────────────────────
    # GÉNÉRATION PDF — CV
    # ────────────────────────────────────────────────────────

    def _draw_sidebar_bg(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#F1F5F9"))
        canvas.rect(0, 0, 6.5 * cm, A4[1], fill=True, stroke=False)
        canvas.restoreState()

    def _get_avatar_flowable(self, avatar_url: Optional[str], initials: str) -> Table:
        width = 4.0 * cm
        height = 4.0 * cm
        teal_color = colors.HexColor("#0D9488")
        
        if avatar_url:
            import requests
            import tempfile
            try:
                r = requests.get(avatar_url, timeout=5)
                if r.status_code == 200:
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                    temp_file.write(r.content)
                    temp_file.close()
                    
                    from reportlab.platypus import Image
                    img = Image(temp_file.name, width=width, height=height)
                    img_table = Table([[img]], colWidths=[width], rowHeights=[height])
                    img_table.setStyle(TableStyle([
                        ("BOX", (0,0), (-1,-1), 3, teal_color),
                        ("LEFTPADDING", (0,0), (-1,-1), 0),
                        ("RIGHTPADDING", (0,0), (-1,-1), 0),
                        ("TOPPADDING", (0,0), (-1,-1), 0),
                        ("BOTTOMPADDING", (0,0), (-1,-1), 0),
                        ("ALIGN", (0,0), (-1,-1), "CENTER"),
                        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                    ]))
                    return img_table
            except Exception as e:
                logger.warning(f"Impossible de charger l'avatar: {e}")
                
        # Monogramme
        style = ParagraphStyle(
            "monogram_style",
            fontName="Helvetica-Bold",
            fontSize=24,
            textColor=colors.white,
            alignment=TA_CENTER,
            leading=28
        )
        p = Paragraph(initials.upper(), style)
        monogram = Table([[p]], colWidths=[width], rowHeights=[height])
        monogram.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), teal_color),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("ALIGN", (0,0), (-1,-1), "CENTER"),
            ("BOX", (0,0), (-1,-1), 3, teal_color),
            ("TOPPADDING", (0,0), (-1,-1), 0.5*cm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0.5*cm),
        ]))
        return monogram

    def _create_progress_bar(self, level: float) -> Table:
        width_total = 3.5 * cm
        width_fill = width_total * level
        width_empty = width_total * (1 - level)
        
        data = [["", ""]]
        col_widths = [width_fill]
        if width_empty > 0:
            col_widths.append(width_empty)
        else:
            col_widths = [width_total]
            
        bar = Table(data, colWidths=col_widths, rowHeights=[0.15 * cm])
        styles = [
            ("BACKGROUND", (0,0), (0,0), colors.HexColor("#0D9488")),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING", (0,0), (-1,-1), 0),
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ]
        if width_empty > 0:
            styles.append(("BACKGROUND", (1,0), (1,0), colors.HexColor("#E2E8F0")))
        bar.setStyle(TableStyle(styles))
        return bar

    def _build_timeline_table(self, profile: UserProfileData, target_job: str, styles) -> Table:
        data = []
        
        # 1. PARCOURS PROFESSIONNEL
        if profile.experiences:
            data.append([
                Paragraph('<b><font size="14" color="#0D9488">&#9632;</font></b>', styles["timeline_marker"]),
                Paragraph('<b>PARCOURS PROFESSIONNEL</b>', styles["cv_section_right"])
            ])
            
            exps = profile.experiences if isinstance(profile.experiences, list) else [profile.experiences]
            for exp in exps:
                if isinstance(exp, dict):
                    job_title = exp.get("title", exp.get("poste", ""))
                    company   = exp.get("company", exp.get("entreprise", ""))
                    period    = exp.get("period", exp.get("periode", ""))
                    desc      = exp.get("description", exp.get("desc", ""))
                    
                    content = []
                    content.append(Paragraph(f"<b>{job_title}</b>", styles["cv_exp_title"]))
                    content.append(Paragraph(f"<font color='#475569'><b>{company}</b> | {period}</font>", styles["cv_exp_meta"]))
                    if desc:
                        content.append(Paragraph(desc, styles["cv_exp_desc"]))
                    content.append(Spacer(1, 4))
                    
                    data.append([
                        Paragraph('<font size="10" color="#1E293B">&#9642;</font>', styles["timeline_submarker"]),
                        content
                    ])
                else:
                    data.append([
                        Paragraph('<font size="10" color="#1E293B">&#9642;</font>', styles["timeline_submarker"]),
                        Paragraph(str(exp), styles["body_normal"])
                    ])
            data.append([Spacer(1, 6), Spacer(1, 6)])

        # 2. FORMATION
        if profile.education_level:
            data.append([
                Paragraph('<b><font size="14" color="#0D9488">&#9632;</font></b>', styles["timeline_marker"]),
                Paragraph('<b>FORMATION</b>', styles["cv_section_right"])
            ])
            
            edu_lines = [line.strip() for line in profile.education_level.split("\n") if line.strip()]
            for line in edu_lines:
                data.append([
                    Paragraph('<font size="10" color="#1E293B">&#9642;</font>', styles["timeline_submarker"]),
                    Paragraph(f"<b>{line}</b>", styles["body_normal"])
                ])
            data.append([Spacer(1, 6), Spacer(1, 6)])

        # 3. LANGUES
        if profile.languages:
            data.append([
                Paragraph('<b><font size="14" color="#0D9488">&#9632;</font></b>', styles["timeline_marker"]),
                Paragraph('<b>LANGUES</b>', styles["cv_section_right"])
            ])
            
            langs = profile.languages if isinstance(profile.languages, list) else list(profile.languages.items())
            lang_flowables = []
            for lang in langs:
                label = ""
                level_str = ""
                level_val = 0.5
                
                if isinstance(lang, (list, tuple)):
                    label = lang[0]
                    level_str = lang[1]
                else:
                    label = str(lang)
                    level_str = "Moyen"
                
                lower_lvl = level_str.lower()
                if "maternelle" in lower_lvl or "bilingue" in lower_lvl or "parfait" in lower_lvl:
                    level_val = 1.0
                elif "courant" in lower_lvl or "avance" in lower_lvl or "avancé" in lower_lvl:
                    level_val = 0.8
                elif "intermediaire" in lower_lvl or "intermédiaire" in lower_lvl or "moyen" in lower_lvl:
                    level_val = 0.6
                else:
                    level_val = 0.3
                    
                lang_bar = self._create_progress_bar(level_val)
                
                lang_item_data = [
                    [Paragraph(f"<b>{label}</b>", styles["body_normal"]), ""],
                    [Paragraph(f"<font size='7.5' color='#64748B'>{level_str}</font>", styles["body_normal"]), ""],
                    [lang_bar, ""]
                ]
                lang_item_table = Table(lang_item_data, colWidths=[5.5 * cm, 0.3 * cm], rowHeights=[12, 10, 10])
                lang_item_table.setStyle(TableStyle([
                    ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 0),
                    ("TOPPADDING", (0,0), (-1,-1), 0),
                    ("LEFTPADDING", (0,0), (-1,-1), 0),
                    ("RIGHTPADDING", (0,0), (-1,-1), 0),
                ]))
                lang_flowables.append(lang_item_table)
            
            lang_pairs_data = []
            for i in range(0, len(lang_flowables), 2):
                pair = [lang_flowables[i]]
                if i + 1 < len(lang_flowables):
                    pair.append(lang_flowables[i+1])
                else:
                    pair.append("")
                lang_pairs_data.append(pair)
                
            lang_table = Table(lang_pairs_data, colWidths=[6.0 * cm, 6.0 * cm])
            lang_table.setStyle(TableStyle([
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("BOTTOMPADDING", (0,0), (-1,-1), 4),
                ("TOPPADDING", (0,0), (-1,-1), 4),
                ("LEFTPADDING", (0,0), (-1,-1), 0),
                ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ]))
            
            data.append([
                Spacer(1, 1),
                lang_table
            ])
            data.append([Spacer(1, 6), Spacer(1, 6)])

        # 4. CENTRES D'INTÉRÊT / CERTIFICATIONS
        interests_list = []
        if hasattr(profile, 'interests') and profile.interests:
            if isinstance(profile.interests, list):
                interests_list.extend(profile.interests)
            else:
                interests_list.append(str(profile.interests))
        
        title_text = "CENTRES D'INTÉRÊT"
        if not interests_list and hasattr(profile, 'certifications') and profile.certifications:
            title_text = "CERTIFICATIONS"
            certs = profile.certifications if isinstance(profile.certifications, list) else [profile.certifications]
            for cert in certs:
                label = cert.get("name", str(cert)) if isinstance(cert, dict) else str(cert)
                interests_list.append(label)
        
        if interests_list:
            data.append([
                Paragraph('<b><font size="14" color="#0D9488">&#9632;</font></b>', styles["timeline_marker"]),
                Paragraph(f'<b>{title_text}</b>', styles["cv_section_right"])
            ])
            
            interest_paragraphs = []
            for item in interests_list:
                interest_paragraphs.append(Paragraph(f"<font color='#0D9488'>•</font> {item}", styles["body_normal"]))
            
            interest_rows = []
            for i in range(0, len(interest_paragraphs), 2):
                row = [interest_paragraphs[i]]
                if i + 1 < len(interest_paragraphs):
                    row.append(interest_paragraphs[i+1])
                else:
                    row.append("")
                interest_rows.append(row)
                
            interest_table = Table(interest_rows, colWidths=[6.0 * cm, 6.0 * cm])
            interest_table.setStyle(TableStyle([
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("BOTTOMPADDING", (0,0), (-1,-1), 2),
                ("TOPPADDING", (0,0), (-1,-1), 2),
                ("LEFTPADDING", (0,0), (-1,-1), 0),
                ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ]))
            
            data.append([
                Spacer(1, 1),
                interest_table
            ])

        t = Table(data, colWidths=[0.8 * cm, 12.0 * cm])
        t.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("BOTTOMPADDING", (0,0), (-1,-1), 1),
            ("TOPPADDING", (0,0), (-1,-1), 1),
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ("LINEAFTER", (0,0), (0,-1), 1.5, colors.HexColor("#CBD5E1")),
        ]))
        return t

    def _cv_left_column(self, profile: UserProfileData, styles) -> List:
        items = []
        
        # Initiales monogramme
        initials = ""
        if profile.first_name: initials += profile.first_name[0]
        if profile.last_name: initials += profile.last_name[0]
        if not initials: initials = "CV"
        
        avatar_flow = self._get_avatar_flowable(profile.avatar_url, initials)
        items.append(avatar_flow)
        items.append(Spacer(1, 12))
        
        if profile.location:
            items.append(Paragraph(f"<font size='10' color='#0D9488'>&#128205;</font> &nbsp;{profile.location}", styles["cv_small"]))
            items.append(Spacer(1, 4))
        if profile.phone:
            items.append(Paragraph(f"<font size='10' color='#0D9488'>&#128222;</font> &nbsp;{profile.phone}", styles["cv_small"]))
            items.append(Spacer(1, 4))
        if profile.email:
            items.append(Paragraph(f"<font size='10' color='#0D9488'>&#9993;</font> &nbsp;{profile.email}", styles["cv_small"]))
            items.append(Spacer(1, 4))
            
        links = []
        if profile.linkedin:
            links.append(f"<font size='10' color='#0D9488'>&#128279;</font> &nbsp;LinkedIn: {profile.linkedin}")
        if profile.github:
            links.append(f"<font size='10' color='#0D9488'>&#128279;</font> &nbsp;GitHub: {profile.github}")
        if profile.portfolio:
            links.append(f"<font size='10' color='#0D9488'>&#128279;</font> &nbsp;Portfolio: {profile.portfolio}")
            
        for link in links:
            items.append(Paragraph(link, styles["cv_small"]))
            items.append(Spacer(1, 4))
            
        items.append(Spacer(1, 8))
        items.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E1"), spaceAfter=10))
        
        if profile.bio:
            items.append(Paragraph("PROFIL", styles["cv_section_left"]))
            items.append(Spacer(1, 4))
            items.append(Paragraph(profile.bio, styles["body_justify"]))
            items.append(Spacer(1, 8))
            items.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E1"), spaceAfter=10))
            
        if profile.skills:
            items.append(Paragraph("COMPÉTENCES", styles["cv_section_left"]))
            items.append(Spacer(1, 4))
            for skill in profile.skills:
                items.append(Paragraph(f"<font color='#0D9488'>•</font> {skill}", styles["cv_small"]))
                items.append(Spacer(1, 3))
                
        return items

    def _build_cv_pdf(self, profile: UserProfileData, target_job: str = "") -> str:
        file_name = f"cv_{uuid.uuid4().hex[:8]}.pdf"
        file_path = os.path.join(OUTPUT_DIR, file_name)

        doc = SimpleDocTemplate(
            file_path, pagesize=A4,
            leftMargin=0, rightMargin=0,
            topMargin=0, bottomMargin=0,
        )

        styles = self._get_styles()
        story = []

        left_col_flowables = self._cv_left_column(profile, styles)
        right_col_flowables = []
        
        full_name = f"{profile.first_name} {profile.last_name}"
        title_txt = target_job or profile.current_title or "Professionnel"
        
        right_col_flowables.append(Spacer(1, 10))
        right_col_flowables.append(Paragraph(full_name.upper(), styles["cv_name"]))
        right_col_flowables.append(Paragraph(title_txt.upper(), styles["cv_subtitle"]))
        right_col_flowables.append(Spacer(1, 15))
        
        timeline = self._build_timeline_table(profile, target_job, styles)
        right_col_flowables.append(timeline)

        body_table = Table(
            [[left_col_flowables, right_col_flowables]],
            colWidths=[6.5 * cm, 14.5 * cm],
            rowHeights=None,
        )
        body_table.setStyle(TableStyle([
            ("VALIGN",      (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (0,0), 0.5 * cm),
            ("RIGHTPADDING",(0,0), (0,0), 0.5 * cm),
            ("LEFTPADDING", (1,0), (1,0), 0.7 * cm),
            ("RIGHTPADDING",(1,0), (1,0), 1.0 * cm),
            ("TOPPADDING",  (0,0), (-1,-1), 1.0 * cm),
            ("BOTTOMPADDING",(0,0), (-1,-1), 1.0 * cm),
        ]))
        story.append(body_table)

        doc.build(
            story,
            onFirstPage=self._draw_sidebar_bg,
            onLaterPages=self._draw_sidebar_bg
        )
        logger.info(f"PDF CV généré : {file_path}")
        return file_path

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
            "cv_name":        ParagraphStyle("cv_name",        fontSize=24, textColor=PRIMARY, fontName="Helvetica-Bold", leading=28),
            "cv_title":       ParagraphStyle("cv_title",       fontSize=12, textColor=ACCENT, fontName="Helvetica-Bold"),
            "cv_subtitle":    ParagraphStyle("cv_subtitle",    fontSize=11, textColor=TEXT_GREY),

            # CV — sections
            "cv_section_left":  ParagraphStyle("cv_section_left",  fontSize=10,  textColor=PRIMARY, fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=4),
            "cv_section_right": ParagraphStyle("cv_section_right", fontSize=11, textColor=PRIMARY, fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=4),

            # CV — contenu
            "cv_small":       ParagraphStyle("cv_small",       fontSize=8.5,  textColor=TEXT_DARK, leading=11),
            "cv_exp_title":   ParagraphStyle("cv_exp_title",   fontSize=9.5, textColor=TEXT_DARK, fontName="Helvetica-Bold"),
            "cv_exp_meta":    ParagraphStyle("cv_exp_meta",    fontSize=8.5,  textColor=TEXT_GREY, fontName="Helvetica-Oblique"),
            "cv_exp_desc":    ParagraphStyle("cv_exp_desc",    fontSize=8.5,  textColor=TEXT_DARK, leading=11, alignment=TA_JUSTIFY),
            
            "timeline_marker": ParagraphStyle("timeline_marker", fontSize=14, textColor=PRIMARY, alignment=TA_CENTER, leading=14),
            "timeline_submarker": ParagraphStyle("timeline_submarker", fontSize=10, textColor=TEXT_DARK, alignment=TA_CENTER, leading=10),
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
