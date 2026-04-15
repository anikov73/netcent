import math
from datetime import date
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.config import settings
from app.services.reporting import _excluded_category_ids


async def detect_anomalies(db: AsyncSession) -> list[dict]:
    anomalies = []

    excluded = set(await _excluded_category_ids(db))
    q = select(Transaction).order_by(Transaction.date.desc()).limit(500)
    if excluded:
        q = q.where(Transaction.category_id.notin_(excluded) | Transaction.category_id.is_(None))
    result = await db.execute(q)
    transactions = result.scalars().all()

    # Compute per-merchant stats
    merchant_txs: dict[str, list] = {}
    for tx in transactions:
        if tx.merchant:
            merchant_txs.setdefault(tx.merchant, []).append(float(abs(tx.amount)))

    merchant_stats = {}
    for merchant, amounts in merchant_txs.items():
        if len(amounts) < 2:
            continue
        mean = sum(amounts) / len(amounts)
        variance = sum((a - mean) ** 2 for a in amounts) / len(amounts)
        std = math.sqrt(variance)
        merchant_stats[merchant] = {'mean': mean, 'std': std}

    # Compute per-category stats
    cat_txs: dict[int, list] = {}
    for tx in transactions:
        if tx.category_id:
            cat_txs.setdefault(tx.category_id, []).append(float(abs(tx.amount)))

    cat_stats = {}
    for cat_id, amounts in cat_txs.items():
        if len(amounts) < 2:
            continue
        mean = sum(amounts) / len(amounts)
        variance = sum((a - mean) ** 2 for a in amounts) / len(amounts)
        std = math.sqrt(variance)
        cat_stats[cat_id] = {'mean': mean, 'std': std}

    seen_merchants = set(t.merchant for t in transactions if t.merchant)

    # Now check recent transactions (last 30 days or all if few)
    for tx in transactions[:200]:
        reasons = []

        # Large transaction
        if abs(float(tx.amount)) > settings.large_transaction_threshold:
            reasons.append(f"Large transaction: {abs(float(tx.amount)):.2f} {tx.currency}")

        # Unusual amount for merchant
        if tx.merchant and tx.merchant in merchant_stats:
            stats = merchant_stats[tx.merchant]
            if stats['std'] > 0:
                z = abs(abs(float(tx.amount)) - stats['mean']) / stats['std']
                if z > 2:
                    reasons.append(f"Unusual amount for {tx.merchant} (z={z:.1f})")

        # Unusual amount for category
        if tx.category_id and tx.category_id in cat_stats:
            stats = cat_stats[tx.category_id]
            if stats['std'] > 0:
                z = abs(abs(float(tx.amount)) - stats['mean']) / stats['std']
                if z > 2 and not reasons:
                    reasons.append(f"Unusual amount for category (z={z:.1f})")

        if reasons:
            anomalies.append({
                'transaction_id': tx.id,
                'date': tx.date,
                'description': tx.description_clean or tx.description,
                'amount': tx.amount,
                'currency': tx.currency,
                'reasons': reasons,
            })

    return anomalies
