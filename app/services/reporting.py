from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select, func, extract
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.transaction import Transaction
from app.models.category import Category


async def get_monthly_summary(db: AsyncSession, year: int, month: int) -> dict:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)

    result = await db.execute(
        select(
            func.sum(Transaction.amount).filter(Transaction.amount > 0).label('income'),
            func.sum(Transaction.amount).filter(Transaction.amount < 0).label('expenses'),
        ).where(Transaction.date >= start, Transaction.date < end)
    )
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
            'total': abs(r.total or Decimal('0')),
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

    result = await db.execute(
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
    result = await db.execute(
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
    rows = result.all()
    return [
        {'merchant': r.merchant, 'count': r.count, 'total': abs(r.total)}
        for r in rows
    ]


async def get_balance_over_time(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Transaction.date, Transaction.amount)
        .order_by(Transaction.date)
    )
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

    result_data = {}
    for cat_id in category_ids:
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
    result = await db.execute(
        select(
            extract('year', Transaction.date).label('year'),
            extract('month', Transaction.date).label('month'),
            func.sum(Transaction.amount).filter(Transaction.amount < 0).label('expenses'),
            func.sum(Transaction.amount).filter(Transaction.amount > 0).label('income'),
        )
        .group_by('year', 'month')
        .order_by('year', 'month')
    )
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
