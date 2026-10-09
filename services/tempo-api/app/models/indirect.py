"""Fixed indirect headcount coverage (order-driven-planning Stage 2/5 integration). See
docs/order-driven-planning.md.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class IndirectHeadcountRequirement(Base):
    """A fixed headcount required for one role at a site/weekday/time window, independent of
    direct-work volume (brief: "including zero-volume days"). `role` is matched against a worker's
    SkillCertification.skill_code, the same convention the rest of Tempo uses for role matching."""

    __tablename__ = "indirect_headcount_requirement"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)
    weekday: Mapped[str] = mapped_column(String)
    start_time: Mapped[str] = mapped_column(String)  # "HH:MM" local wall-clock
    end_time: Mapped[str] = mapped_column(String)
    headcount: Mapped[int] = mapped_column(Integer)
