from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.category import Category
from app.models.transaction import Transaction

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/categories", response_class=HTMLResponse)
async def categories_list(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(
            Category,
            func.count(Transaction.id).label('tx_count'),
        )
        .outerjoin(Transaction, Transaction.category_id == Category.id)
        .group_by(Category.id)
        .order_by(Category.sort_order, Category.name)
    )
    rows = result.all()
    categories = [{'cat': r[0], 'tx_count': r[1]} for r in rows]

    parent_cats = [r[0] for r in rows if r[0].parent_id is None]

    msg = request.query_params.get("msg", "")
    msg_type = request.query_params.get("type", "info")

    return templates.TemplateResponse("categories.html", {
        "request": request,
        "active_page": "categories",
        "categories": categories,
        "parent_cats": parent_cats,
        "flash_messages": [{"message": msg, "type": msg_type}] if msg else [],
    })


@router.post("/categories/create")
async def create_category(
    name: str = Form(...),
    icon: str = Form(default=""),
    color: str = Form(default="#9E9E9E"),
    parent_id: str = Form(default=""),
    is_income: str = Form(default=""),
    sort_order: int = Form(default=0),
    db: AsyncSession = Depends(get_db),
):
    cat = Category(
        name=name,
        icon=icon or None,
        color=color or "#9E9E9E",
        parent_id=int(parent_id) if parent_id else None,
        is_income=bool(is_income),
        sort_order=sort_order,
    )
    db.add(cat)
    await db.commit()
    return RedirectResponse("/categories?msg=Category+created&type=success", status_code=303)


@router.post("/categories/{cat_id}/edit")
async def edit_category(
    cat_id: int,
    name: str = Form(...),
    icon: str = Form(default=""),
    color: str = Form(default="#9E9E9E"),
    parent_id: str = Form(default=""),
    is_income: str = Form(default=""),
    sort_order: int = Form(default=0),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Category).where(Category.id == cat_id))
    cat = result.scalar_one_or_none()
    if not cat:
        return RedirectResponse("/categories?msg=Not+found&type=error", status_code=303)

    cat.name = name
    cat.icon = icon or None
    cat.color = color
    cat.parent_id = int(parent_id) if parent_id else None
    cat.is_income = bool(is_income)
    cat.sort_order = sort_order
    await db.commit()
    return RedirectResponse("/categories?msg=Category+updated&type=success", status_code=303)


@router.post("/categories/{cat_id}/delete")
async def delete_category(
    cat_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Category).where(Category.id == cat_id))
    cat = result.scalar_one_or_none()
    if not cat:
        return RedirectResponse("/categories?msg=Not+found&type=error", status_code=303)

    if cat.name == 'Uncategorized':
        return RedirectResponse("/categories?msg=Cannot+delete+Uncategorized&type=error", status_code=303)

    # Move transactions to Uncategorized
    uncat_result = await db.execute(select(Category).where(Category.name == 'Uncategorized'))
    uncat = uncat_result.scalar_one_or_none()

    tx_result = await db.execute(select(Transaction).where(Transaction.category_id == cat_id))
    for tx in tx_result.scalars().all():
        tx.category_id = uncat.id if uncat else None

    await db.delete(cat)
    await db.commit()
    return RedirectResponse("/categories?msg=Category+deleted&type=success", status_code=303)


@router.post("/categories/merge")
async def merge_categories(
    source_id: int = Form(...),
    target_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    tx_result = await db.execute(
        select(Transaction).where(Transaction.category_id == source_id)
    )
    for tx in tx_result.scalars().all():
        tx.category_id = target_id

    source_result = await db.execute(select(Category).where(Category.id == source_id))
    source = source_result.scalar_one_or_none()
    if source:
        await db.delete(source)

    await db.commit()
    return RedirectResponse("/categories?msg=Categories+merged&type=success", status_code=303)
