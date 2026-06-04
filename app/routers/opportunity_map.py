from __future__ import annotations

import math
import unicodedata
from typing import Any, Dict, Iterable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, func, or_, text
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.database_models import (
    CandidateCategory,
    OffreEmploiBrute,
    OffreEmploiEnrichie,
    SenegalAdminBoundary,
    User,
    UserProfile,
    UserRole,
)
from ..utils.auth import get_current_user

router = APIRouter(prefix="/api/v1/opportunity-map", tags=["opportunity-map"])


def _normalize(value: Optional[str]) -> str:
    raw = str(value or "")
    normalized = unicodedata.normalize("NFKD", raw)
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(without_accents.lower().replace("-", " ").replace("_", " ").split())


def _distance_km(origin: Dict[str, float], destination: Dict[str, float]) -> float:
    earth_radius_km = 6371.0
    lat1 = math.radians(origin["lat"])
    lat2 = math.radians(destination["lat"])
    d_lat = math.radians(destination["lat"] - origin["lat"])
    d_lng = math.radians(destination["lng"] - origin["lng"])
    a = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    return earth_radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _role_value(profile: UserProfile) -> str:
    role = getattr(getattr(profile, "user", None), "role", None)
    return getattr(role, "value", role) or UserRole.CANDIDATE.value


def _ensure_recruiter(profile: UserProfile) -> None:
    role = _role_value(profile)
    if role not in {UserRole.RECRUITER.value, UserRole.HR_MANAGER.value, UserRole.ADMIN.value}:
        raise HTTPException(status_code=403, detail="Accès réservé aux recruteurs")


def _boundary_rows(db: Session) -> list[Dict[str, Any]]:
    centroid_geometry = func.ST_GeomFromText(func.ST_AsText(SenegalAdminBoundary.centroid), 4326)
    rows = (
        db.query(
            SenegalAdminBoundary.id,
            SenegalAdminBoundary.name,
            SenegalAdminBoundary.level,
            SenegalAdminBoundary.parent_name,
            SenegalAdminBoundary.offer_count,
            func.ST_Y(centroid_geometry).label("lat"),
            func.ST_X(centroid_geometry).label("lng"),
        )
        .filter(SenegalAdminBoundary.centroid.isnot(None))
        .all()
    )

    return [
        {
            "id": row.id,
            "name": row.name,
            "level": row.level,
            "parent_name": row.parent_name,
            "offer_count": row.offer_count or 0,
            "coordinates": {"lat": float(row.lat), "lng": float(row.lng)} if row.lat is not None and row.lng is not None else None,
            "normalized_name": _normalize(row.name),
            "normalized_parent": _normalize(row.parent_name),
        }
        for row in rows
    ]


def _resolve_boundary(
    boundaries: Iterable[Dict[str, Any]],
    location: Optional[str],
    admin_boundary_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    boundary_list = list(boundaries)

    if admin_boundary_id is not None:
        direct = next((boundary for boundary in boundary_list if boundary["id"] == admin_boundary_id), None)
        if direct and direct.get("coordinates"):
            return direct

    normalized_location = _normalize(location)
    if not normalized_location:
        return None

    exact = next((boundary for boundary in boundary_list if boundary["normalized_name"] == normalized_location), None)
    if exact and exact.get("coordinates"):
        return exact

    contained = sorted(
        [
            boundary
            for boundary in boundary_list
            if boundary.get("coordinates")
            and (
                boundary["normalized_name"] in normalized_location
                or normalized_location in boundary["normalized_name"]
            )
        ],
        key=lambda boundary: len(boundary["normalized_name"]),
        reverse=True,
    )
    if contained:
        return contained[0]

    parent = next(
        (
            boundary
            for boundary in boundary_list
            if boundary.get("coordinates")
            and boundary["normalized_parent"]
            and boundary["normalized_parent"] in normalized_location
        ),
        None,
    )
    return parent


def _profile_center(profile: UserProfile, boundaries: list[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    boundary = _resolve_boundary(boundaries, profile.location, profile.admin_boundary_id)
    return boundary["coordinates"] if boundary else None


def _request_center(
    profile: UserProfile,
    boundaries: list[Dict[str, Any]],
    lat: Optional[float],
    lng: Optional[float],
    location: Optional[str],
) -> tuple[Optional[Dict[str, float]], str]:
    if lat is not None and lng is not None:
        return {"lat": float(lat), "lng": float(lng)}, "browser"

    if location:
        boundary = _resolve_boundary(boundaries, location)
        if boundary:
            return boundary["coordinates"], "location_filter"

    center = _profile_center(profile, boundaries)
    if center:
        return center, "profile"

    first_boundary = next((boundary for boundary in boundaries if boundary.get("coordinates")), None)
    if first_boundary:
        return first_boundary["coordinates"], "backend_boundary"

    return None, "unavailable"


def _skills_overlap_score(user_skills: list[str], target_skills: list[str], base: int = 62) -> int:
    normalized_user = {_normalize(skill) for skill in user_skills if skill}
    normalized_target = {_normalize(skill) for skill in target_skills if skill}
    if not normalized_target:
        return base
    overlap = len(normalized_user.intersection(normalized_target))
    score = base + min(30, overlap * 10)
    return max(45, min(98, score))


def _job_payload(
    brute: OffreEmploiBrute,
    enrichie: Optional[OffreEmploiEnrichie],
    boundaries: list[Dict[str, Any]],
    center: Optional[Dict[str, float]],
    user_skills: Optional[list[str]] = None,
) -> Optional[Dict[str, Any]]:
    boundary = _resolve_boundary(boundaries, brute.location, brute.admin_boundary_id)
    if not boundary:
        return None

    coordinates = boundary["coordinates"]
    skills = list(enrichie.extracted_skills or []) if enrichie else []
    distance = round(_distance_km(center, coordinates), 1) if center and coordinates else None

    return {
        "id": str(brute.id),
        "type": "job",
        "title": brute.title,
        "company_name": brute.company_name,
        "location": brute.location,
        "contract_type": (enrichie.extracted_contract_type if enrichie else None) or brute.contract_type,
        "remote_type": brute.remote_type,
        "is_urgent": bool(brute.is_urgent),
        "posted_date": brute.posted_date.isoformat() if brute.posted_date else None,
        "salary_min": enrichie.extracted_salary_min if enrichie else None,
        "salary_max": enrichie.extracted_salary_max if enrichie else None,
        "skills": skills,
        "sector": enrichie.extracted_sector if enrichie else brute.sector,
        "job_title": enrichie.extracted_job_title if enrichie else None,
        "coordinates": coordinates,
        "boundary": {
            "id": boundary["id"],
            "name": boundary["name"],
            "level": boundary["level"],
            "parent_name": boundary["parent_name"],
        },
        "distance_km": distance,
        "match_score": _skills_overlap_score(user_skills or [], skills),
        "detail_path": f"/candidate/job/{brute.id}",
    }


def _candidate_payload(
    profile: UserProfile,
    boundaries: list[Dict[str, Any]],
    center: Optional[Dict[str, float]],
    search_skills: list[str],
) -> Optional[Dict[str, Any]]:
    boundary = _resolve_boundary(boundaries, profile.location, profile.admin_boundary_id)
    if not boundary:
        return None

    coordinates = boundary["coordinates"]
    skills = list(profile.skills or [])
    distance = round(_distance_km(center, coordinates), 1) if center and coordinates else None
    first_name = profile.first_name or ""
    last_name = profile.last_name or ""
    display_name = " ".join(part for part in [first_name, last_name] if part).strip() or "Candidat"

    return {
        "id": str(profile.user_id),
        "profile_id": str(profile.id),
        "type": "talent",
        "name": display_name,
        "title": profile.current_title or "Profil candidat",
        "location": profile.location,
        "coordinates": coordinates,
        "boundary": {
            "id": boundary["id"],
            "name": boundary["name"],
            "level": boundary["level"],
            "parent_name": boundary["parent_name"],
        },
        "skills": skills,
        "experience_years": profile.experience_years or 0,
        "availability": profile.availability,
        "category": getattr(profile.category, "value", profile.category),
        "distance_km": distance,
        "match_score": _skills_overlap_score(search_skills, skills, base=65),
        "detail_path": f"/enterprise/candidates/{profile.user_id}",
    }


def _zone_payloads(
    boundaries: list[Dict[str, Any]],
    jobs: list[Dict[str, Any]],
    talents: list[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    zone_results: list[Dict[str, Any]] = []
    region_boundaries = [boundary for boundary in boundaries if boundary["level"] == "region" and boundary.get("coordinates")]

    for boundary in region_boundaries:
        normalized_name = boundary["normalized_name"]
        zone_jobs = [
            job
            for job in jobs
            if _normalize(job.get("boundary", {}).get("name")) == normalized_name
            or _normalize(job.get("boundary", {}).get("parent_name")) == normalized_name
            or normalized_name in _normalize(job.get("location"))
        ]
        zone_talents = [
            talent
            for talent in talents
            if _normalize(talent.get("boundary", {}).get("name")) == normalized_name
            or _normalize(talent.get("boundary", {}).get("parent_name")) == normalized_name
            or normalized_name in _normalize(talent.get("location"))
        ]

        skill_counts: Dict[str, int] = {}
        for job in zone_jobs:
            for skill in job.get("skills", []):
                skill_counts[skill] = skill_counts.get(skill, 0) + 1

        offer_count = len(zone_jobs) if zone_jobs else boundary["offer_count"]
        talent_count = len(zone_talents)
        tension_score = min(100, round((offer_count / (talent_count + 1)) * 18))

        zone_results.append(
            {
                "id": str(boundary["id"]),
                "type": "zone",
                "name": boundary["name"],
                "level": boundary["level"],
                "coordinates": boundary["coordinates"],
                "offer_count": offer_count,
                "talent_count": talent_count,
                "growth": 0,
                "tension_score": tension_score,
                "top_skills": [
                    skill
                    for skill, _ in sorted(skill_counts.items(), key=lambda item: item[1], reverse=True)[:4]
                ],
            }
        )

    return zone_results


def _jobs_query(
    db: Session,
    search: Optional[str],
    location: Optional[str],
    contract_type: Optional[str],
    sector: Optional[str],
    skill: Optional[str],
    user_category: Optional[str],
):
    query = db.query(OffreEmploiBrute, OffreEmploiEnrichie).join(
        OffreEmploiEnrichie,
        OffreEmploiBrute.id == OffreEmploiEnrichie.offre_id,
        isouter=True,
    )

    if user_category == CandidateCategory.PUPIL.value:
        query = query.filter(
            and_(
                or_(
                    func.lower(OffreEmploiBrute.title).contains("concours"),
                    func.lower(OffreEmploiBrute.title).contains("bourse"),
                    func.lower(OffreEmploiBrute.title).contains("examen"),
                    func.lower(OffreEmploiBrute.title).contains("ecole"),
                    OffreEmploiEnrichie.job_type == "scholarship_exam",
                ),
                func.lower(func.coalesce(OffreEmploiBrute.contract_type, "")).notin_(
                    ["cdd", "cdi", "stage", "internship", "emploi"]
                ),
            )
        )
    elif user_category == CandidateCategory.INFORMAL.value:
        query = query.filter(func.lower(func.coalesce(OffreEmploiBrute.education_level, "")).contains("sans diplôme"))

    if search:
        pattern = f"%{search.lower()}%"
        query = query.filter(
            or_(
                func.lower(OffreEmploiBrute.title).like(pattern),
                func.lower(OffreEmploiBrute.description).like(pattern),
                func.lower(OffreEmploiBrute.company_name).like(pattern),
                text("offres_emploi_enrichies.extracted_skills::text ILIKE :search_skill").params(search_skill=pattern),
            )
        )
    if location:
        query = query.filter(func.lower(OffreEmploiBrute.location).contains(func.lower(location)))
    if contract_type:
        query = query.filter(
            or_(
                func.lower(OffreEmploiBrute.contract_type).contains(func.lower(contract_type)),
                func.lower(OffreEmploiEnrichie.extracted_contract_type).contains(func.lower(contract_type)),
            )
        )
    if sector:
        query = query.filter(func.lower(OffreEmploiEnrichie.extracted_sector).contains(func.lower(sector)))
    if skill:
        query = query.filter(
            text("offres_emploi_enrichies.extracted_skills::text ILIKE :skill_filter").params(
                skill_filter=f"%{skill}%"
            )
        )

    return query.order_by(desc(OffreEmploiBrute.posted_date))


@router.get("/candidate", response_model=dict)
async def get_candidate_radar(
    search: Optional[str] = None,
    location: Optional[str] = None,
    contract_type: Optional[str] = None,
    sector: Optional[str] = None,
    skill: Optional[str] = None,
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lng: Optional[float] = Query(None, ge=-180, le=180),
    radius_km: int = Query(50, ge=1, le=500),
    limit: int = Query(120, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    boundaries = _boundary_rows(db)
    center, center_source = _request_center(current_user, boundaries, lat, lng, location)
    user_category = getattr(current_user.category, "value", current_user.category)
    user_skills = list(current_user.skills or [])

    query = _jobs_query(db, search, location, contract_type, sector, skill, user_category)
    rows = query.limit(limit * 2).all()

    jobs: list[Dict[str, Any]] = []
    for brute, enrichie in rows:
        payload = _job_payload(brute, enrichie, boundaries, center, user_skills)
        if not payload:
            continue
        if center and payload["distance_km"] is not None and payload["distance_km"] > radius_km:
            continue
        jobs.append(payload)
        if len(jobs) >= limit:
            break

    zones = _zone_payloads(boundaries, jobs, [])

    return {
        "mode": "candidate",
        "center": center,
        "center_source": center_source,
        "radius_km": radius_km,
        "jobs": jobs,
        "talents": [],
        "zones": zones,
        "totals": {
            "jobs": len(jobs),
            "talents": 0,
            "zones": len(zones),
            "critical_zones": len([zone for zone in zones if zone["tension_score"] >= 60]),
        },
    }


@router.get("/recruiter", response_model=dict)
async def get_recruiter_radar(
    search: Optional[str] = None,
    location: Optional[str] = None,
    contract_type: Optional[str] = None,
    sector: Optional[str] = None,
    skill: Optional[str] = None,
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lng: Optional[float] = Query(None, ge=-180, le=180),
    radius_km: int = Query(50, ge=1, le=500),
    limit: int = Query(120, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: UserProfile = Depends(get_current_user),
):
    _ensure_recruiter(current_user)

    boundaries = _boundary_rows(db)
    center, center_source = _request_center(current_user, boundaries, lat, lng, location)

    job_rows = _jobs_query(db, search, location, contract_type, sector, skill, None).limit(limit).all()
    jobs: list[Dict[str, Any]] = []
    for brute, enrichie in job_rows:
        payload = _job_payload(brute, enrichie, boundaries, center, [])
        if not payload:
            continue
        payload["detail_path"] = f"/enterprise/jobs"
        if center and payload["distance_km"] is not None and payload["distance_km"] > radius_km:
            continue
        jobs.append(payload)

    talent_query = db.query(UserProfile).join(User, UserProfile.user_id == User.id).filter(
        User.role == UserRole.CANDIDATE,
        UserProfile.is_active.is_(True),
        UserProfile.category != CandidateCategory.PUPIL,
    )

    if search:
        pattern = f"%{search}%"
        talent_query = talent_query.filter(
            or_(
                UserProfile.first_name.ilike(pattern),
                UserProfile.last_name.ilike(pattern),
                UserProfile.current_title.ilike(pattern),
                text("user_profiles.skills::text ILIKE :talent_search").params(talent_search=pattern),
            )
        )
    if location:
        talent_query = talent_query.filter(UserProfile.location.ilike(f"%{location}%"))
    if skill:
        talent_query = talent_query.filter(
            text("user_profiles.skills::text ILIKE :talent_skill").params(talent_skill=f"%{skill}%")
        )

    requested_skills = [part.strip() for part in [skill, search] if part and part.strip()]
    talent_rows = talent_query.limit(limit * 2).all()
    talents: list[Dict[str, Any]] = []
    for profile in talent_rows:
        payload = _candidate_payload(profile, boundaries, center, requested_skills)
        if not payload:
            continue
        if center and payload["distance_km"] is not None and payload["distance_km"] > radius_km:
            continue
        talents.append(payload)
        if len(talents) >= limit:
            break

    zones = _zone_payloads(boundaries, jobs, talents)

    return {
        "mode": "recruiter",
        "center": center,
        "center_source": center_source,
        "radius_km": radius_km,
        "jobs": jobs,
        "talents": talents,
        "zones": zones,
        "totals": {
            "jobs": len(jobs),
            "talents": len(talents),
            "zones": len(zones),
            "critical_zones": len([zone for zone in zones if zone["tension_score"] >= 60]),
        },
    }
