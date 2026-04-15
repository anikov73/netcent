"""Accounts management."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.account import Account
from app.models.transaction import Transaction

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Account).order_by(Account.name))
    accounts = result.scalars().all()

    # Transaction count per account (None key = unassigned)
    counts_result = await db.execute(
        select(Transaction.account_id, func.count(Transaction.id).label("cnt"))
        .group_by(Transaction.account_id)
    )
    counts: dict[int | None, int] = {row.account_id: row.cnt for row in counts_result}
    unassigned_count = counts.get(None, 0)

    msg = request.query_params.get("msg", "")
    msg_type = request.query_params.get("type", "info")
    return templates.TemplateResponse("accounts.html", {
        "request": request,
        "active_page": "accounts",
        "accounts": accounts,
        "tx_counts": counts,
        "unassigned_count": unassigned_count,
        "flash_messages": [{"message": msg, "type": msg_type}] if msg else [],
    })


@router.post("/accounts/create")
async def create_account(
    name: str = Form(...),
    description: str = Form(default=""),
    currency: str = Form(default="MKD"),
    db: AsyncSession = Depends(get_db),
):
    account = Account(
        name=name.strip(),
        description=description.strip() or None,
        currency=currency.strip().upper() or "MKD",
        is_active=True,
    )
    db.add(account)
    await db.commit()
    return RedirectResponse("/accounts?msg=Account+created&type=success", status_code=303)


@router.post("/accounts/{account_id}/edit")
async def edit_account(
    account_id: int,
    name: str = Form(...),
    description: str = Form(default=""),
    currency: str = Form(default="MKD"),
    is_active: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        return RedirectResponse("/accounts?msg=Not+found&type=error", status_code=303)

    account.name = name.strip()
    account.description = description.strip() or None
    account.currency = currency.strip().upper() or "MKD"
    account.is_active = bool(is_active)
    await db.commit()
    return RedirectResponse("/accounts?msg=Account+updated&type=success", status_code=303)


@router.post("/accounts/{account_id}/clear-transactions")
async def clear_account_transactions(
    account_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete every transaction assigned to this account. Account row is kept."""
    acc_result = await db.execute(select(Account).where(Account.id == account_id))
    account = acc_result.scalar_one_or_none()
    if not account:
        return RedirectResponse("/accounts?msg=Not+found&type=error", status_code=303)

    del_result = await db.execute(
        delete(Transaction).where(Transaction.account_id == account_id)
    )
    await db.commit()
    deleted = del_result.rowcount or 0
    return RedirectResponse(
        f"/accounts?msg=Deleted+{deleted}+transactions+for+{account.name}&type=success",
        status_code=303,
    )


@router.post("/accounts/clear-unassigned")
async def clear_unassigned_transactions(db: AsyncSession = Depends(get_db)):
    """Delete every transaction with no account assigned (account_id IS NULL)."""
    del_result = await db.execute(
        delete(Transaction).where(Transaction.account_id.is_(None))
    )
    await db.commit()
    deleted = del_result.rowcount or 0
    return RedirectResponse(
        f"/accounts?msg=Deleted+{deleted}+unassigned+transactions&type=success",
        status_code=303,
    )


@router.post("/accounts/{account_id}/delete")
async def delete_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        return RedirectResponse("/accounts?msg=Not+found&type=error", status_code=303)

    await db.delete(account)
    await db.commit()
    return RedirectResponse("/accounts?msg=Account+deleted&type=success", status_code=303)
