import json
import logging

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.account import Account
from app.models.import_log import ImportLog
from app.services.categorization import auto_categorize_transactions
from app.services.import_service import preview_file, import_transactions, import_from_parsed
from app.services.llm_mapper import extract_transactions

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


async def _load_accounts(db: AsyncSession) -> list[Account]:
    result = await db.execute(select(Account).where(Account.is_active == True).order_by(Account.name))
    return result.scalars().all()


@router.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ImportLog).order_by(ImportLog.imported_at.desc()).limit(10)
    )
    logs = result.scalars().all()
    accounts = await _load_accounts(db)
    msg = request.query_params.get("msg", "")
    msg_type = request.query_params.get("type", "info")
    return templates.TemplateResponse("upload.html", {
        "request": request,
        "active_page": "upload",
        "logs": logs,
        "accounts": accounts,
        "has_openai": bool(settings.openai_api_key),
        "flash_messages": [{"message": msg, "type": msg_type}] if msg else [],
    })


@router.post("/upload/ai", response_class=HTMLResponse)
async def upload_ai(
    request: Request,
    file: UploadFile = File(...),
    account_id: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    """Upload → AI extracts all transactions → show confirmation."""
    import time
    t_start = time.perf_counter()

    content = await file.read()
    filename = file.filename
    logger.info("┌── AI UPLOAD ────────────────────────────────────")
    logger.info("│ file     : %s", filename)
    logger.info("│ size     : %d bytes (%.1f KB)", len(content), len(content) / 1024)
    logger.info("│ openai   : model=%s  key_set=%s", settings.openai_model, bool(settings.openai_api_key))
    logger.info("│ account  : %s", account_id or "none")

    logger.info("│ [step 1] Calling extract_transactions …")
    try:
        parsed = await extract_transactions(content, filename)
    except Exception as e:
        logger.exception("│ [step 1] FAILED")
        logger.info("└─────────────────────────────────────────────────")
        return RedirectResponse(
            f"/upload?msg=AI+extraction+failed:+{e}&type=error", status_code=303
        )

    logger.info("│ [step 1] OK — %d transactions extracted in %.0fms",
                len(parsed), (time.perf_counter() - t_start) * 1000)

    if not parsed:
        logger.warning("│ No transactions found — aborting")
        logger.info("└─────────────────────────────────────────────────")
        return RedirectResponse(
            f"/upload?msg=AI+found+no+transactions+in+{filename}&type=error", status_code=303
        )

    logger.info("│ [step 2] Rendering confirmation page …")
    logger.info("└── total so far: %.0fms", (time.perf_counter() - t_start) * 1000)

    # Resolve account name for display
    account_name = ""
    if account_id:
        acc_result = await db.execute(select(Account).where(Account.id == int(account_id)))
        acc = acc_result.scalar_one_or_none()
        if acc:
            account_name = acc.name

    return templates.TemplateResponse("upload_ai_confirm.html", {
        "request": request,
        "active_page": "upload",
        "filename": filename,
        "account_id": account_id,
        "account_name": account_name,
        "parsed_json": json.dumps(parsed),
        "transactions": parsed,
        "flash_messages": [],
    })


@router.post("/upload/ai/confirm")
async def upload_ai_confirm(
    filename: str = Form(...),
    parsed_json: str = Form(...),
    account_id: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    import time
    t_start = time.perf_counter()
    parsed = json.loads(parsed_json)
    acc_id = int(account_id) if account_id else None
    logger.info("┌── AI IMPORT CONFIRM ────────────────────────────")
    logger.info("│ file        : %s", filename)
    logger.info("│ transactions: %d to import", len(parsed))
    logger.info("│ account_id  : %s", acc_id)
    try:
        result = await import_from_parsed(
            parsed=parsed,
            filename=filename,
            db=db,
            categorize_fn=auto_categorize_transactions,
            account_id=acc_id,
        )
        logger.info("│ result: new=%d  dupes=%d  errors=%d  time=%.0fms",
                    result["new"], result["duplicates"], result["errors"],
                    (time.perf_counter() - t_start) * 1000)
        logger.info("└─────────────────────────────────────────────────")
        msg = f"Imported {result['new']} new, {result['duplicates']} duplicates, {result['errors']} errors"
        return RedirectResponse(f"/upload?msg={msg}&type=success", status_code=303)
    except Exception as e:
        logger.exception("│ FAILED")
        logger.info("└─────────────────────────────────────────────────")
        return RedirectResponse(
            f"/upload?msg=Import+failed:+{e}&type=error", status_code=303
        )


@router.post("/upload/preview", response_class=HTMLResponse)
async def upload_preview(
    request: Request,
    file: UploadFile = File(...),
    account_id: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    try:
        preview = preview_file(content, file.filename)
    except Exception as e:
        return RedirectResponse(f"/upload?msg=Error+reading+file:+{e}&type=error", status_code=303)

    accounts = await _load_accounts(db)
    return templates.TemplateResponse("upload_preview.html", {
        "request": request,
        "active_page": "upload",
        "filename": file.filename,
        "file_content_b64": content.hex(),
        "columns": preview["columns"],
        "rows": preview["rows"],
        "account_id": account_id,
        "accounts": accounts,
        "flash_messages": [],
    })


@router.post("/upload/import")
async def do_import(
    filename: str = Form(...),
    file_hex: str = Form(...),
    account_id: str = Form(default=""),
    col_date: str = Form(default=""),
    col_description: str = Form(default=""),
    col_amount: str = Form(default=""),
    col_debit: str = Form(default=""),
    col_credit: str = Form(default=""),
    col_currency: str = Form(default=""),
    col_value_date: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    content = bytes.fromhex(file_hex)
    acc_id = int(account_id) if account_id else None
    mapping = {}
    if col_date:        mapping["date"] = col_date
    if col_description: mapping["description"] = col_description
    if col_amount:      mapping["amount"] = col_amount
    if col_debit:       mapping["debit"] = col_debit
    if col_credit:      mapping["credit"] = col_credit
    if col_currency:    mapping["currency"] = col_currency
    if col_value_date:  mapping["value_date"] = col_value_date

    try:
        result = await import_transactions(
            content=content, filename=filename, column_mapping=mapping,
            db=db, categorize_fn=auto_categorize_transactions,
            account_id=acc_id,
        )
        msg = f"Imported {result['new']} new, {result['duplicates']} duplicates, {result['errors']} errors"
        return RedirectResponse(f"/upload?msg={msg}&type=success", status_code=303)
    except Exception as e:
        logger.exception("Manual import failed")
        return RedirectResponse(f"/upload?msg=Import+failed:+{e}&type=error", status_code=303)


@router.get("/upload/logs/{log_id}", response_class=HTMLResponse)
async def view_log(log_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    from app.models.transaction import Transaction
    log_result = await db.execute(select(ImportLog).where(ImportLog.id == log_id))
    log = log_result.scalar_one_or_none()
    if not log:
        return RedirectResponse("/upload")
    tx_result = await db.execute(
        select(Transaction).where(Transaction.import_log_id == log_id).limit(200)
    )
    transactions = tx_result.scalars().all()
    return templates.TemplateResponse("import_log.html", {
        "request": request,
        "active_page": "upload",
        "log": log,
        "transactions": transactions,
        "flash_messages": [],
    })
