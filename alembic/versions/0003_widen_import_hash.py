"""widen import_hash to accommodate in-batch duplicate suffix

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'transactions', 'import_hash',
        existing_type=sa.String(length=64),
        type_=sa.String(length=80),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        'transactions', 'import_hash',
        existing_type=sa.String(length=80),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
