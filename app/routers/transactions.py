from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.account import Account
from app.models.transaction import Transaction
from app.models.category import Category

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

PAGE_SIZE = 50


@router.get("/transactions", response_class=HTMLResponse)
async def transactions_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = 1,
    q: str = "",
    category_id: str = "",
    account_id: str = "",
    date_from: str = "",
    date_to: str = "",
    amount_min: str = "",
    amount_max: str = "",
    currency: str = "",
    uncategorized: bool = False,
    income_only: bool = False,
    expense_only: bool = False,
    sort: str = "date",
    order: str = "desc",
    page_size: str = "50",
):
    query = select(Transaction).options(
        selectinload(Transaction.category),
        selectinload(Transaction.account),
    )

    # Filters
    if q:
        search = f"%{q}%"
        query = query.where(
            or_(
                Transaction.description.ilike(search),
                Transaction.description_clean.ilike(search),
                Transaction.merchant.ilike(search),
                Transaction.notes.ilike(search),
            )
        )
    try:
        category_id_int = int(category_id) if category_id else None
    except ValueError:
        category_id_int = None
    try:
        account_id_int = int(account_id) if account_id else None
    except ValueError:
        account_id_int = None

    if category_id_int:
        query = query.where(Transaction.category_id == category_id_int)
    if account_id_int:
        query = query.where(Transaction.account_id == account_id_int)
    if date_from:
        from datetime import date
        try:
            query = query.where(Transaction.date >= date.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        from datetime import date
        try:
            query = query.where(Transaction.date <= date.fromisoformat(date_to))
        except ValueError:
            pass
    if amount_min:
        try:
            query = query.where(Transaction.amount >= float(amount_min))
        except ValueError:
            pass
    if amount_max:
        try:
            query = query.where(Transaction.amount <= float(amount_max))
        except ValueError:
            pass
    if currency:
        query = query.where(Transaction.currency == currency)
    if uncategorized:
        query = query.where(Transaction.category_id == None)
    if income_only:
        query = query.where(Transaction.amount > 0)
    if expense_only:
        query = query.where(Transaction.amount < 0)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar()

    # Sort
    sort_col = {
        'date': Transaction.date,
        'amount': Transaction.amount,
        'description': Transaction.description_clean,
        'merchant': Transaction.merchant,
    }.get(sort, Transaction.date)
    if order == 'asc':
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    # Page size: "20" / "50" / "100" / "all"
    if page_size == "all":
        ps_int: int | None = None
    else:
        try:
            ps_int = int(page_size)
        except ValueError:
            ps_int = PAGE_SIZE
        if ps_int not in (20, 50, 100):
            ps_int = PAGE_SIZE

    if ps_int is None:
        result = await db.execute(query)
    else:
        offset = (page - 1) * ps_int
        result = await db.execute(query.offset(offset).limit(ps_int))
    transactions = result.scalars().all()

    # Categories for filter
    cats_result = await db.execute(select(Category).order_by(Category.name))
    categories = cats_result.scalars().all()

    # Accounts for filter
    accs_result = await db.execute(select(Account).where(Account.is_active == True).order_by(Account.name))
    accounts = accs_result.scalars().all()

    if ps_int is None:
        total_pages = 1
        page = 1
    else:
        total_pages = max(1, (total + ps_int - 1) // ps_int)
        page = min(max(1, page), total_pages)

    # Window of page numbers: current ± 5, clamped to [1, total_pages].
    window_start = max(1, page - 5)
    window_end = min(total_pages, page + 5)
    page_window = list(range(window_start, window_end + 1))

    # Build a querystring that preserves every active filter/sort param so
    # pagination links don't reset the user's filters.
    filter_params: list[tuple[str, str]] = [("page_size", page_size)]
    for key, value in (
        ("q", q),
        ("category_id", category_id),
        ("account_id", account_id),
        ("date_from", date_from),
        ("date_to", date_to),
        ("amount_min", amount_min),
        ("amount_max", amount_max),
        ("currency", currency),
        ("sort", sort),
        ("order", order),
    ):
        if value:
            filter_params.append((key, str(value)))
    for key, flag in (
        ("uncategorized", uncategorized),
        ("income_only", income_only),
        ("expense_only", expense_only),
    ):
        if flag:
            filter_params.append((key, "1"))
    filter_qs = urlencode(filter_params)

    msg = request.query_params.get("msg", "")
    msg_type = request.query_params.get("type", "info")

    return templates.TemplateResponse("transactions.html", {
        "request": request,
        "active_page": "transactions",
        "transactions": transactions,
        "categories": categories,
        "accounts": accounts,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "q": q,
        "category_id": category_id,
        "account_id": account_id,
        "date_from": date_from,
        "date_to": date_to,
        "amount_min": amount_min,
        "amount_max": amount_max,
        "currency": currency,
        "uncategorized": uncategorized,
        "income_only": income_only,
        "expense_only": expense_only,
        "sort": sort,
        "order": order,
        "page_size": page_size,
        "page_window": page_window,
        "filter_qs": filter_qs,
        "flash_messages": [{"message": msg, "type": msg_type}] if msg else [],
    })


@router.post("/transactions/bulk-delete")
async def bulk_delete_transactions(
    ids: list[int] = Form(default=[]),
    db: AsyncSession = Depends(get_db),
):
    """Delete every transaction whose id is in `ids`. Posted from the
    transactions page after the user double-confirms in the UI."""
    if not ids:
        return RedirectResponse(
            "/transactions?msg=No+transactions+selected&type=error", status_code=303
        )
    result = await db.execute(delete(Transaction).where(Transaction.id.in_(ids)))
    await db.commit()
    deleted = result.rowcount or 0
    return RedirectResponse(
        f"/transactions?msg=Deleted+{deleted}+transactions&type=success", status_code=303
    )


@router.post("/transactions/{tx_id}/edit")
async def edit_transaction(
    tx_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    category_id: str = Form(default=""),
    notes: str = Form(default=""),
    merchant: str = Form(default=""),
    description_clean: str = Form(default=""),
):
    result = await db.execute(select(Transaction).where(Transaction.id == tx_id))
    tx = result.scalar_one_or_none()
    if not tx:
        return RedirectResponse("/transactions?msg=Not+found&type=error", status_code=303)

    if category_id:
        tx.category_id = int(category_id) if category_id != "0" else None
        tx.is_manually_categorized = True
    if notes is not None:
        tx.notes = notes or None
    if merchant:
        tx.merchant = merchant
    if description_clean:
        tx.description_clean = description_clean

    await db.commit()
    return RedirectResponse(
        f"/transactions?msg=Transaction+updated&type=success", status_code=303
    )


@router.get("/transactions/{tx_id}", response_class=HTMLResponse)
async def transaction_detail(
    tx_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Transaction)
        .options(selectinload(Transaction.category), selectinload(Transaction.account))
        .where(Transaction.id == tx_id)
    )
    tx = result.scalar_one_or_none()
    if not tx:
        return RedirectResponse("/transactions")

    cats_result = await db.execute(select(Category).order_by(Category.name))
    categories = cats_result.scalars().all()

    return templates.TemplateResponse("transaction_detail.html", {
        "request": request,
        "active_page": "transactions",
        "tx": tx,
        "categories": categories,
        "flash_messages": [],
    })
