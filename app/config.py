"""
Configuration settings for the Emploi Dakar backend.
"""

import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application settings."""

    # =========================
    # Database
    # =========================
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL"    )

    # =========================
    # API Configuration
    # =========================
    FRONTEND_URL: str = os.getenv(
        "FRONTEND_URL",
        "https://www.sunu-souba.com"
    )

    API_SECRET_KEY: str = os.getenv(
        "API_SECRET_KEY",
        "your-secret-key-here"
    )

    API_ALGORITHM: str = os.getenv(
        "API_ALGORITHM",
        "HS256"
    )

    API_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv(
            "API_ACCESS_TOKEN_EXPIRE_MINUTES",
            "30"
        )
    )

    # =========================
    # MLflow Configuration
    # =========================
    MLFLOW_TRACKING_URI: str = os.getenv(
        "MLFLOW_TRACKING_URI",
        "http://localhost:5000"
    )

    # =========================
    # Email Configuration
    # =========================
    SMTP_SERVER: str = os.getenv(
        "SMTP_SERVER",
        "smtp.gmail.com"
    )

    SMTP_PORT: int = int(
        os.getenv(
            "SMTP_PORT",
            "587"
        )
    )

    EMAIL_USER: Optional[str] = os.getenv(
        "EMAIL_USER"
    )

    EMAIL_PASSWORD: Optional[str] = os.getenv(
        "EMAIL_PASSWORD"
    )

    # Alias de configuration pour la compatibilité avec notification_service
    SMTP_HOST: str = os.getenv("SMTP_HOST") or os.getenv("SMTP_SERVER", "smtp.gmail.com")
    SMTP_USER: Optional[str] = os.getenv("SMTP_USER") or os.getenv("EMAIL_USER")
    SMTP_PASSWORD: Optional[str] = os.getenv("SMTP_PASSWORD") or os.getenv("EMAIL_PASSWORD")

    # =========================
    # External API Keys
    # =========================
    OPENAI_API_KEY: Optional[str] = os.getenv(
        "OPENAI_API_KEY"
    )

    RESEND_API_KEY: Optional[str] = os.getenv(
        "RESEND_API_KEY"
    )

    XAI_API_KEY: Optional[str] = os.getenv(
        "XAI_API_KEY"
    )

    XAI_MODEL: str = os.getenv(
        "XAI_MODEL",
        "grok-beta"
    )

    XAI_BASE_URL: str = os.getenv(
        "XAI_BASE_URL",
        "https://api.x.ai/v1"
    )

    HUGGINGFACE_API_TOKEN: Optional[str] = os.getenv(
        "HUGGINGFACE_API_TOKEN"
    )

    # =========================
    # Cloudinary Configuration
    # =========================
    CLOUDINARY_URL: str = os.getenv(
        "CLOUDINARY_URL",
        ""
    )

    CLOUDINARY_FOLDER: str = os.getenv(
        "CLOUDINARY_FOLDER",
        "emploi-dakar"
    )

    # =========================
    # File Upload Configuration
    # =========================
    UPLOAD_DIR: str = os.getenv(
        "UPLOAD_DIR",
        "uploads"
    )

    MAX_FILE_SIZE: int = int(
        os.getenv(
            "MAX_FILE_SIZE",
            "10485760"
        )
    )  # 10 MB

    ALLOWED_EXTENSIONS: set = {
        ".pdf",
        ".doc",
        ".docx",
        ".txt"
    }

    # =========================
    # Application Settings
    # =========================
    DEBUG: bool = os.getenv(
        "DEBUG",
        "False"
    ).lower() == "true"

    ENVIRONMENT: str = os.getenv(
        "ENVIRONMENT",
        "development"
    )

    # =========================
    # Pagination Settings
    # =========================
    DEFAULT_PAGE_SIZE: int = int(
        os.getenv(
            "DEFAULT_PAGE_SIZE",
            "20"
        )
    )

    MAX_PAGE_SIZE: int = int(
        os.getenv(
            "MAX_PAGE_SIZE",
            "100"
        )
    )

    # =========================
    # Cache Settings
    # =========================
    CACHE_TTL: int = int(
        os.getenv(
            "CACHE_TTL",
            "300"
        )
    )  # 5 minutes

    # =========================
    # Security Settings
    # =========================
    CORS_ORIGINS: list = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:5173"
    ).split(",")

    GOOGLE_CLIENT_ID: Optional[str] = os.getenv("GOOGLE_CLIENT_ID", "710490506642-hj5t7v8m6nchogg4n7nmpdech51f6cfh.apps.googleusercontent.com")

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


# Global settings instance
settings = Settings()