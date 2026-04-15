from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.category import Category
from app.models.transaction import Transaction

# Transactions in this category are bookkeeping-only (transfers between the
# user's own accounts) and must not appear in any report aggregation or chart.
TRANSFER_CATEGORY_NAME = "Transfer between accounts"


async def _excluded_category_ids(db: AsyncSession) -> list[int]:
    """Return the ids of categories that must be hidden from all reports."""
    result = await db.execute(
        select(Category.id).where(Category.name == TRANSFER_CATEGORY_NAME)
    )
    return [cid for (cid,) in result.all()]


async def _report_exclusion_filter(db: AsyncSession):
    """Build a WHERE clause that excludes report-hidden categories.

    Uncategorized rows (category_id IS NULL) are kept, which is why we can't
    use a plain `NOT IN` (SQL `NULL NOT IN (...)` is UNKNOWN and would drop
    those rows silently).
    """
    excluded = await _excluded_category_ids(db)
    if not excluded:
        return None
    return or_(
        Transaction.category_id.is_(None),
        Transaction.category_id.notin_(excluded),
    )


async def get_monthly_summary(db: AsyncSession, year: int, month: int) -> dict:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)

    filt = await _report_exclusion_filter(db)
    q = select(
        func.sum(Transaction.amount).filter(Transaction.amount > 0).label('income'),
        func.sum(Transaction.amount).filter(Transaction.amount < 0).label('expenses'),
    ).where(Transaction.date >= start, Transaction.date < end)
    if filt is not None:
        q = q.where(filt)
    result = await db.execute(q)
    row = result.one()
    income = row.income or Decimal('0')
    expenses = abs(row.expenses or Decimal('0'))
    return {
        'income': income,
        'expenses': expenses,
        'net': income - expenses,
    }


async def get_spending_by_category(db: AsyncSession, year: int, month: int) -> list[dict]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)

    result = await db.execute(
        select(
            Category.name,
            Category.color,
            Category.icon,
            func.sum(Transaction.amount).label('total'),
        )
        .join(Transaction, Transaction.category_id == Category.id, isouter=True)
        .where(
            Transaction.date >= start,
            Transaction.date < end,
            Transaction.amount < 0,
            Category.is_income == False,
            Category.name != TRANSFER_CATEGORY_NAME,
        )
        .group_by(Category.id, Category.name, Category.color, Category.icon)
        .order_by(func.sum(Transaction.amount))
    )
    rows = result.all()
    return [
        {
            'name': r.name,
            'color': r.color or '#9E9E9E',
            'icon': r.icon or '❓',
            'total': float(abs(r.total or Decimal('0'))),
        }
        for r in rows
        if r.total
    ]


async def get_daily_spending(db: AsyncSession, year: int, month: int) -> list[dict]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)

    filt = await _report_exclusion_filter(db)
    q = (
        select(
            Transaction.date,
            func.sum(Transaction.amount).label('total'),
        )
        .where(
            Transaction.date >= start,
            Transaction.date < end,
            Transaction.amount < 0,
        )
        .group_by(Transaction.date)
        .order_by(Transaction.date)
    )
    if filt is not None:
        q = q.where(filt)
    result = await db.execute(q)
    rows = result.all()
    return [{'date': str(r.date), 'total': abs(r.total)} for r in rows]


async def get_monthly_totals(db: AsyncSession, months: int = 12) -> list[dict]:
    today = date.today()
    results = []
    for i in range(months - 1, -1, -1):
        month = today.month - i
        year = today.year
        while month <= 0:
            month += 12
            year -= 1
        summary = await get_monthly_summary(db, year, month)
        results.append({
            'year': year,
            'month': month,
            'label': date(year, month, 1).strftime('%b %Y'),
            **summary,
        })
    return results


async def get_top_merchants(db: AsyncSession, start: date, end: date, limit: int = 20) -> list[dict]:
    filt = await _report_exclusion_filter(db)
    q = (
        select(
            Transaction.merchant,
            func.count().label('count'),
            func.sum(Transaction.amount).label('total'),
        )
        .where(
            Transaction.date >= start,
            Transaction.date <= end,
            Transaction.amount < 0,
            Transaction.merchant != None,
            Transaction.merchant != '',
        )
        .group_by(Transaction.merchant)
        .order_by(func.sum(Transaction.amount))
        .limit(limit)
    )
    if filt is not None:
        q = q.where(filt)
    result = await db.execute(q)
    rows = result.all()
    return [
        {'merchant': r.merchant, 'count': r.count, 'total': abs(r.total)}
        for r in rows
    ]


async def get_balance_over_time(db: AsyncSession) -> list[dict]:
    filt = await _report_exclusion_filter(db)
    q = select(Transaction.date, Transaction.amount).order_by(Transaction.date)
    if filt is not None:
        q = q.where(filt)
    result = await db.execute(q)
    rows = result.all()
    running = Decimal('0')
    points = []
    for r in rows:
        running += r.amount
        if points and points[-1]['date'] == str(r.date):
            points[-1]['balance'] = float(running)
        else:
            points.append({'date': str(r.date), 'balance': float(running)})
    return points


async def get_category_trends(
    db: AsyncSession, category_ids: list[int], months: int = 12
) -> list[dict]:
    today = date.today()
    labels = []
    for i in range(months - 1, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        labels.append((y, m, date(y, m, 1).strftime('%b %Y')))

    excluded = set(await _excluded_category_ids(db))
    result_data = {}
    for cat_id in category_ids:
        if cat_id in excluded:
            # Transfer category is hidden from all reports.
            result_data[cat_id] = [0.0] * len(labels)
            continue
        monthly = []
        for y, m, label in labels:
            start = date(y, m, 1)
            end = date(y, m + 1, 1) if m < 12 else date(y + 1, 1, 1)
            r = await db.execute(
                select(func.sum(Transaction.amount).label('total'))
                .where(
                    Transaction.category_id == cat_id,
                    Transaction.date >= start,
                    Transaction.date < end,
                    Transaction.amount < 0,
                )
            )
            total = abs(r.scalar() or Decimal('0'))
            monthly.append(float(total))
        result_data[cat_id] = monthly

    return {
        'labels': [l[2] for l in labels],
        'data': result_data,
    }


async def get_yoy_data(db: AsyncSession) -> dict:
    filt = await _report_exclusion_filter(db)
    q = (
        select(
            extract('year', Transaction.date).label('year'),
            extract('month', Transaction.date).label('month'),
            func.sum(Transaction.amount).filter(Transaction.amount < 0).label('expenses'),
            func.sum(Transaction.amount).filter(Transaction.amount > 0).label('income'),
        )
        .group_by('year', 'month')
        .order_by('year', 'month')
    )
    if filt is not None:
        q = q.where(filt)
    result = await db.execute(q)
    rows = result.all()
    data = {}
    for r in rows:
        year = int(r.year)
        month = int(r.month)
        if year not in data:
            data[year] = {}
        data[year][month] = {
            'expenses': abs(r.expenses or Decimal('0')),
            'income': r.income or Decimal('0'),
        }
    return data
