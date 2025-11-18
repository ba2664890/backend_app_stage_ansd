import os
import logging
from pathlib import Path
from typing import Optional
import geopandas as gpd
from sqlalchemy.orm import Session
from sqlalchemy import delete, func
from geoalchemy2.shape import from_shape
from shapely.geometry import shape

from app.models.database_models import SenegalAdminBoundary

logger = logging.getLogger(__name__)


class AdminBoundaryImporterService:
    """
    Service pour importer les shapefiles locaux SIG dans PostGIS.
    - Lecture depuis docs/SEN_adm/
    - Import optimisé (bulk insert)
    - Génération du centroid et conversion GeoJSON
    """

    def __init__(self, data_dir: Optional[str] = None):
        """
        Args:
            data_dir: Chemin relatif depuis le dossier 'service'. 
                     Par défaut: '../docs/SEN_adm'
        """
        if data_dir is None:
            # Chemin relatif depuis ce fichier (service/)
            self.data_dir = Path(__file__).parent.parent / "SEN_adm"
        else:
            self.data_dir = Path(data_dir)
        
        if not self.data_dir.exists():
            raise FileNotFoundError(f"Dossier non trouvé : {self.data_dir}")

    # ------------------------------------------------------------
    # Import d’un shapefile donné
    # ------------------------------------------------------------
    def import_one_shapefile(self, db: Session, shp_path: Path, level: str):
        logger.info(f"📍 Import {level} : {shp_path.name}")

        # Lecture et projection
        gdf = gpd.read_file(shp_path).to_crs(4326)
        
        if gdf.empty:
            logger.warning(f"⚠️  Shapefile vide : {shp_path}")
            return 0

        # Préparer les données pour bulk insert
        records = []
        for _, row in gdf.iterrows():
            # Conversion GeoJSON
            geojson = row.geometry.__geo_interface__
            
            # Calcul du centroid (format WKT pour Geography)
            centroid_wkt = row.geometry.centroid.wkt
            
            # Nom de la zone (plusieurs conventions possibles)
            name = (
                row.get("NAME") or 
                row.get("name") or 
                row.get("NOM") or 
                row.get("nom") or 
                "Inconnu"
            )
            
            records.append({
                "name": str(name)[:255],
                "level": level,
                "parent_name": row.get("PARENT", "")[:255] if "PARENT" in row else None,
                "geojson": geojson,
                "centroid": centroid_wkt,
                "offer_count": 0
            })

        # Insertion bulk optimisée
        db.execute(
            SenegalAdminBoundary.__table__.insert(),
            records
        )
        db.commit()
        
        logger.info(f"✅ {len(records)} limites importées ({level})")
        return len(records)

    # ------------------------------------------------------------
    # Import complet
    # ------------------------------------------------------------
    def import_all(self, db: Session, clean: bool = True):
        """
        Importe tous les niveaux administratifs depuis le dossier local.
        
        Args:
            db: Session SQLAlchemy
            clean: Si True, vide la table avant import
        """
        logger.info(f"🚀 DÉBUT IMPORT depuis {self.data_dir}")

        # Nettoyage optionnel
        if clean:
            deleted = db.execute(delete(SenegalAdminBoundary)).rowcount
            db.commit()
            logger.info(f"🧹 {deleted} anciennes données supprimées")

        # Mapping des fichiers par pattern de nom
        # - Clé : level dans la DB
        # - Valeurs : patterns possibles dans le nom de fichier
        file_mapping = {
            "region": ["adm0", "region"],
            "departement": ["adm1", "departement"],
            "commune": ["adm2", "commune"],
            "arrondissement": ["adm3", "arrondissement"],
            "quartier": ["adm4", "quartier"]
        }

        total_imported = 0
        
        # Scanner les fichiers .shp
        shp_files = list(self.data_dir.glob("*.shp"))
        
        if not shp_files:
            logger.error(f"❌ Aucun fichier .shp trouvé dans {self.data_dir}")
            return {"status": "error", "message": "Aucun shapefile trouvé"}

        for level, patterns in file_mapping.items():
            for shp_path in shp_files:
                # Vérifier si le fichier correspond à un level
                lower_name = shp_path.name.lower()
                if any(pattern.lower() in lower_name for pattern in patterns):
                    try:
                        count = self.import_one_shapefile(db, shp_path, level)
                        total_imported += count
                    except Exception as e:
                        logger.error(f"❌ Erreur import {level} : {e}")
                        db.rollback()
                    break  # Passer au level suivant après le premier match

        logger.info(f"🎉 IMPORT COMPLET : {total_imported} limites importées")
        return {
            "status": "success",
            "total_imported": total_imported,
            "source_dir": str(self.data_dir)
        }

    # ------------------------------------------------------------
    # Vérification rapide
    # ------------------------------------------------------------
    def verify_import(self, db: Session):
        """Retourne le nombre de limites par niveau."""
        stats = db.query(
            SenegalAdminBoundary.level,
            func.count(SenegalAdminBoundary.id).label('count')
        ).group_by(SenegalAdminBoundary.level).all()
        
        result = {level: count for level, count in stats}
        logger.info(f"📊 Stats import : {result}")
        return result