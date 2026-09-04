from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration.

    Defaults target local development (SQLite). Production deploys to Oracle
    Autonomous Database per the Integration Spec §17.1 — override DATABASE_URL
    there; no application code changes needed since access goes through SQLAlchemy.
    """

    database_url: str = "sqlite:///./tempo_dev.db"
    service_name: str = "tempo-optimisation-service"
    api_base_path: str = "/v1"
    confidence_method: str = "tempo-confidence-1.0"

    model_config = {"env_prefix": "TEMPO_"}


settings = Settings()
