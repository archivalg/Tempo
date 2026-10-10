"""Per-run commitment ledger (order_commitment) — makes one committed run's contribution to an
order's committed_units separately releasable, so cancelling or replacing a committed plan can make
its unfinished work available again without touching any other run's commitment or actual completion.

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None

TENANT = "tenant_id = current_setting('app.tenant_id', true)"


def upgrade() -> None:
    op.create_table("order_commitment",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("order_id", sa.String(), sa.ForeignKey("order_.id"), nullable=False, index=True),
        sa.Column("run_id", sa.String(), nullable=False, index=True),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True))
    op.execute('ALTER TABLE "order_commitment" ENABLE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY tempo_tenant_isolation ON "order_commitment" FOR ALL TO tempo_app USING ({TENANT}) WITH CHECK ({TENANT})')


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tempo_tenant_isolation ON "order_commitment"')
    op.drop_table("order_commitment")
