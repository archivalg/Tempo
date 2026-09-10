from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration.

    Defaults target local development (SQLite). Production deploys to Oracle
    Autonomous Database per the Integration Spec §17.1 — override DATABASE_URL
    there; no application code changes needed since access goes through SQLAlchemy.
    """

    database_url: str = "sqlite:///./tempo_dev.db"
    # DAT-04: pooling/retry/timeout, applied by app/db.py only for a real
    # (non-SQLite) database — SQLite's default poolclass (NullPool)
    # doesn't accept pool_size/max_overflow at all, so these are inert
    # until a real environment (ADR-0002) exists to tune them against.
    # The defaults below are sane starting points, not validated against
    # any real concurrency target — DAT-04's own acceptance criterion
    # ("load and failure tests") is what actually calibrates them.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1800
    db_pool_pre_ping: bool = True
    # Oracle has no universal driver-agnostic "statement_timeout" the way
    # Postgres does; this is stored now so a real environment's connection
    # setup has somewhere to read it from, but nothing applies it yet —
    # doing so correctly depends on which Oracle driver is chosen
    # (ADR-0002), unverified here.
    db_statement_timeout_ms: int = 30_000
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
