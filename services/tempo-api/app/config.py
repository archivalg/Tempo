from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration.

    Defaults target local development (SQLite). Production deploys to Oracle
    Autonomous Database per the Integration Spec §17.1 — override DATABASE_URL
    there; no application code changes needed since access goes through SQLAlchemy.
    """

    # PostgreSQL only (ADR-0011). This is the *runtime* URL and must use the
    # non-owner `tempo_app` role so RLS applies; migrations use
    # `database_migration_url` (the `tempo_owner` role). No default password:
    # the URL must come from the environment (.env.example documents it).
    env: str = "local"  # local | test | uat | production
    database_url: str = "postgresql+psycopg://tempo_app@localhost:5439/tempo"
    database_migration_url: str = "postgresql+psycopg://tempo_owner@localhost:5439/tempo"
    # Signs Tempo-issued short-lived access tokens (HS256). Required outside local.
    session_signing_key: str = ""
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 60 * 60 * 12
    session_cookie_secure: bool = True
    # Set to the parent domain (e.g. ".tempo.example") so app.* can read the CSRF cookie set by api.*.
    # Empty = host-only cookies (local development).
    cookie_domain: str = ""
    # OIDC adapter (ADR-0001, production IdP choice still open).
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    # Restricted local identity provider: only honoured when env == "local"/"test".
    dev_idp_enabled: bool = False
    # Username + password sign-in (Argon2id, lockout, TOTP for admins). Refuses plain HTTP outside local/test.
    password_auth_enabled: bool = True
    require_https: bool = True
    login_max_failures: int = 5
    login_ip_limit: int = 120        # sign-in attempts per address per 10 minutes; a warehouse shares one address, so this is not tiny (the per-account limit stays at 10)
    login_lock_minutes: int = 15
    invite_ttl_hours: int = 72
    # Mobile: push provider (disabled | mock | expo) and optional SMS provider (disabled | mock). 'disabled' sends nothing and says so.
    push_provider: str = "disabled"
    # Where links in emails point. SMTP itself is configured by a platform admin in the console (stored encrypted), not here.
    public_app_url: str = "https://tempo.ensemblesolutions.com.au"
    expo_access_token: str = ""      # optional Expo enhanced-security token; never shipped in the app
    sms_provider: str = "disabled"
    jobs_enabled: bool = False       # run the notification job loop inside the API process (single instance, advisory-locked)
    jobs_interval_seconds: int = 30
    kiosk_qr_ttl_seconds: int = 90
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


INSECURE_ACTION_TOKEN_DEFAULT = "dev-insecure-action-token-secret-change-in-production"


def validate_settings(config: Settings) -> None:
    """Fail closed on start: production-like environments reject insecure defaults."""
    if config.env == "production" or config.env == "uat":
        problems = []
        if config.action_token_secret == INSECURE_ACTION_TOKEN_DEFAULT or len(config.action_token_secret) < 32:
            problems.append("TEMPO_ACTION_TOKEN_SECRET must be set to a strong secret")
        if len(config.session_signing_key) < 32:
            problems.append("TEMPO_SESSION_SIGNING_KEY must be set (>=32 chars)")
        if config.dev_idp_enabled:
            problems.append("TEMPO_DEV_IDP_ENABLED must be false")
        if not config.session_cookie_secure:
            problems.append("TEMPO_SESSION_COOKIE_SECURE must be true")
        has_oidc = bool(config.oidc_issuer and config.oidc_audience and config.oidc_jwks_url)
        if not (has_oidc or config.password_auth_enabled):
            problems.append("configure OIDC or enable password sign-in")
        if not config.require_https:
            problems.append("TEMPO_REQUIRE_HTTPS must be true")
        if "*" in config.console_cors_origins:
            problems.append("TEMPO_CONSOLE_CORS_ORIGINS must not be '*'")
        if problems:
            raise RuntimeError("insecure configuration: " + "; ".join(problems))
    if config.dev_idp_enabled and config.env not in ("local", "test"):
        raise RuntimeError("TEMPO_DEV_IDP_ENABLED is only permitted when TEMPO_ENV is local or test")


settings = Settings()
