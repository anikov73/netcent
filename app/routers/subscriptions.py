from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.subscription import Subscription
from app.models.category import Category
from app.services.subscription_detector import detect_subscriptions, update_subscription_status

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/subscriptions", response_class=HTMLResponse)
async def subscriptions_list(request: Request, db: AsyncSession = Depends(get_db)):
    await update_subscription_status(db)

    result = await db.execute(
        select(Subscription)
        .options(selectinload(Subscription.category))
        .order_by(Subscription.is_active.desc(), Subscription.next_expected)
    )
    subscriptions = result.scalars().all()

    today = date.today()
    overdue = [s for s in subscriptions if s.is_active and s.next_expected and s.next_expected < today]

    cats_result = await db.execute(select(Category).order_by(Category.name))
    categories = cats_result.scalars().all()

    # Monthly cost total
    monthly_cost = sum(
        float(s.expected_amount or 0) * {
            'weekly': 4.33,
            'monthly': 1,
            'quarterly': 1/3,
            'yearly': 1/12,
        }.get(s.frequency, 1)
        for s in subscriptions
        if s.is_active and s.expected_amount
    )

    msg = request.query_params.get("msg", "")
    msg_type = request.query_params.get("type", "info")

    return templates.TemplateResponse("subscriptions.html", {
        "request": request,
        "active_page": "subscriptions",
        "subscriptions": subscriptions,
        "overdue": overdue,
        "categories": categories,
        "monthly_cost": monthly_cost,
        "yearly_cost": monthly_cost * 12,
        "flash_messages": [{"message": msg, "type": msg_type}] if msg else [],
    })


@router.post("/subscriptions/detect")
async def run_detection(db: AsyncSession = Depends(get_db)):
    suggestions = await detect_subscriptions(db)
    # Add suggestions that don't already exist
    existing_result = await db.execute(select(Subscription.merchant))
    existing_merchants = {r[0] for r in existing_result.all() if r[0]}

    added = 0
    for sug in suggestions:
        if sug['merchant'] not in existing_merchants:
            # Find subscriptions category
            cat_result = await db.execute(
                select(Category).where(Category.name == 'Subscriptions / Recurring')
            )
            cat = cat_result.scalar_one_or_none()
            sub = Subscription(
                name=sug['merchant'],
                merchant=sug['merchant'],
                expected_amount=sug['expected_amount'],
                frequency=sug['frequency'],
                category_id=cat.id if cat else None,
                last_seen=sug['last_seen'],
                is_active=True,
            )
            db.add(sub)
            added += 1

    await db.commit()
    return RedirectResponse(
        f"/subscriptions?msg={added}+subscriptions+detected&type=success", status_code=303
    )


@router.post("/subscriptions/create")
async def create_subscription(
    name: str = Form(...),
    merchant: str = Form(default=""),
    expected_amount: str = Form(default=""),
    currency: str = Form(default="MKD"),
    frequency: str = Form(...),
    category_id: str = Form(default=""),
    notes: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    from decimal import Decimal
    sub = Subscription(
        name=name,
        merchant=merchant or None,
        expected_amount=Decimal(expected_amount) if expected_amount else None,
        currency=currency,
        frequency=frequency,
        category_id=int(category_id) if category_id else None,
        notes=notes or None,
        is_active=True,
    )
    db.add(sub)
    await db.commit()
    return RedirectResponse("/subscriptions?msg=Subscription+created&type=success", status_code=303)


@router.post("/subscriptions/{sub_id}/edit")
async def edit_subscription(
    sub_id: int,
    name: str = Form(...),
    merchant: str = Form(default=""),
    expected_amount: str = Form(default=""),
    currency: str = Form(default="MKD"),
    frequency: str = Form(...),
    category_id: str = Form(default=""),
    notes: str = Form(default=""),
    is_active: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    from decimal import Decimal
    result = await db.execute(select(Subscription).where(Subscription.id == sub_id))
    sub = result.scalar_one_or_none()
    if not sub:
        return RedirectResponse("/subscriptions?msg=Not+found&type=error", status_code=303)

    sub.name = name
    sub.merchant = merchant or None
    sub.expected_amount = Decimal(expected_amount) if expected_amount else None
    sub.currency = currency
    sub.frequency = frequency
    sub.category_id = int(category_id) if category_id else None
    sub.notes = notes or None
    sub.is_active = bool(is_active)
    await db.commit()
    return RedirectResponse("/subscriptions?msg=Subscription+updated&type=success", status_code=303)


@router.post("/subscriptions/{sub_id}/delete")
async def delete_subscription(sub_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Subscription).where(Subscription.id == sub_id))
    sub = result.scalar_one_or_none()
    if sub:
        await db.delete(sub)
        await db.commit()
    return RedirectResponse("/subscriptions?msg=Subscription+deleted&type=success", status_code=303)


@router.post("/subscriptions/{sub_id}/toggle")
async def toggle_subscription(sub_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Subscription).where(Subscription.id == sub_id))
    sub = result.scalar_one_or_none()
    if sub:
        sub.is_active = not sub.is_active
        await db.commit()
    return RedirectResponse("/subscriptions?msg=Updated&type=success", status_code=303)
