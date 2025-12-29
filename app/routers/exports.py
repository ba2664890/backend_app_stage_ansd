"""
Routes API pour les exports (PDF, Excel).
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List

from ..database import get_db
from ..services.export_service import ExportService
from ..services.application_service import ApplicationService
from ..utils.auth import get_current_user
from ..utils.permissions import require_permission, Permission

router = APIRouter(prefix="/api/v1/export", tags=["export"])
export_service = ExportService()
application_service = ApplicationService()


@router.get("/applications/excel")
@require_permission(Permission.EXPORT_DATA)
async def export_applications_excel(
    company_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Exporte les candidatures d'une entreprise en Excel."""
    applications, _ = application_service.get_company_applications(db, company_id, skip=0, limit=1000)
    
    # Formater les données
    formatted_apps = [{
        "id": str(app.id),
        "candidate_name": f"{app.user.profile.first_name} {app.user.profile.last_name}" if app.user.profile else "N/A",
        "candidate_email": app.user.email,
        "job_title": app.job.offre_brute.title if app.job.offre_brute else "N/A",
        "company_name": app.company.name,
        "status": app.status,
        "rating": app.rating,
        "applied_at": app.applied_at.strftime("%Y-%m-%d %H:%M") if app.applied_at else "N/A",
        "reviewed_at": app.reviewed_at.strftime("%Y-%m-%d %H:%M") if app.reviewed_at else "",
        "decision_date": app.decision_date.strftime("%Y-%m-%d") if app.decision_date else "",
    } for app in applications]
    
    excel_data = export_service.export_applications_to_excel(formatted_apps)
    
    if not excel_data:
        raise HTTPException(status_code=500, detail="Erreur lors de l'export")
    
    return Response(
        content=excel_data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=candidatures_{company_id}.xlsx"}
    )


@router.get("/recruitment-report/pdf")
@require_permission(Permission.EXPORT_DATA)
async def export_recruitment_report_pdf(
    company_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Génère un rapport de recrutement en PDF."""
    from ..services.company_service import CompanyService
    
    company_service = CompanyService()
    company = company_service.get_company_by_id(db, company_id)
    
    if not company:
        raise HTTPException(status_code=404, detail="Entreprise non trouvée")
    
    # Récupérer les statistiques
    stats = application_service.get_application_stats(db, company_id=company_id)
    
    # Récupérer les candidatures récentes
    applications, _ = application_service.get_company_applications(db, company_id, skip=0, limit=50)
    formatted_apps = [{
        "candidate_name": f"{app.user.profile.first_name} {app.user.profile.last_name}" if app.user.profile else "N/A",
        "job_title": app.job.offre_brute.title if app.job.offre_brute else "N/A",
        "status": app.status,
        "applied_at": app.applied_at.strftime("%d/%m/%Y") if app.applied_at else "N/A",
    } for app in applications]
    
    pdf_data = export_service.generate_recruitment_report_pdf(
        company_name=company.name,
        stats=stats,
        applications=formatted_apps
    )
    
    if not pdf_data:
        raise HTTPException(status_code=500, detail="Erreur lors de la génération du PDF")
    
    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=rapport_recrutement_{company.name}.pdf"}
    )
