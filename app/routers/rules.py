from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.categorization_rule import CategorizationRule
from app.models.category import Category
from app.services.categorization import test_rule, auto_categorize_transactions

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/rules", response_class=HTMLResponse)
async def rules_list(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CategorizationRule)
        .options(selectinload(CategorizationRule.category))
        .order_by(CategorizationRule.priority.desc(), CategorizationRule.id)
    )
    rules = result.scalars().all()

    cats_result = await db.execute(select(Category).order_by(Category.name))
    categories = cats_result.scalars().all()

    msg = request.query_params.get("msg", "")
    msg_type = request.query_params.get("type", "info")

    return templates.TemplateResponse("rules.html", {
        "request": request,
        "active_page": "rules",
        "rules": rules,
        "categories": categories,
        "flash_messages": [{"message": msg, "type": msg_type}] if msg else [],
        "test_results": None,
        "test_pattern": "",
    })


@router.post("/rules/create")
async def create_rule(
    pattern: str = Form(...),
    match_type: str = Form(...),
    category_id: int = Form(...),
    priority: int = Form(default=0),
    db: AsyncSession = Depends(get_db),
):
    rule = CategorizationRule(
        pattern=pattern,
        match_type=match_type,
        category_id=category_id,
        priority=priority,
        is_active=True,
    )
    db.add(rule)
    await db.commit()
    return RedirectResponse("/rules?msg=Rule+created&type=success", status_code=303)


@router.post("/rules/{rule_id}/edit")
async def edit_rule(
    rule_id: int,
    pattern: str = Form(...),
    match_type: str = Form(...),
    category_id: int = Form(...),
    priority: int = Form(default=0),
    is_active: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CategorizationRule).where(CategorizationRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        return RedirectResponse("/rules?msg=Not+found&type=error", status_code=303)

    rule.pattern = pattern
    rule.match_type = match_type
    rule.category_id = category_id
    rule.priority = priority
    rule.is_active = bool(is_active)
    await db.commit()
    return RedirectResponse("/rules?msg=Rule+updated&type=success", status_code=303)


@router.post("/rules/{rule_id}/delete")
async def delete_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CategorizationRule).where(CategorizationRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if rule:
        await db.delete(rule)
        await db.commit()
    return RedirectResponse("/rules?msg=Rule+deleted&type=success", status_code=303)


@router.post("/rules/{rule_id}/toggle")
async def toggle_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CategorizationRule).where(CategorizationRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if rule:
        rule.is_active = not rule.is_active
        await db.commit()
    return RedirectResponse("/rules?msg=Rule+toggled&type=success", status_code=303)


@router.post("/rules/test", response_class=HTMLResponse)
async def test_rule_endpoint(
    request: Request,
    pattern: str = Form(...),
    match_type: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    from app.models.transaction import Transaction
    from sqlalchemy.orm import selectinload as sl
    matches = await test_rule(db, pattern, match_type)

    result = await db.execute(
        select(CategorizationRule)
        .options(sl(CategorizationRule.category))
        .order_by(CategorizationRule.priority.desc())
    )
    rules = result.scalars().all()

    cats_result = await db.execute(select(Category).order_by(Category.name))
    categories = cats_result.scalars().all()

    return templates.TemplateResponse("rules.html", {
        "request": request,
        "active_page": "rules",
        "rules": rules,
        "categories": categories,
        "flash_messages": [],
        "test_results": matches,
        "test_pattern": pattern,
        "test_match_type": match_type,
    })


@router.post("/rules/recategorize")
async def bulk_recategorize(db: AsyncSession = Depends(get_db)):
    count = await auto_categorize_transactions(db)
    return RedirectResponse(
        f"/rules?msg={count}+transactions+recategorized&type=success", status_code=303
    )
