import os
from functools import lru_cache
from typing import List, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings and configuration for Prior Authorization AI Agent.
    Reads from environment variables and .env file.
    """
    
    # Application Configuration
    ENVIRONMENT: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)

    # Security
    # Never hardcode SECRET_KEY with a default value. Always read from environment.
    SECRET_KEY: str = Field(
        default_factory=lambda: os.environ.get("SECRET_KEY", os.urandom(32).hex())
    )
    CORS_ORIGINS: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:8000"]
    )

    # Database Configuration (PostgreSQL + asyncpg + pgvector)
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/prior_auth_pro"
    )

    # Redis Configuration (for ARQ task queue and WebSocket pub/sub)
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # FHIR Server Configuration
    FHIR_BASE_URL: str = Field(default="https://hapi.fhir.org/baseR4")
    FHIR_AUTH_TOKEN: Optional[str] = Field(default=None)

    # AI / LLM Configuration (Google Gemini)
    GEMINI_API_KEY: str = Field(default="")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        """
        Ensure critical security settings are explicitly provided in production.
        Fails loudly if SECRET_KEY is missing in the environment.
        
        Returns:
            Settings: The validated settings instance.
            
        Raises:
            ValueError: If required production settings are missing or insecure.
        """
        if self.ENVIRONMENT.lower() == "production":
            if not os.environ.get("SECRET_KEY"):
                raise ValueError("SECRET_KEY environment variable MUST be explicitly set in production.")
            if not self.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY environment variable MUST be set in production.")
            if "*" in self.CORS_ORIGINS:
                raise ValueError("CORS_ORIGINS cannot contain '*' in production environments.")
        return self


@lru_cache()
def get_settings() -> Settings:
    """
    Retrieve cached application settings.
    Uses lru_cache to ensure the settings are only loaded and validated once.
    
    Returns:
        Settings: The application settings instance.
    """
    return Settings()