import os
import logging
from pathlib import Path
import pandas as pd
from typing import Any, Dict, Optional, List
import geopandas as gpd
from sqlalchemy.orm import Session
from sqlalchemy import delete, func, or_
from app.services.admin_boundary import AdminBoundaryService
from geoalchemy2.shape import from_shape
from shapely.geometry import shape
from difflib import get_close_matches

from app.models.database_models import OffreEmploiBrute, SenegalAdminBoundary, UserProfile, Company

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
        
        # Chargement du CSV pour le mapping département -> région
        csv_path = self.data_dir / "SEN_adm2.csv"
        self.dept_to_region: Dict[str, str] = {}
        
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)
                for _, row in df.iterrows():
                    dept_name = str(row["NAME_2"]).strip()
                    region_name = str(row["NAME_1"]).strip()
                    if dept_name and region_name:
                        self.dept_to_region[dept_name] = region_name
                logger.info(f"📊 CSV chargé : {len(self.dept_to_region)} départements mappés")
            except Exception as e:
                logger.error(f"❌ Erreur lecture CSV : {e}")
        else:
            logger.warning(f"⚠️ CSV non trouvé : {csv_path}")

    def import_one_shapefile(self, db: Session, shp_path: Path, level: str):
        logger.info(f"📍 Import {level} : {shp_path.name}")

        gdf = gpd.read_file(shp_path).to_crs(4326)

        if gdf.empty:
            logger.warning(f"⚠️ Shapefile vide : {shp_path}")
            return 0

        # Mapping des colonnes de nom
        name_map = {
            "region": "NAME_1",
            "departement": "NAME_2",
            "arrondissement": "NAME_3",
            "commune": "NAME_4",
        }

        # Mapping parent UNIQUEMENT pour les niveaux non couverts par CSV
        parent_map = {
            "arrondissement": "NAME_2",
            "commune": "NAME_3",
        }

        if level not in name_map:
            raise ValueError(f"Niveau inconnu : {level}")

        name_col = name_map[level]

        records = []
        for _, row in gdf.iterrows():
            geojson = row.geometry.__geo_interface__
            centroid_wkt = row.geometry.centroid.wkt
            name = row.get(name_col)

            # Détermination du parent selon le niveau (UNIQUEMENT pour region/departement)
            if level == "region":
                parent_name = "Senegal"
            elif level == "departement":
                parent_name = self.dept_to_region.get(name)
                if not parent_name:
                    logger.warning(f"⚠️ Département '{name}' non trouvé dans le CSV")
                    parent_name = row.get("NAME_1")
            else:
                parent_col = parent_map.get(level)
                parent_name = row.get(parent_col) if parent_col else None

            if not name:
                logger.warning(f"⚠️ Nom manquant pour une entité {level} dans {shp_path}")
                continue

            records.append({
                "name": str(name)[:255],
                "level": level,
                "parent_name": str(parent_name)[:255] if parent_name else None,
                "geojson": geojson,
                "centroid": centroid_wkt,
                "offer_count": 0,
            })

        db.execute(SenegalAdminBoundary.__table__.insert(), records)
        db.commit()

        logger.info(f"✅ {len(records)} limites importées ({level})")
        return len(records)

    def import_all(self, db: Session, clean: bool = True):
        logger.info(f"🚀 DÉBUT IMPORT depuis {self.data_dir}")

        if clean:
            deleted = db.execute(delete(SenegalAdminBoundary)).rowcount
            db.commit()
            logger.info(f"🧹 {deleted} anciennes données supprimées")

        file_mapping = {
            "region": ["adm1", "region"],
            "departement": ["adm2", "departement"],
            "arrondissement": ["adm3", "arrondissement"],
            "commune": ["adm4", "commune"],
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
    def match_offers_to_boundaries(self, db: Session, similarity_threshold: int = 85) -> Dict[str, Any]:
        logger.info("🔄 Matching offres ↔ limites administratives")
        return self._match_entities_to_boundaries(db, OffreEmploiBrute, similarity_threshold)

    def match_talents_to_boundaries(self, db: Session, similarity_threshold: int = 85) -> Dict[str, Any]:
        logger.info("🔄 Matching talents ↔ limites administratives")
        return self._match_entities_to_boundaries(db, UserProfile, similarity_threshold)

    def match_companies_to_boundaries(self, db: Session, similarity_threshold: int = 85) -> Dict[str, Any]:
        logger.info("🔄 Matching entreprises ↔ limites administratives")
        return self._match_entities_to_boundaries(db, Company, similarity_threshold)

    def _match_entities_to_boundaries(self, db: Session, model_class: Any, similarity_threshold: int = 85) -> Dict[str, Any]:
        """Méthode générique pour matcher n'importe quel modèle ayant 'location' et 'admin_boundary_id'."""
        boundaries = db.query(SenegalAdminBoundary).all()
        if not boundaries:
            return {"status": "success", "matched": 0}

        boundary_map = {
            self._normalize_name(str(b.name)): b.id
            for b in boundaries
        }

        # On ne traite que ceux qui n'ont pas encore de boundary_id
        entities = db.query(model_class).filter(
            model_class.location.isnot(None),
            model_class.admin_boundary_id.is_(None)
        ).all()
        
        logger.info(f"📋 {len(entities)} {model_class.__name__} à matcher")

        matched = 0
        for entity in entities:
            matched_id = self._find_best_match(
                str(entity.location),
                boundary_map,
                similarity_threshold,
            )

            if matched_id:
                entity.admin_boundary_id = int(matched_id)
                matched += 1

        db.commit()
        return {
            "status": "success",
            "entity": model_class.__name__,
            "total_processed": len(entities),
            "matched": matched,
        }

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

    def _find_best_match(self, location: Optional[str], boundary_map: dict, threshold: int) -> Optional[int]:
        if not isinstance(location, str):
            return None
        norm_location = self._normalize_name(location)

        for boundary_name, boundary_id in boundary_map.items():
            if boundary_name in norm_location or norm_location in boundary_name:
                return boundary_id

        words = norm_location.split()
        names = list(boundary_map.keys())
        for word in words:
            if len(word) < 3:
                continue
            matches = get_close_matches(word, names, n=1, cutoff=threshold / 100)
            if matches:
                return boundary_map[matches[0]]
        return None

    def verify_import(self, db: Session):
        stats = db.query(
            SenegalAdminBoundary.level,
            func.count(SenegalAdminBoundary.id),
        ).group_by(SenegalAdminBoundary.level).all()
        result = {level: count for level, count in stats}
        logger.info(f"📊 Stats import : {result}")
        return result

    def match_and_refresh(self, db: Session, level: str = None):
        """Matching + refresh atomique pour éviter incohérence."""
        try:
            match_result = self.match_offers_to_boundaries(db)
            if match_result["matched"] > 0:
                service = AdminBoundaryService()
                refresh = service.refresh_offer_counts(db, level)
                match_result["offer_counts_updated"] = refresh["updated_rows"]
            return match_result
        except Exception:
            db.rollback()
            raise