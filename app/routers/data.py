"""Export / Import page."""
import json
import logging
from datetime import date

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction
from app.services.categorization import auto_categorize_transactions
from app.services.import_service import import_from_parsed

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


async def _page_context(db: AsyncSession, today: date) -> dict:
    accs = await db.execute(select(Account).where(Account.is_active == True).order_by(Account.name))
    return {
        "accounts": accs.scalars().all(),
        "default_date_from": str(date(today.year, 1, 1)),
        "default_date_to": str(today),
    }


@router.get("/data", response_class=HTMLResponse)
async def data_page(request: Request, db: AsyncSession = Depends(get_db)):
    today = date.today()
    ctx = await _page_context(db, today)
    return templates.TemplateResponse("data.html", {
        "request": request,
        "active_page": "data",
        "flash_messages": [],
        **ctx,
    })


@router.get("/data/export")
async def export_transactions(
    date_from: str = "",
    date_to: str = "",
    account_id: str = "",
    db: AsyncSession = Depends(get_db),
):
    query = select(Transaction).order_by(Transaction.date.asc(), Transaction.id.asc())

    if date_from:
        try:
            query = query.where(Transaction.date >= date.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            query = query.where(Transaction.date <= date.fromisoformat(date_to))
        except ValueError:
            pass
    if account_id:
        try:
            query = query.where(Transaction.account_id == int(account_id))
        except ValueError:
            pass

    result = await db.execute(query)
    transactions = result.scalars().all()

    # Load categories and accounts for name lookup
    cat_result = await db.execute(select(Category))
    cat_map = {c.id: c for c in cat_result.scalars().all()}
    acc_result = await db.execute(select(Account))
    acc_map = {a.id: a for a in acc_result.scalars().all()}

    rows = []
    for tx in transactions:
        cat = cat_map.get(tx.category_id) if tx.category_id else None
        acc = acc_map.get(tx.account_id) if tx.account_id else None
        rows.append({
            "date": str(tx.date),
            "value_date": str(tx.value_date) if tx.value_date else None,
            "description": tx.description,
            "description_clean": tx.description_clean,
            "merchant": tx.merchant,
            "amount": float(tx.amount),
            "currency": tx.currency,
            "account": acc.name if acc else None,
            "category": cat.name if cat else None,
            "notes": tx.notes,
            "is_manually_categorized": tx.is_manually_categorized,
        })

    filename_parts = ["transactions"]
    if account_id:
        acc = acc_map.get(int(account_id)) if account_id.isdigit() else None
        if acc:
            filename_parts.append(acc.name.replace(" ", "_"))
    if date_from:
        filename_parts.append(date_from)
    if date_to:
        filename_parts.append(date_to)
    filename = "_".join(filename_parts) + ".json"

    payload = json.dumps({"transactions": rows}, ensure_ascii=False, indent=2)
    logger.info("Exporting %d transactions to %s", len(rows), filename)

    return StreamingResponse(
        iter([payload]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/data/import", response_class=HTMLResponse)
async def import_json(
    request: Request,
    file: UploadFile = File(...),
    account_id: str = "",
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    today = date.today()

    try:
        data = json.loads(content)
    except Exception as e:
        ctx = await _page_context(db, today)
        return templates.TemplateResponse("data.html", {
            "request": request,
            "active_page": "data",
            "flash_messages": [{"message": f"Invalid JSON: {e}", "type": "error"}],
            **ctx,
        })

    rows = data if isinstance(data, list) else data.get("transactions", [])

    if not rows:
        ctx = await _page_context(db, today)
        return templates.TemplateResponse("data.html", {
            "request": request,
            "active_page": "data",
            "flash_messages": [{"message": "No transactions found in file.", "type": "error"}],
            **ctx,
        })

    # Resolve category names → ids
    cat_result = await db.execute(select(Category))
    cat_name_map = {c.name.lower(): c.id for c in cat_result.scalars().all()}

    # Resolve account names → ids
    acc_result = await db.execute(select(Account))
    acc_name_map = {a.name.lower(): a.id for a in acc_result.scalars().all()}

    # Determine account_id: form field takes priority, else fall back to JSON field per row
    forced_account_id = int(account_id) if account_id else None

    parsed = []
    for row in rows:
        item = {
            "date": row.get("date", ""),
            "description": row.get("description_clean") or row.get("description", ""),
            "amount": row.get("amount", 0),
            "currency": row.get("currency", "MKD"),
        }
        cat_name = (row.get("category") or "").lower()
        if cat_name and cat_name in cat_name_map:
            item["category_id"] = cat_name_map[cat_name]

        # Resolve account: form override → JSON field → None
        if forced_account_id:
            item["account_id"] = forced_account_id
        else:
            row_acc = (row.get("account") or "").lower()
            if row_acc and row_acc in acc_name_map:
                item["account_id"] = acc_name_map[row_acc]

        parsed.append(item)

    # Pass account_id to import only when forced (per-row is handled above)
    try:
        result = await import_from_parsed(
            parsed=parsed,
            filename=file.filename,
            db=db,
            categorize_fn=auto_categorize_transactions,
            account_id=forced_account_id,
        )
        msg = f"Imported {result['new']} new, {result['duplicates']} duplicates, {result['errors']} errors"
        msg_type = "success"
    except Exception as e:
        logger.exception("JSON import failed")
        msg = f"Import failed: {e}"
        msg_type = "error"

    ctx = await _page_context(db, today)
    return templates.TemplateResponse("data.html", {
        "request": request,
        "active_page": "data",
        "flash_messages": [{"message": msg, "type": msg_type}],
        **ctx,
    })
