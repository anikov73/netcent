from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.transaction import Transaction
from app.models.category import Category
from app.models.subscription import Subscription
from app.services.reporting import get_monthly_summary, get_spending_by_category, get_daily_spending
from app.services.anomaly_detector import detect_anomalies

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    today = date.today()
    year, month = today.year, today.month

    summary = await get_monthly_summary(db, year, month)
    by_category = await get_spending_by_category(db, year, month)
    daily = await get_daily_spending(db, year, month)
    anomalies = await detect_anomalies(db)

    # Recent transactions
    result = await db.execute(
        select(Transaction)
        .options(selectinload(Transaction.category))
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .limit(10)
    )
    recent = result.scalars().all()

    # Uncategorized count
    uncat_result = await db.execute(
        select(func.count(Transaction.id)).where(Transaction.category_id == None)
    )
    uncategorized_count = uncat_result.scalar()

    # Active subscriptions
    sub_result = await db.execute(
        select(Subscription).where(Subscription.is_active == True)
        .order_by(Subscription.next_expected)
    )
    subscriptions = sub_result.scalars().all()

    # Overdue subscriptions
    overdue = [s for s in subscriptions if s.next_expected and s.next_expected < today]

    msg = request.query_params.get("msg", "")
    msg_type = request.query_params.get("type", "info")

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active_page": "dashboard",
        "summary": summary,
        "by_category": by_category,
        "daily_spending": daily,
        "recent_transactions": recent,
        "uncategorized_count": uncategorized_count,
        "subscriptions": subscriptions,
        "overdue_subscriptions": overdue,
        "anomalies": anomalies,
        "current_month": today.strftime("%B %Y"),
        "flash_messages": [{"message": msg, "type": msg_type}] if msg else [],
    })
