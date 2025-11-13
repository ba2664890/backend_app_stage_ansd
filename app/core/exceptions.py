"""
Module d'exceptions métier centralisées.
Toutes les exceptions spécifiques à l'application héritent de AppError.
Permet une gestion homogène des erreurs (logs, HTTP, monitoring).
"""

import logging
from typing import Optional, Dict, Any
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """
    Exception racine de l'application.
    Encapsule message, code HTTP, contexte technique et logging automatique.
    """
    
    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        context: Optional[Dict[str, Any]] = None,
        log_level: int = logging.ERROR,
        log_stack: bool = True,
    ) -> None:
        """
        :param message: Message compréhensible pour le client/fonctionnel
        :param status_code: Code HTTP à retourner (404, 422, etc.)
        :param context: Données techniques supplémentaires (IDs, SQL, etc.)
        :param log_level: Niveau de log (ERROR, WARNING, INFO)
        :param log_stack: True pour logger la stacktrace complète
        """
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.context = context or {}
        
        # Log automatique à la création (évite de répéter logger.error() partout)
        log_func = logger.info if log_level == logging.INFO else \
                   logger.warning if log_level == logging.WARNING else \
                   logger.error
        
        if log_stack and log_level >= logging.ERROR:
            log_func(f"{message} | context={self.context}", exc_info=True)
        else:
            log_func(f"{message} | context={self.context}")


# -----------------------
# Sous-classes pratiques
# -----------------------

class NotFoundError(AppError):
    """Ressource introuvable (404)"""
    def __init__(self, resource: str, identifier: Any, context: Optional[Dict] = None):
        super().__init__(
            message=f"{resource} non trouvé(e) : {identifier}",
            status_code=status.HTTP_404_NOT_FOUND,
            context={"resource": resource, "id": identifier, **(context or {})},
            log_level=logging.WARNING,
            log_stack=False,
        )


class ValidationError(AppError):
    """Données invalides (422)"""
    def __init__(self, field: str, reason: str, context: Optional[Dict] = None):
        super().__init__(
            message=f"Validation échouée sur '{field}': {reason}",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            context={"field": field, "reason": reason, **(context or {})},
            log_level=logging.WARNING,
            log_stack=False,
        )


class ConflictError(AppError):
    """Conflit d'état (409)"""
    def __init__(self, resource: str, details: str, context: Optional[Dict] = None):
        super().__init__(
            message=f"Conflit sur {resource}: {details}",
            status_code=status.HTTP_409_CONFLICT,
            context={"resource": resource, "details": details, **(context or {})},
            log_level=logging.WARNING,
        )


class UnauthorizedError(AppError):
    """Accès interdit (401/403)"""
    def __init__(self, action: str, user: Optional[str] = None, context: Optional[Dict] = None):
        super().__init__(
            message=f"Accès refusé pour {action}",
            status_code=status.HTTP_403_FORBIDDEN,
            context={"action": action, "user": user, **(context or {})},
            log_level=logging.WARNING,
            log_stack=False,
        )


class ExternalAPIError(AppError):
    """Erreur d'appel API externe (502)"""
    def __init__(self, service: str, status: int, body: str, context: Optional[Dict] = None):
        super().__init__(
            message=f"Service externe {service} a échoué ({status})",
            status_code=status.HTTP_502_BAD_GATEWAY,
            context={"service": service, "status": status, "body": body, **(context or {})},
        )


# -----------------------
# Handler global FastAPI
# -----------------------

def setup_exception_handlers(app):
    """
    Enregistre les handlers globalaux pour toutes les routes FastAPI.
    À appeler dans `main.py` : setup_exception_handlers(app)
    """
    
    @app.exception_handler(AppError)
    async def handle_app_error(request, exc: AppError):
        # Transforme AppError en réponse HTTP JSON structurée
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "type": exc.__class__.__name__,
                    "message": exc.message,
                    "context": exc.context,
                }
            },
        )
    
    @app.exception_handler(HTTPException)
    async def handle_http_exception(request, exc: HTTPException):
        # Pour les HTTPException natives FastAPI
        logger.warning(f"HTTPException {exc.status_code}: {exc.detail}")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "type": "HTTPException",
                    "message": exc.detail,
                    "context": {},
                }
            },
        )
    
    @app.exception_handler(Exception)
    async def handle_unexpected_error(request, exc: Exception):
        # Dernière ligne de défense : logue et masque les détails au client
        logger.exception("Erreur inattendue non gérée")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "type": "InternalError",
                    "message": "Une erreur technique est survenue.",
                    "context": {"request_id": request.state.request_id},  # si tu as un middleware de correlation
                }
            },
        )