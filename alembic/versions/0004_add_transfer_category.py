"""add Transfer between accounts category

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Excluded from all report aggregations. Sits before "Uncategorized" in
    # sort order.
    op.execute("""
        INSERT INTO categories (name, icon, color, is_income, sort_order)
        VALUES ('Transfer between accounts', '🔁', '#607D8B', false, 50)
        ON CONFLICT (name) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM categories WHERE name = 'Transfer between accounts'")
