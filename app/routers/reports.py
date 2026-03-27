from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.category import Category
from app.services.reporting import (
    get_monthly_summary, get_spending_by_category, get_monthly_totals,
    get_top_merchants, get_balance_over_time, get_yoy_data, get_category_trends
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/reports", response_class=HTMLResponse)
async def reports_index(request: Request, db: AsyncSession = Depends(get_db)):
    return templates.TemplateResponse("reports.html", {
        "request": request,
        "active_page": "reports",
        "flash_messages": [],
    })


@router.get("/reports/monthly", response_class=HTMLResponse)
async def monthly_report(
    request: Request,
    db: AsyncSession = Depends(get_db),
    year: int | None = None,
    month: int | None = None,
):
    today = date.today()
    year = year or today.year
    month = month or today.month

    summary = await get_monthly_summary(db, year, month)
    by_category = await get_spending_by_category(db, year, month)

    # Previous month
    prev_month = month - 1 or 12
    prev_year = year if month > 1 else year - 1
    prev_summary = await get_monthly_summary(db, prev_year, prev_month)
    prev_by_category = await get_spending_by_category(db, prev_year, prev_month)

    cats_result = await db.execute(select(Category).order_by(Category.name))
    categories = cats_result.scalars().all()

    return templates.TemplateResponse("report_monthly.html", {
        "request": request,
        "active_page": "reports",
        "year": year,
        "month": month,
        "month_name": date(year, month, 1).strftime("%B %Y"),
        "summary": summary,
        "by_category": by_category,
        "prev_summary": prev_summary,
        "prev_by_category": prev_by_category,
        "prev_month_name": date(prev_year, prev_month, 1).strftime("%B %Y"),
        "flash_messages": [],
    })


@router.get("/reports/trends", response_class=HTMLResponse)
async def trends_report(
    request: Request,
    db: AsyncSession = Depends(get_db),
    months: int = 6,
):
    cats_result = await db.execute(
        select(Category).where(Category.is_income == False).order_by(Category.name)
    )
    categories = cats_result.scalars().all()

    return templates.TemplateResponse("report_trends.html", {
        "request": request,
        "active_page": "reports",
        "categories": categories,
        "months": months,
        "flash_messages": [],
    })


@router.get("/reports/income-expenses", response_class=HTMLResponse)
async def income_expenses_report(request: Request, db: AsyncSession = Depends(get_db)):
    monthly = await get_monthly_totals(db, months=12)
    return templates.TemplateResponse("report_income_expenses.html", {
        "request": request,
        "active_page": "reports",
        "monthly": monthly,
        "flash_messages": [],
    })


@router.get("/reports/merchants", response_class=HTMLResponse)
async def merchants_report(
    request: Request,
    db: AsyncSession = Depends(get_db),
    date_from: str = "",
    date_to: str = "",
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

    merchants = await get_top_merchants(db, start, end)
    return templates.TemplateResponse("report_merchants.html", {
        "request": request,
        "active_page": "reports",
        "merchants": merchants,
        "date_from": str(start),
        "date_to": str(end),
        "flash_messages": [],
    })


@router.get("/reports/balance", response_class=HTMLResponse)
async def balance_report(request: Request, db: AsyncSession = Depends(get_db)):
    return templates.TemplateResponse("report_balance.html", {
        "request": request,
        "active_page": "reports",
        "flash_messages": [],
    })


@router.get("/reports/yoy", response_class=HTMLResponse)
async def yoy_report(request: Request, db: AsyncSession = Depends(get_db)):
    yoy_data = await get_yoy_data(db)
    return templates.TemplateResponse("report_yoy.html", {
        "request": request,
        "active_page": "reports",
        "yoy_data": yoy_data,
        "flash_messages": [],
    })
