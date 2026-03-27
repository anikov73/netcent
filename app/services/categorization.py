import re
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.categorization_rule import CategorizationRule
from app.models.transaction import Transaction


def matches_rule(text: str, pattern: str, match_type: str) -> bool:
    text_lower = text.lower()
    pattern_lower = pattern.lower()
    try:
        if match_type == 'contains':
            return pattern_lower in text_lower
        elif match_type == 'starts_with':
            return text_lower.startswith(pattern_lower)
        elif match_type == 'exact':
            return text_lower == pattern_lower
        elif match_type == 'regex':
            return bool(re.search(pattern_lower, text_lower))
    except Exception:
        return False
    return False


async def get_active_rules(db: AsyncSession) -> list[CategorizationRule]:
    result = await db.execute(
        select(CategorizationRule)
        .where(CategorizationRule.is_active == True)
        .order_by(CategorizationRule.priority.desc())
    )
    return result.scalars().all()


async def categorize_transaction(
    tx: Transaction,
    rules: list[CategorizationRule],
) -> int | None:
    text = tx.description_clean or tx.description or ''
    for rule in rules:
        if matches_rule(text, rule.pattern, rule.match_type):
            return rule.category_id
    return None


async def auto_categorize_transactions(
    db: AsyncSession,
    transaction_ids: list[int] | None = None,
    force: bool = False,
) -> int:
    """Auto-categorize transactions. If transaction_ids given, only those; else all uncategorized."""
    rules = await get_active_rules(db)
    if not rules:
        return 0

    query = select(Transaction)
    if transaction_ids:
        query = query.where(Transaction.id.in_(transaction_ids))
    if not force:
        query = query.where(Transaction.is_manually_categorized == False)

    result = await db.execute(query)
    transactions = result.scalars().all()

    count = 0
    for tx in transactions:
        cat_id = await categorize_transaction(tx, rules)
        if cat_id and (not tx.category_id or not tx.is_manually_categorized):
            tx.category_id = cat_id
            count += 1

    await db.commit()
    return count


async def test_rule(
    db: AsyncSession,
    pattern: str,
    match_type: str,
    limit: int = 20,
) -> list[Transaction]:
    result = await db.execute(select(Transaction).limit(1000))
    all_txs = result.scalars().all()
    matching = [tx for tx in all_txs if matches_rule(
        tx.description_clean or tx.description or '', pattern, match_type
    )]
    return matching[:limit]
