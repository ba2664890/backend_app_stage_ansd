import json
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from ..models.database_models import SenegalAdminBoundary, OffreEmploiBrute
from ..models.api_models import AdminBoundaryOut
from app.core.exceptions import AppError 

logger = logging.getLogger(__name__)

class AdminBoundaryService:
    """
    Service dédié à la gestion des limites administratives.
    Toutes les exceptions sont transformées en `AppError` pour le contrôleur.
    """

    # ------------------------------------------------------------------
    # 1. Récupération des limites + stats
    # ------------------------------------------------------------------
    def get_boundaries(self, db: Session, level: str) -> List[AdminBoundaryOut]:
        """
        Retourne les limites administratives d'un niveau donné
        avec le nombre d'offres intersectées (mise à jour possible via refresh).
        """
        try:
            boundaries = (
                db.query(SenegalAdminBoundary)
                .filter(SenegalAdminBoundary.level == level)
                .order_by(SenegalAdminBoundary.name)
                .all()
            )
            return [AdminBoundaryOut.from_orm(b) for b in boundaries]
        except Exception as exc:
            logger.exception("Erreur lors de la récupération des limites")
            raise AppError("Impossible de charger les limites administratives") from exc

    # ------------------------------------------------------------------
    # 2. Rafraîchissement des compteurs d'offres (intersection PostGIS)
    # ------------------------------------------------------------------
    def refresh_offer_counts(self, db: Session, level: str) -> None:
        """
        Met à jour la colonne `offer_count` en intersectant les offres
        (lng,lat) avec les polygones PostGIS.
        Exécuté périodiquement ou via endpoint admin.
        """
        sql = """
        WITH counts AS (
            SELECT ab.id, COUNT(o.id) AS nb
            FROM senegal_admin_boundaries ab
            JOIN offre_emploi_brute o ON ST_Contains(
                ST_SetSRID(ST_GeomFromGeoJSON(ab.geojson->>'geometry'), 4326),
                ST_SetSRID(ST_MakePoint(o.lng, o.lat), 4326)
            )
            WHERE ab.level = :level
            GROUP BY ab.id
        )
        UPDATE senegal_admin_boundaries ab
        SET offer_count = COALESCE(c.nb, 0),
            updated_at = NOW()
        FROM counts c
        WHERE c.id = ab.id;
        """
        try:
            db.execute(text(sql), {"level": level})
            db.commit()
            logger.info("Compteurs d'offres rafraîchis pour level=%s", level)
        except Exception as exc:
            db.rollback()
            logger.exception("Erreur lors du rafraîchissement des compteurs")
            raise AppError("Mise à jour des compteurs échouée") from exc

    # ------------------------------------------------------------------
    # 3. Injection bulk de GeoJSON (admin uniquement)
    # ------------------------------------------------------------------
    def bulk_insert_geojson(self, db: Session, geojson_file: str, level: str) -> int:
        """
        Charge un fichier GeoJSON (FeatureCollection) dans la table.
        Retourne le nombre d'enregistrements créés.
        """
        try:
            with open(geojson_file, encoding="utf-8") as f:
                collection = json.load(f)

            features = collection.get("features", [])
            if not features:
                raise AppError("Aucune entité trouvée dans le fichier")

            inserted = 0
            for feat in features:
                geom = feat.get("geometry")
                props = feat.get("properties", {})
                name = props.get("name") or props.get("nom") or props.get("NAME")
                if not name:
                    logger.warning("Entité sans nom ignorée")
                    continue

                # Calcul du centroïd (PostGIS)
                centroid = db.scalar(
                    text(
                        "SELECT ST_AsGeoJSON(ST_Centroid(ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4326)))"
                    ),
                    {"geom": json.dumps(geom)},
                )
                lon_lat = json.loads(centroid)["coordinates"] if centroid else None

                boundary = SenegalAdminBoundary(
                    name=name,
                    level=level,
                    parent_name=props.get("parent"),
                    geojson={"type": "Feature", "geometry": geom, "properties": props},
                    centroid=f"POINT({lon_lat[0]} {lon_lat[1]})" if lon_lat else None,
                )
                db.add(boundary)
                inserted += 1

            db.commit()
            logger.info("%d limites insérées (level=%s)", inserted, level)
            return inserted
        except Exception as exc:
            db.rollback()
            logger.exception("Erreur lors du chargement du GeoJSON")
            raise AppError("Chargement du GeoJSON échoué") from exc