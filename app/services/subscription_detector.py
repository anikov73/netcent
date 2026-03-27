from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.models.subscription import Subscription


FREQ_TOLERANCES = {
    'weekly': 7,
    'monthly': 3,
    'quarterly': 7,
    'yearly': 14,
}

FREQ_DAYS = {
    'weekly': 7,
    'monthly': 30,
    'quarterly': 91,
    'yearly': 365,
}


def detect_frequency(intervals: list[float]) -> str | None:
    if not intervals:
        return None
    avg = sum(intervals) / len(intervals)
    if 5 <= avg <= 9:
        return 'weekly'
    elif 25 <= avg <= 35:
        return 'monthly'
    elif 85 <= avg <= 97:
        return 'quarterly'
    elif 355 <= avg <= 375:
        return 'yearly'
    return None


async def detect_subscriptions(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Transaction.merchant, Transaction.amount, Transaction.date)
        .where(
            Transaction.amount < 0,
            Transaction.merchant != None,
            Transaction.merchant != '',
        )
        .order_by(Transaction.merchant, Transaction.date)
    )
    rows = result.all()

    # Group by merchant
    from collections import defaultdict
    merchant_txs: dict[str, list] = defaultdict(list)
    for r in rows:
        merchant_txs[r.merchant].append({'amount': r.amount, 'date': r.date})

    suggestions = []
    for merchant, txs in merchant_txs.items():
        if len(txs) < 3:
            continue

        # Check if amounts are similar (within 10%)
        amounts = [abs(tx['amount']) for tx in txs]
        avg_amount = sum(amounts) / len(amounts)
        if any(abs(a - avg_amount) / avg_amount > 0.1 for a in amounts):
            continue

        # Check intervals
        dates = sorted(tx['date'] for tx in txs)
        intervals = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
        freq = detect_frequency(intervals)
        if not freq:
            continue

        # Check tolerance
        tolerance = FREQ_TOLERANCES[freq]
        expected = FREQ_DAYS[freq]
        if any(abs(iv - expected) > tolerance for iv in intervals):
            continue

        suggestions.append({
            'merchant': merchant,
            'expected_amount': avg_amount,
            'frequency': freq,
            'last_seen': dates[-1],
            'occurrences': len(txs),
        })

    return suggestions


async def update_subscription_status(db: AsyncSession) -> None:
    today = date.today()
    result = await db.execute(
        select(Subscription).where(Subscription.is_active == True)
    )
    subscriptions = result.scalars().all()

    for sub in subscriptions:
        if sub.last_seen:
            days = FREQ_DAYS.get(sub.frequency, 30)
            sub.next_expected = sub.last_seen + timedelta(days=days)

    await db.commit()


async def match_subscription_transactions(db: AsyncSession) -> None:
    """Update last_seen for subscriptions based on transactions."""
    today = date.today()
    result = await db.execute(
        select(Subscription).where(Subscription.is_active == True)
    )
    subscriptions = result.scalars().all()

    for sub in subscriptions:
        if not sub.merchant:
            continue
        tx_result = await db.execute(
            select(Transaction)
            .where(
                Transaction.merchant.ilike(f'%{sub.merchant}%'),
                Transaction.amount < 0,
            )
            .order_by(Transaction.date.desc())
            .limit(1)
        )
        tx = tx_result.scalar_one_or_none()
        if tx:
            sub.last_seen = tx.date
            days = FREQ_DAYS.get(sub.frequency, 30)
            sub.next_expected = tx.date + timedelta(days=days)

    await db.commit()
