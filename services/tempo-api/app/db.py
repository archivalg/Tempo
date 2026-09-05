from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    # Phase 0 uses SQLAlchemy's own migration-free create_all against SQLite/dev
    # Postgres/Oracle. Real environments should switch to Alembic migrations
    # before Phase A ingests real tenant data (see docs/roadmap.md).
    import app.models.canonical  # noqa: F401
    import app.models.connectors  # noqa: F401
    import app.models.runs  # noqa: F401

    Base.metadata.create_all(bind=engine)
