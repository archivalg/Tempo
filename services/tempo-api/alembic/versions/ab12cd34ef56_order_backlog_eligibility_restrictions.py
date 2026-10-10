"""Arch acceptance completion pass 2: open-order backlog (order_.fulfilled_units), and an explicit,
configurable award/agreement eligibility-restriction table distinct from skill/certification
eligibility (brief: "do not infer restrictions from an award name").

Revision ID: ab12cd34ef56
Revises: f7a8b9c0d1e2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ab12cd34ef56"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None

TENANT = "tenant_id = current_setting('app.tenant_id', true)"


def _tenant_rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY tempo_tenant_isolation ON "{table}" FOR ALL TO tempo_app USING ({TENANT}) WITH CHECK ({TENANT})')


def upgrade() -> None:
    op.add_column("order_", sa.Column("fulfilled_units", sa.Float(), nullable=False, server_default="0"))
    op.add_column("work_standard", sa.Column("required_skill", sa.String(), nullable=True))

    op.create_table("award_eligibility_restriction",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("award_code", sa.String(), nullable=False), sa.Column("activity", sa.String(), nullable=False),
        sa.UniqueConstraint("tenant_id", "award_code", "activity", name="uq_award_eligibility_restriction"))
    _tenant_rls("award_eligibility_restriction")


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tempo_tenant_isolation ON "award_eligibility_restriction"')
    op.drop_table("award_eligibility_restriction")
    op.drop_column("work_standard", "required_skill")
    op.drop_column("order_", "fulfilled_units")
