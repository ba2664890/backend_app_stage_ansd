import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional
import geopandas as gpd
from sqlalchemy.orm import Session
from sqlalchemy import delete, func
from app.services.admin_boundary import AdminBoundaryService
from geoalchemy2.shape import from_shape
from shapely.geometry import shape
from difflib import get_close_matches
from sqlalchemy import or_, func

from app.models.database_models import OffreEmploiBrute, SenegalAdminBoundary

logger = logging.getLogger(__name__)


class AdminBoundaryImporterService:
    """
    Service pour importer les shapefiles locaux SIG dans PostGIS.
    """

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            self.data_dir = Path(__file__).parent.parent / "SEN_adm"
        else:
            self.data_dir = Path(data_dir)

        if not self.data_dir.exists():
            raise FileNotFoundError(f"Dossier non trouvé : {self.data_dir}")

    # ------------------------------------------------------------
    # Import d’un shapefile
    # ------------------------------------------------------------
    def import_one_shapefile(self, db: Session, shp_path: Path, level: str):
        logger.info(f"📍 Import {level} : {shp_path.name}")

        gdf = gpd.read_file(shp_path).to_crs(4326)

        if gdf.empty:
            logger.warning(f"⚠️  Shapefile vide : {shp_path}")
            return 0

        records = []
        for _, row in gdf.iterrows():
            geojson = row.geometry.__geo_interface__
            centroid_wkt = row.geometry.centroid.wkt

            name = row.get("NAME_")

            records.append({
                "name": str(name)[:255],
                "level": level,
                "parent_name": row.get("PARENT", "")[:255] if "PARENT" in row else None,
                "geojson": geojson,
                "centroid": centroid_wkt,
                "offer_count": 0,
            })
        print(records)
        db.execute(SenegalAdminBoundary.__table__.insert(), records)
        db.commit()

        logger.info(f"✅ {len(records)} limites importées ({level})")
        return len(records)

    # ------------------------------------------------------------
    # Import complet
    # ------------------------------------------------------------
    def import_all(self, db: Session, clean: bool = True):
        logger.info(f"🚀 DÉBUT IMPORT depuis {self.data_dir}")

        if clean:
            deleted = db.execute(delete(SenegalAdminBoundary)).rowcount
            db.commit()
            logger.info(f"🧹 {deleted} anciennes données supprimées")

        file_mapping = {
            "region": ["adm1", "region"],
            "departement": ["adm2", "departement"],
            "commune": ["adm3", "commune"],
            "arrondissement": ["adm4", "arrondissement"],
        }

        total_imported = 0
        shp_files = list(self.data_dir.glob("*.shp"))

        if not shp_files:
            return {"status": "error", "message": "Aucun shapefile trouvé"}

        for level, patterns in file_mapping.items():
            for shp_path in shp_files:
                lower_name = shp_path.name.lower()
                if any(p in lower_name for p in patterns):
                    try:
                        count = self.import_one_shapefile(db, shp_path, level)
                        total_imported += count
                    except Exception as e:
                        logger.error(f"❌ Erreur import {level} : {e}")
                        db.rollback()
                    break

        logger.info(f"🎉 IMPORT COMPLET : {total_imported} limites importées")
        return {"status": "success", "total_imported": total_imported}

    # ------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------
    def match_offers_to_boundaries(
        self,
        db: Session,
        level: str = None,
        similarity_threshold: int = 85,
    ) -> Dict[str, Any]:

        logger.info("🔄 Matching offres ↔ limites administratives (texte)")

        boundaries = db.query(SenegalAdminBoundary).all()
        if not boundaries:
            return {"status": "success", "matched": 0}

        # 🔥 Cast pour éviter Column[str] → str
        boundary_map = {
            self._normalize_name(str(b.name)): b.id
            for b in boundaries
        }

        query = db.query(OffreEmploiBrute).filter(
            OffreEmploiBrute.admin_boundary_id.is_(None),
            OffreEmploiBrute.location.isnot(None),
        )

        if level:
            query = query.join(SenegalAdminBoundary).filter(
                SenegalAdminBoundary.level == level
            )
            print(query)

        pending_offers = query.all()
        logger.info(f"📋 {len(pending_offers)} offres à matcher")

        matched = 0

        for offer in pending_offers:
            matched_boundary = self._find_best_match(
                str(offer.location),  # 🔥 Cast ici
                boundary_map,
                similarity_threshold,
            )

            if matched_boundary:
                offer.admin_boundary_id = int(matched_boundary)  # 🔥 Cast int() pour Pylance
                matched += 1

        db.commit()

        return {
            "status": "success",
            "total_processed": len(pending_offers),
            "matched": matched,
        }

    # ------------------------------------------------------------
    # Normalisation des noms
    # ------------------------------------------------------------
    def _normalize_name(self, name: Optional[str]) -> str:
        import unicodedata

        if not isinstance(name, str):
            return ""

        if "," in name:
            name = name.split(",")[0]

        name = name.lower().strip()

        name = "".join(
            c for c in unicodedata.normalize("NFD", name)
            if unicodedata.category(c) != "Mn"
        )

        name = name.replace("-", " ").replace("_", " ")

        return " ".join(name.split())

    # ------------------------------------------------------------
    # Fuzzy matching
    # ------------------------------------------------------------
    def _find_best_match(
        self,
        location: Optional[str],
        boundary_map: dict,
        threshold: int,
    ) -> Optional[int]:

        if not isinstance(location, str):
            return None

        location = str(location)
        norm_location = self._normalize_name(location)

        # --- matching exact ---
        for boundary_name, boundary_id in boundary_map.items():
            if boundary_name in norm_location or norm_location in boundary_name:
                return boundary_id

        # --- fuzzy matching ---
        words = norm_location.split()
        names = list(boundary_map.keys())

        for word in words:
            if len(word) < 3:
                continue

            matches = get_close_matches(
                word,
                names,
                n=1,
                cutoff=threshold / 100,
            )

            if matches:
                return boundary_map[matches[0]]

        return None

    # ------------------------------------------------------------
    # Vérification des imports
    # ------------------------------------------------------------
    def verify_import(self, db: Session):
        stats = db.query(
            SenegalAdminBoundary.level,
            func.count(SenegalAdminBoundary.id),
        ).group_by(SenegalAdminBoundary.level).all()

        result = {level: count for level, count in stats}
        logger.info(f"📊 Stats import : {result}")
        return result


    # Fin du fichier - ajoutez :
    # Dans admin_boundary_importer.py
    def match_and_refresh(self, db: Session, level: str = None):
        """Matching + refresh atomique pour éviter incohérence."""
        try:
            # 1. Match les offres
            match_result = self.match_offers_to_boundaries(db, level)
            
            # 2. Si des offres ont été matchées, refresh immédiatement
            if match_result["matched"] > 0:
                service = AdminBoundaryService()
                refresh = service.refresh_offer_counts(db, level)
                match_result["offer_counts_updated"] = refresh["updated_rows"]
            
            return match_result
        except Exception:
            db.rollback()
            raise