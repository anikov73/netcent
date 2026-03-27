"""initial

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('icon', sa.String(50), nullable=True),
        sa.Column('color', sa.String(7), nullable=True),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('is_income', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['parent_id'], ['categories.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table(
        'import_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('imported_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.Column('total_rows', sa.Integer(), nullable=True),
        sa.Column('new_rows', sa.Integer(), nullable=True),
        sa.Column('duplicate_rows', sa.Integer(), nullable=True),
        sa.Column('error_rows', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(20), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('value_date', sa.Date(), nullable=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('description_clean', sa.Text(), nullable=True),
        sa.Column('amount', sa.DECIMAL(12, 2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='MKD'),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('is_manually_categorized', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('merchant', sa.String(255), nullable=True),
        sa.Column('import_hash', sa.String(64), nullable=False),
        sa.Column('import_log_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['import_log_id'], ['import_logs.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('import_hash'),
    )

    op.create_table(
        'categorization_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pattern', sa.String(255), nullable=False),
        sa.Column('match_type', sa.String(20), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('merchant', sa.String(255), nullable=True),
        sa.Column('expected_amount', sa.DECIMAL(12, 2), nullable=True),
        sa.Column('currency', sa.String(3), nullable=False, server_default='MKD'),
        sa.Column('frequency', sa.String(20), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_seen', sa.Date(), nullable=True),
        sa.Column('next_expected', sa.Date(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Seed default categories
    op.execute("""
        INSERT INTO categories (name, icon, color, is_income, sort_order) VALUES
        ('Food & Groceries', '🛒', '#4CAF50', false, 1),
        ('Rent / Housing', '🏠', '#2196F3', false, 2),
        ('Transport', '🚗', '#FF9800', false, 3),
        ('Subscriptions / Recurring', '🔄', '#9C27B0', false, 4),
        ('Entertainment', '🎬', '#E91E63', false, 5),
        ('Health / Insurance', '❤️', '#F44336', false, 6),
        ('Shopping', '🛍️', '#00BCD4', false, 7),
        ('Travel', '✈️', '#3F51B5', false, 8),
        ('Utilities / Bills', '⚡', '#FF5722', false, 9),
        ('Income / Salary', '💰', '#8BC34A', true, 10),
        ('Uncategorized', '❓', '#9E9E9E', false, 99)
    """)

    # Seed default categorization rules
    op.execute("""
        INSERT INTO categorization_rules (pattern, match_type, category_id, priority, is_active)
        SELECT pattern, match_type, c.id, priority, true
        FROM (VALUES
            ('migros|coop|aldi|lidl|denner|spar', 'regex', 'Food & Groceries', 10),
            ('sbb|zvv|uber|taxi|parking|benzin|fuel', 'regex', 'Transport', 10),
            ('netflix|spotify|disney|apple.com|google storage', 'regex', 'Subscriptions / Recurring', 10),
            ('rent|miete|wohnung', 'regex', 'Rent / Housing', 10),
            ('swisscom|sunrise|salt|elektr|strom', 'regex', 'Utilities / Bills', 10),
            ('doctor|arzt|apotheke|pharmacy|css|swica', 'regex', 'Health / Insurance', 10),
            ('zalando|amazon|digitec|galaxus', 'regex', 'Shopping', 10),
            ('hotel|airbnb|booking|flight|flug', 'regex', 'Travel', 10),
            ('kino|cinema|restaurant|bar|cafe', 'regex', 'Entertainment', 10),
            ('salary|lohn|gehalt', 'regex', 'Income / Salary', 10)
        ) AS rules(pattern, match_type, cat_name, priority)
        JOIN categories c ON c.name = rules.cat_name
    """)


def downgrade() -> None:
    op.drop_table('subscriptions')
    op.drop_table('categorization_rules')
    op.drop_table('transactions')
    op.drop_table('import_logs')
    op.drop_table('categories')
