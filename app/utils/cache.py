"""
Service de cache Redis pour améliorer les performances.
"""

from typing import Optional, Any
import json
import logging
from functools import wraps
from datetime import timedelta

logger = logging.getLogger(__name__)

try:
    import redis
    from redis import Redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis non installé. Cache désactivé. Installez avec: pip install redis")


class CacheService:
    """Service de cache avec Redis."""
    
    def __init__(self, host: str = 'localhost', port: int = 6379, db: int = 0):
        """
        Initialise le service de cache.
        
        Args:
            host: Hôte Redis
            port: Port Redis
            db: Numéro de base de données Redis
        """
        if REDIS_AVAILABLE:
            try:
                self.redis_client = Redis(
                    host=host,
                    port=port,
                    db=db,
                    decode_responses=True,
                    socket_connect_timeout=2
                )
                # Test de connexion
                self.redis_client.ping()
                self.enabled = True
                logger.info(f"Cache Redis connecté: {host}:{port}")
            except Exception as e:
                logger.warning(f"Impossible de se connecter à Redis: {e}. Cache désactivé.")
                self.enabled = False
                self.redis_client = None
        else:
            self.enabled = False
            self.redis_client = None
    
    def get(self, key: str) -> Optional[Any]:
        """Récupère une valeur du cache."""
        if not self.enabled or not self.redis_client:
            return None
        
        try:
            value = self.redis_client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Erreur lecture cache: {e}")
            return None
    
    def set(
        self,
        key: str,
        value: Any,
        ttl: int = 300
    ) -> bool:
        """
        Stocke une valeur dans le cache.
        
        Args:
            key: Clé du cache
            value: Valeur à stocker (sera sérialisée en JSON)
            ttl: Durée de vie en secondes (défaut: 5 minutes)
        """
        if not self.enabled or not self.redis_client:
            return False
        
        try:
            serialized = json.dumps(value, default=str)
            self.redis_client.setex(key, ttl, serialized)
            return True
        except Exception as e:
            logger.error(f"Erreur écriture cache: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Supprime une clé du cache."""
        if not self.enabled or not self.redis_client:
            return False
        
        try:
            self.redis_client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Erreur suppression cache: {e}")
            return False
    
    def delete_pattern(self, pattern: str) -> int:
        """
        Supprime toutes les clés correspondant à un pattern.
        
        Args:
            pattern: Pattern Redis (ex: "user:*", "salary:benchmark:*")
        
        Returns:
            Nombre de clés supprimées
        """
        if not self.enabled or not self.redis_client:
            return 0
        
        try:
            keys = self.redis_client.keys(pattern)
            if keys:
                return self.redis_client.delete(*keys)
            return 0
        except Exception as e:
            logger.error(f"Erreur suppression pattern cache: {e}")
            return 0
    
    def clear_all(self) -> bool:
        """Vide tout le cache (à utiliser avec précaution)."""
        if not self.enabled or not self.redis_client:
            return False
        
        try:
            self.redis_client.flushdb()
            logger.info("Cache vidé complètement")
            return True
        except Exception as e:
            logger.error(f"Erreur vidage cache: {e}")
            return False


# Instance globale du cache
cache_service = CacheService()


def cache_result(ttl: int = 300, key_prefix: str = ""):
    """
    Décorateur pour mettre en cache le résultat d'une fonction.
    
    Args:
        ttl: Durée de vie du cache en secondes
        key_prefix: Préfixe pour la clé de cache
    
    Usage:
        @cache_result(ttl=600, key_prefix="salary:benchmark")
        def get_salary_benchmark(job_category, sector):
            # Calculs lourds...
            return result
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Générer une clé de cache unique
            cache_key = f"{key_prefix}:{func.__name__}:{str(args)}:{str(sorted(kwargs.items()))}"
            
            # Essayer de récupérer du cache
            cached_value = cache_service.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache HIT: {cache_key}")
                return cached_value
            
            # Exécuter la fonction
            logger.debug(f"Cache MISS: {cache_key}")
            result = func(*args, **kwargs)
            
            # Mettre en cache
            cache_service.set(cache_key, result, ttl)
            
            return result
        return wrapper
    return decorator


def invalidate_cache(pattern: str):
    """
    Invalide le cache pour un pattern donné.
    
    Usage:
        invalidate_cache("salary:benchmark:*")
    """
    count = cache_service.delete_pattern(pattern)
    logger.info(f"Cache invalidé: {count} clés supprimées pour pattern '{pattern}'")
    return count


# Exemples d'utilisation dans les services:

"""
# Dans salary_benchmark_service.py:

from ..utils.cache import cache_result, invalidate_cache

class SalaryBenchmarkService:
    
    @cache_result(ttl=3600, key_prefix="salary:benchmark")
    def get_salary_benchmark(self, db, job_category, sector, location):
        # Calculs lourds...
        return benchmark_data
    
    def update_salary_data(self, db, new_data):
        # Mise à jour des données
        # ...
        
        # Invalider le cache
        invalidate_cache("salary:benchmark:*")


# Dans analytics_service.py:

from ..utils.cache import cache_result

class AnalyticsService:
    
    @cache_result(ttl=600, key_prefix="analytics:dashboard")
    def get_dashboard_stats(self, db, company_id):
        # Calculs d'analytics...
        return stats
"""
