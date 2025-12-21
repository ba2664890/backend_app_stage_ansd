"""
Service d'export de données (PDF, Excel, CSV).
"""

from typing import List, Dict, Any, Optional
from io import BytesIO
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# PDF
try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    logger.warning("ReportLab non installé. Export PDF désactivé. Installez avec: pip install reportlab")

# Excel
try:
    import pandas as pd
    EXCEL_AVAILABLE = True
except ImportError:
    EXCEL_AVAILABLE = False
    logger.warning("Pandas non installé. Export Excel désactivé. Installez avec: pip install pandas openpyxl")


class ExportService:
    """Service pour exporter des données."""
    
    def export_to_excel(
        self,
        data: List[Dict[str, Any]],
        filename: str = "export.xlsx",
        sheet_name: str = "Data"
    ) -> Optional[bytes]:
        """
        Exporte des données vers Excel.
        
        Args:
            data: Liste de dictionnaires à exporter
            filename: Nom du fichier
            sheet_name: Nom de la feuille
            
        Returns:
            bytes: Contenu du fichier Excel
        """
        if not EXCEL_AVAILABLE:
            logger.error("Pandas non disponible pour export Excel")
            return None
        
        try:
            df = pd.DataFrame(data)
            
            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            buffer.seek(0)
            logger.info(f"Export Excel créé: {len(data)} lignes")
            return buffer.getvalue()
            
        except Exception as e:
            logger.error(f"Erreur export Excel: {e}")
            return None
    
    def export_to_csv(
        self,
        data: List[Dict[str, Any]],
        filename: str = "export.csv"
    ) -> Optional[bytes]:
        """Exporte des données vers CSV."""
        if not EXCEL_AVAILABLE:
            logger.error("Pandas non disponible pour export CSV")
            return None
        
        try:
            df = pd.DataFrame(data)
            
            buffer = BytesIO()
            df.to_csv(buffer, index=False, encoding='utf-8')
            buffer.seek(0)
            
            logger.info(f"Export CSV créé: {len(data)} lignes")
            return buffer.getvalue()
            
        except Exception as e:
            logger.error(f"Erreur export CSV: {e}")
            return None
    
    def generate_recruitment_report_pdf(
        self,
        company_name: str,
        stats: Dict[str, Any],
        applications: List[Dict[str, Any]]
    ) -> Optional[bytes]:
        """
        Génère un rapport de recrutement en PDF.
        
        Args:
            company_name: Nom de l'entreprise
            stats: Statistiques de recrutement
            applications: Liste des candidatures
        """
        if not PDF_AVAILABLE:
            logger.error("ReportLab non disponible pour export PDF")
            return None
        
        try:
            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4)
            story = []
            styles = getSampleStyleSheet()
            
            # Titre
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=24,
                textColor=colors.HexColor('#1a73e8'),
                spaceAfter=30
            )
            title = Paragraph(f"Rapport de Recrutement<br/>{company_name}", title_style)
            story.append(title)
            
            # Date
            date_text = Paragraph(
                f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}",
                styles['Normal']
            )
            story.append(date_text)
            story.append(Spacer(1, 0.3*inch))
            
            # Statistiques globales
            stats_title = Paragraph("📊 Statistiques Globales", styles['Heading2'])
            story.append(stats_title)
            story.append(Spacer(1, 0.2*inch))
            
            stats_data = [
                ['Métrique', 'Valeur'],
                ['Total candidatures', str(stats.get('total', 0))],
                ['Temps moyen de review', f"{stats.get('avg_time_to_review', 0):.1f}h"],
                ['Temps moyen d'embauche', f"{stats.get('avg_time_to_hire', 0):.1f} jours"],
                ['Taux de conversion', f"{stats.get('conversion_rate', 0):.1f}%"],
            ]
            
            stats_table = Table(stats_data, colWidths=[3*inch, 2*inch])
            stats_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a73e8')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            story.append(stats_table)
            story.append(Spacer(1, 0.5*inch))
            
            # Répartition par statut
            if stats.get('by_status'):
                status_title = Paragraph("📈 Répartition par Statut", styles['Heading2'])
                story.append(status_title)
                story.append(Spacer(1, 0.2*inch))
                
                status_data = [['Statut', 'Nombre']]
                for status, count in stats['by_status'].items():
                    status_data.append([status, str(count)])
                
                status_table = Table(status_data, colWidths=[3*inch, 2*inch])
                status_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34a853')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)
                ]))
                story.append(status_table)
                story.append(PageBreak())
            
            # Liste des candidatures récentes
            if applications:
                apps_title = Paragraph("📋 Candidatures Récentes", styles['Heading2'])
                story.append(apps_title)
                story.append(Spacer(1, 0.2*inch))
                
                apps_data = [['Candidat', 'Poste', 'Statut', 'Date']]
                for app in applications[:20]:  # Limiter à 20
                    apps_data.append([
                        app.get('candidate_name', 'N/A'),
                        app.get('job_title', 'N/A')[:30],
                        app.get('status', 'N/A'),
                        app.get('applied_at', 'N/A')
                    ])
                
                apps_table = Table(apps_data, colWidths=[1.5*inch, 2*inch, 1.2*inch, 1.3*inch])
                apps_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#fbbc04')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)
                ]))
                story.append(apps_table)
            
            # Générer le PDF
            doc.build(story)
            buffer.seek(0)
            
            logger.info(f"Rapport PDF généré pour {company_name}")
            return buffer.getvalue()
            
        except Exception as e:
            logger.error(f"Erreur génération PDF: {e}")
            return None
    
    def export_applications_to_excel(
        self,
        applications: List[Dict[str, Any]]
    ) -> Optional[bytes]:
        """Exporte les candidatures vers Excel."""
        formatted_data = []
        
        for app in applications:
            formatted_data.append({
                "ID": app.get('id', ''),
                "Candidat": app.get('candidate_name', ''),
                "Email": app.get('candidate_email', ''),
                "Poste": app.get('job_title', ''),
                "Entreprise": app.get('company_name', ''),
                "Statut": app.get('status', ''),
                "Note": app.get('rating', ''),
                "Date candidature": app.get('applied_at', ''),
                "Date review": app.get('reviewed_at', ''),
                "Date décision": app.get('decision_date', ''),
            })
        
        return self.export_to_excel(formatted_data, sheet_name="Candidatures")
