"""add accounts

Revision ID: 0002
Revises: 0001
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('currency', sa.String(3), nullable=False, server_default='MKD'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.add_column(
        'transactions',
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('accounts.id', ondelete='SET NULL'), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('transactions', 'account_id')
    op.drop_table('accounts')
