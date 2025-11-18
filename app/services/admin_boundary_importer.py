import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional
import geopandas as gpd
from sqlalchemy.orm import Session
from sqlalchemy import delete, func
from geoalchemy2.shape import from_shape
from shapely.geometry import shape
from difflib import get_close_matches
from sqlalchemy import or_, func

from app.models.database_models import OffreEmploiBrute, SenegalAdminBoundary

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
            
            print(row)
            # Nom de la zone (plusieurs conventions possibles)
            name = (
                row.get("NAME_1") or 
                row.get("NAME_2") or 
                row.get("NAME_3") or 
                row.get("NAME_4") or 
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
            "region": ["adm1", "region"],
            "departement": ["adm2", "departement"],
            "commune": ["adm3", "commune"],
            "arrondissement": ["adm4", "arrondissement"],
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


    def match_offers_to_boundaries(
        self, 
        db: Session, 
        level: str = None,
        similarity_threshold: int = 85
    ) -> Dict[str, Any]:
        """
        Mappe les offres aux limites administratives par matching texte.
        
        Args:
            level: Si spécifié, ne traite que ce niveau (ex: 'quartier')
            similarity_threshold: Score minimal (0-100) pour fuzzy matching
        """
        logger.info("🔄 Matching offres ↔ limites administratives (texte)")
        
        # 1. Récupérer toutes les limites
        boundaries = db.query(SenegalAdminBoundary).all()
        if not boundaries:
            logger.warning("Aucune limite administrative en DB")
            return {"status": "success", "matched": 0, "threshold": similarity_threshold}
        
        # 2. Construire un dictionnaire {nom: boundary_id}
        # Normaliser les noms (minuscules, sans accents)
        boundary_map = {
            self._normalize_name(b.name): b.id 
            for b in boundaries
        }
        
        # 3. Récupérer les offres sans admin_boundary_id
        query = db.query(OffreEmploiBrute).filter(
            OffreEmploiBrute.admin_boundary_id.is_(None),
            OffreEmploiBrute.location.isnot(None)
        )
        if level:
            query = query.join(SenegalAdminBoundary).filter(
                SenegalAdminBoundary.level == level
            )
        
        pending_offers = query.all()
        logger.info(f"📋 {len(pending_offers)} offres à matcher")
        
        # 4. Matcher chaque offre
        matched = 0
        for offer in pending_offers:
            matched_boundary = self._find_best_match(
                offer.location, 
                boundary_map, 
                similarity_threshold
            )
            
            if matched_boundary:
                offer.admin_boundary_id = matched_boundary
                matched += 1
        
        db.commit()
        logger.info(f"✅ {matched} offres matchées")
        
        return {
            "status": "success",
            "total_processed": len(pending_offers),
            "matched": matched,
            "threshold": similarity_threshold
        }
    
    def _normalize_name(self, name: str) -> str:
        """Normalise un nom pour matching."""
        import unicodedata
        
        if not name:
            return ""

        # Garder uniquement la partie avant la virgule
        if "," in name:
            name = name.split(",")[0]

        # Minuscule + trim
        name = name.lower().strip()

        # Supprimer les accents
        name = ''.join(
            c for c in unicodedata.normalize('NFD', name)
            if unicodedata.category(c) != 'Mn'
        )

        # Supprimer certaines ponctuations
        name = name.replace('-', ' ').replace('_', ' ')

        # Condenser les espaces multiples
        return ' '.join(name.split())

    
    def _find_best_match(
        self, 
        location: str, 
        boundary_map: dict, 
        threshold: int
    ) -> Optional[int]:
        """
        Trouve la meilleure correspondance entre location et noms de limites.
        """
        if not location:
            return None
        
        # Normaliser la location
        norm_location = self._normalize_name(location)
        
        # 1. Essai exact (contient)
        for boundary_name, boundary_id in boundary_map.items():
            if boundary_name in norm_location or norm_location in boundary_name:
                return boundary_id
        
        # 2. Fuzzy matching sur les mots clés
        location_words = norm_location.split()
        boundary_names = list(boundary_map.keys())
        
        # Chercher le meilleur match pour chaque mot
        for word in location_words:
            if len(word) < 3:  # Ignorer les mots courts (le, la, de...)
                continue
            
            matches = get_close_matches(
                word, 
                boundary_names, 
                n=1, 
                cutoff=threshold / 100
            )
            
            if matches:
                return boundary_map[matches[0]]
        
        return None
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