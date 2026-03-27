"""JSON API endpoints for chart data."""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.category import Category
from app.services.reporting import (
    get_spending_by_category, get_daily_spending, get_monthly_totals,
    get_top_merchants, get_balance_over_time, get_category_trends, get_yoy_data
)
from app.services.anomaly_detector import detect_anomalies

router = APIRouter(prefix="/api")


@router.get("/dashboard/summary")
async def dashboard_summary(
    year: int | None = None,
    month: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    year = year or today.year
    month = month or today.month
    from app.services.reporting import get_monthly_summary
    summary = await get_monthly_summary(db, year, month)
    return {k: float(v) for k, v in summary.items()}


@router.get("/dashboard/spending-by-category")
async def spending_by_category_api(
    year: int | None = None,
    month: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    year = year or today.year
    month = month or today.month
    data = await get_spending_by_category(db, year, month)
    return {
        "labels": [d['name'] for d in data],
        "values": [float(d['total']) for d in data],
        "colors": [d['color'] for d in data],
    }


@router.get("/dashboard/daily-spending")
async def daily_spending_api(
    year: int | None = None,
    month: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    year = year or today.year
    month = month or today.month
    data = await get_daily_spending(db, year, month)
    return {
        "labels": [d['date'] for d in data],
        "values": [float(d['total']) for d in data],
    }


@router.get("/reports/monthly-totals")
async def monthly_totals_api(months: int = 12, db: AsyncSession = Depends(get_db)):
    data = await get_monthly_totals(db, months)
    return {
        "labels": [d['label'] for d in data],
        "income": [float(d['income']) for d in data],
        "expenses": [float(d['expenses']) for d in data],
        "net": [float(d['net']) for d in data],
    }


@router.get("/reports/top-merchants")
async def top_merchants_api(
    date_from: str = "",
    date_to: str = "",
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    start = date(today.year, 1, 1)
    end = today
    if date_from:
        try:
            start = date.fromisoformat(date_from)
        except ValueError:
            pass
    if date_to:
        try:
            end = date.fromisoformat(date_to)
        except ValueError:
            pass
    data = await get_top_merchants(db, start, end)
    return {
        "labels": [d['merchant'] for d in data],
        "values": [float(d['total']) for d in data],
        "counts": [d['count'] for d in data],
    }


@router.get("/reports/balance-over-time")
async def balance_over_time_api(db: AsyncSession = Depends(get_db)):
    data = await get_balance_over_time(db)
    return {
        "labels": [d['date'] for d in data],
        "values": [d['balance'] for d in data],
    }


@router.get("/reports/category-trends")
async def category_trends_api(
    category_ids: str = "",
    months: int = 6,
    db: AsyncSession = Depends(get_db),
):
    ids = []
    if category_ids:
        try:
            ids = [int(x) for x in category_ids.split(',') if x.strip()]
        except ValueError:
            pass

    if not ids:
        cats_result = await db.execute(
            select(Category).where(Category.is_income == False).limit(5)
        )
        ids = [c.id for c in cats_result.scalars().all()]

    data = await get_category_trends(db, ids, months)
    cats_result = await db.execute(select(Category).where(Category.id.in_(ids)))
    cats = {c.id: c for c in cats_result.scalars().all()}

    datasets = []
    for cat_id, values in data.get('data', {}).items():
        cat = cats.get(cat_id)
        datasets.append({
            "label": cat.name if cat else str(cat_id),
            "color": cat.color if cat else '#9E9E9E',
            "data": values,
        })

    return {
        "labels": data.get('labels', []),
        "datasets": datasets,
    }


@router.get("/reports/yoy")
async def yoy_api(db: AsyncSession = Depends(get_db)):
    data = await get_yoy_data(db)
    months = list(range(1, 13))
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    years = sorted(data.keys())
    datasets = []
    colors = ['#3b82f6', '#ef4444', '#22c55e', '#f59e0b', '#8b5cf6']
    for i, year in enumerate(years):
        expenses = [float(data[year].get(m, {}).get('expenses', 0)) for m in months]
        datasets.append({
            "label": str(year),
            "color": colors[i % len(colors)],
            "data": expenses,
        })
    return {"labels": month_names, "datasets": datasets}


@router.get("/categories")
async def categories_api(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Category).order_by(Category.sort_order, Category.name))
    cats = result.scalars().all()
    return [{"id": c.id, "name": c.name, "icon": c.icon or "", "color": c.color or "#9E9E9E"} for c in cats]


@router.patch("/transactions/{tx_id}")
async def update_transaction_api(tx_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    from app.models.transaction import Transaction
    result = await db.execute(select(Transaction).where(Transaction.id == tx_id))
    tx = result.scalar_one_or_none()
    if not tx:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Transaction not found")

    if "description_clean" in data:
        tx.description_clean = data["description_clean"] or None
    if "merchant" in data:
        tx.merchant = data["merchant"] or None
    if "amount" in data:
        from decimal import Decimal
        tx.amount = Decimal(str(data["amount"]))
    if "currency" in data:
        tx.currency = data["currency"] or tx.currency
    if "category_id" in data:
        tx.category_id = data["category_id"]  # None clears it
        if data["category_id"] is not None:
            tx.is_manually_categorized = True

    await db.commit()
    await db.refresh(tx)

    # Load category for response
    cat = None
    if tx.category_id:
        cat_result = await db.execute(select(Category).where(Category.id == tx.category_id))
        cat = cat_result.scalar_one_or_none()

    return {
        "id": tx.id,
        "date": str(tx.date),
        "description": tx.description,
        "description_clean": tx.description_clean,
        "merchant": tx.merchant,
        "amount": float(tx.amount),
        "currency": tx.currency,
        "category_id": tx.category_id,
        "category_name": cat.name if cat else None,
        "category_color": cat.color if cat else None,
        "category_icon": cat.icon if cat else None,
    }


@router.get("/anomalies")
async def anomalies_api(db: AsyncSession = Depends(get_db)):
    data = await detect_anomalies(db)
    return [
        {
            **d,
            'date': str(d['date']),
            'amount': float(d['amount']),
        }
        for d in data
    ]
