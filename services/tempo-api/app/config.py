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
    # Signs Phase E's action_token (app/core/action_tokens.py). Same class of
    # Phase 0 stand-in as X-Tempo-Context: a real deployment must override
    # this via TEMPO_ACTION_TOKEN_SECRET — a fixed default is not a security
    # control and must not reach production (tracked alongside OD-01).
    action_token_secret: str = "dev-insecure-action-token-secret-change-in-production"
    # services/tempo-console's dev server origin(s), comma-separated. A
    # real deployment should set this to the console's actual origin(s) —
    # "*" is a local-dev convenience, not a security posture.
    console_cors_origins: str = "http://localhost:5173"

    model_config = {"env_prefix": "TEMPO_"}


settings = Settings()
