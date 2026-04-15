import hashlib
import logging
import re
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any

import pandas as pd

from app.models.import_log import ImportLog
from app.models.transaction import Transaction

logger = logging.getLogger(__name__)


def compute_hash(date_val: str, description: str, amount: str, currency: str) -> str:
    raw = f"{date_val}|{description}|{amount}|{currency}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def _load_existing_naturals(db, naturals: set[str]) -> set[str]:
    """Return the subset of `naturals` that already appear in the DB.

    In-batch duplicate rows share the same natural hash but are stored with a
    `|N` suffix, so we compare the 64-char prefix of every stored hash.
    """
    if not naturals:
        return set()
    from sqlalchemy import func, select
    result = await db.execute(
        select(Transaction.import_hash).where(
            func.substring(Transaction.import_hash, 1, 64).in_(naturals)
        )
    )
    return {h[:64] for (h,) in result.all()}


def _next_unique_hash(natural: str, occurrence: dict[str, int]) -> str:
    """Disambiguate within-batch duplicates so each row gets a unique DB hash."""
    n = occurrence.get(natural, 0)
    occurrence[natural] = n + 1
    return natural if n == 0 else f"{natural}|{n}"


def clean_description(desc: str) -> str:
    if not desc:
        return desc
    # Remove excessive whitespace
    clean = re.sub(r'\s+', ' ', desc.strip())
    # Remove card numbers (sequences of 4+ digits with spaces/dashes)
    clean = re.sub(r'\b\d{4}[\s\-]\d{4}[\s\-]\d{4}[\s\-]?\d{0,4}\b', '', clean)
    # Remove long pure-digit reference codes (e.g. "4029357733") but keep
    # uppercase merchant words like "TRADINGVIEW" or "CANVAPTYLIM".
    clean = re.sub(r'\b\d{8,}\b', '', clean)
    # Re-collapse whitespace introduced by the substitutions
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()


def extract_merchant(description: str) -> str | None:
    if not description:
        return None
    # Take first meaningful part before common separators
    parts = re.split(r'[,\|/\\]', description)
    merchant = parts[0].strip()
    # Capitalize properly
    if len(merchant) > 2:
        return merchant[:60]
    return None


def parse_date(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    s = str(val).strip()
    for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y'):
        try:
            from datetime import datetime
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(val: Any) -> tuple[Decimal | None, str | None]:
    """Returns (amount, currency_if_detected)."""
    if val is None:
        return None, None
    if isinstance(val, (int, float)):
        return Decimal(str(val)), None
    if isinstance(val, Decimal):
        return val, None

    s = str(val).strip()

    # Extract trailing currency (e.g. "- 19,99 USD" or "2.896,00 MKD")
    currency = None
    currency_match = re.search(r'([A-Z]{3})\s*$', s)
    if currency_match:
        currency = currency_match.group(1)
        s = s[:currency_match.start()].strip()

    # Determine sign
    negative = s.startswith('-') or '- ' in s or s.startswith('- ')
    s = s.replace('- ', '').replace('-', '').replace('+', '').replace("'", '').strip()

    # European format: 1.234,56 or 1.234.567,89
    if re.match(r'^\d{1,3}(\.\d{3})*(,\d+)?$', s):
        s = s.replace('.', '').replace(',', '.')
    else:
        # Try removing thousand separators and normalizing decimal
        s = re.sub(r'[^\d,.]', '', s)
        if s.count(',') == 1 and s.count('.') <= 1:
            if s.index(',') > s.index('.') if '.' in s else True:
                # comma is decimal separator
                s = s.replace('.', '').replace(',', '.')
        elif s.count('.') == 1 and s.count(',') > 1:
            # dot is decimal, commas are thousands
            s = s.replace(',', '')

    try:
        amount = Decimal(s)
        if negative:
            amount = -amount
        return amount, currency
    except Exception:
        return None, None


def _find_header_row(df: pd.DataFrame) -> int:
    """Find the first row where majority of cells are non-null — use as header."""
    for i, row in df.iterrows():
        non_null = row.notna().sum()
        if non_null >= max(3, len(df.columns) * 0.3):
            return i
    return 0


def read_file(content: bytes, filename: str, header_row: int | None = None) -> pd.DataFrame:
    ext = filename.rsplit('.', 1)[-1].lower()
    buf = BytesIO(content)
    if ext == 'csv':
        for sep in [',', ';', '\t']:
            try:
                df = pd.read_csv(buf, sep=sep, dtype=str, header=header_row)
                if len(df.columns) > 1:
                    return df
                buf.seek(0)
            except Exception:
                buf.seek(0)
        return pd.read_csv(buf, dtype=str)
    elif ext in ('xlsx', 'xls'):
        if header_row is not None:
            return pd.read_excel(buf, dtype=str, header=header_row)
        # Try to auto-detect header row
        raw = pd.read_excel(buf, dtype=str, header=None)
        hdr = _find_header_row(raw)
        buf.seek(0)
        df = pd.read_excel(buf, dtype=str, header=hdr)
        # Clean up unnamed columns
        df.columns = [
            str(c) if not str(c).startswith('Unnamed') else f"Col_{i}"
            for i, c in enumerate(df.columns)
        ]
        return df
    raise ValueError(f"Unsupported file format: {ext}")


def preview_file(content: bytes, filename: str) -> dict:
    df = read_file(content, filename)
    columns = list(df.columns)
    rows = df.head(10).fillna('').values.tolist()
    return {"columns": columns, "rows": rows}


async def import_transactions(
    content: bytes,
    filename: str,
    column_mapping: dict,
    db,
    categorize_fn=None,
    df: "pd.DataFrame | None" = None,
    account_id: int | None = None,
) -> dict:
    if df is None:
        df = read_file(content, filename)
    df = df.fillna('')

    new_count = 0
    dup_count = 0
    err_count = 0
    imported_ids = []

    # Create import log
    log = ImportLog(filename=filename, status='partial')
    db.add(log)
    await db.flush()

    # First pass — extract and validate every row so we can snapshot existing
    # DB hashes before inserting anything.
    prepared: list[tuple[object, object, str, Decimal, str, str]] = []
    for _, row in df.iterrows():
        try:
            date_col = column_mapping.get('date')
            desc_col = column_mapping.get('description')
            amount_col = column_mapping.get('amount')
            debit_col = column_mapping.get('debit')
            credit_col = column_mapping.get('credit')
            currency_col = column_mapping.get('currency')
            value_date_col = column_mapping.get('value_date')

            raw_date = parse_date(row.get(date_col, '')) if date_col else None
            if not raw_date:
                err_count += 1
                continue

            raw_desc = str(row.get(desc_col, '')).strip() if desc_col else ''
            if not raw_desc:
                err_count += 1
                continue

            currency = str(row.get(currency_col, 'MKD')).strip() if currency_col else 'MKD'
            if not currency or currency in ('nan', ''):
                currency = 'MKD'

            # Amount: single column or debit/credit
            detected_currency = None
            if amount_col and row.get(amount_col):
                amount, detected_currency = parse_amount(row.get(amount_col))
            elif debit_col or credit_col:
                debit, _ = parse_amount(row.get(debit_col, '')) if debit_col else (None, None)
                credit, _ = parse_amount(row.get(credit_col, '')) if credit_col else (None, None)
                debit = debit or Decimal('0')
                credit = credit or Decimal('0')
                amount = credit - debit
            else:
                err_count += 1
                continue

            if amount is None:
                err_count += 1
                continue

            # Use detected currency from amount string if no currency column
            if detected_currency and not currency_col:
                currency = detected_currency

            value_date = parse_date(row.get(value_date_col, '')) if value_date_col else None
            natural = compute_hash(str(raw_date), raw_desc, str(amount), currency)
            prepared.append((raw_date, value_date, raw_desc, amount, currency, natural))
        except Exception:
            err_count += 1
            continue

    existing_naturals = await _load_existing_naturals(
        db, {p[5] for p in prepared}
    )
    occurrence: dict[str, int] = {}

    for raw_date, value_date, raw_desc, amount, currency, natural in prepared:
        try:
            if natural in existing_naturals:
                dup_count += 1
                continue

            import_hash = _next_unique_hash(natural, occurrence)
            desc_clean = clean_description(raw_desc)
            merchant = extract_merchant(desc_clean)

            tx = Transaction(
                date=raw_date,
                value_date=value_date,
                description=raw_desc,
                description_clean=desc_clean,
                amount=amount,
                currency=currency,
                merchant=merchant,
                import_hash=import_hash,
                import_log_id=log.id,
                account_id=account_id,
            )
            db.add(tx)
            await db.flush()
            imported_ids.append(tx.id)
            new_count += 1

        except Exception:
            err_count += 1
            continue

    total = new_count + dup_count + err_count
    log.total_rows = total
    log.new_rows = new_count
    log.duplicate_rows = dup_count
    log.error_rows = err_count
    log.status = 'success' if err_count == 0 else 'partial'

    await db.commit()

    # Auto-categorize new transactions
    if categorize_fn and imported_ids:
        await categorize_fn(db, imported_ids)

    return {
        "log_id": log.id,
        "total": total,
        "new": new_count,
        "duplicates": dup_count,
        "errors": err_count,
    }


async def import_from_parsed(
    parsed: list[dict],
    filename: str,
    db,
    categorize_fn=None,
    account_id: int | None = None,
) -> dict:
    """Import pre-parsed transaction dicts from LLM extraction."""
    logger.info("import_from_parsed: filename=%s  input_count=%d", filename, len(parsed))

    new_count = 0
    dup_count = 0
    err_count = 0
    imported_ids = []

    log = ImportLog(filename=filename, status="partial")
    db.add(log)
    await db.flush()
    logger.debug("  Created ImportLog id=%d", log.id)

    # First pass — validate rows and compute natural hashes up front, so we can
    # snapshot the DB's existing hashes in a single query before touching it.
    prepared: list[tuple[int, dict, object, str, Decimal, str, str]] = []
    for i, item in enumerate(parsed):
        try:
            raw_date = parse_date(item.get("date", ""))
            if not raw_date:
                logger.debug("  [%d] SKIP — bad date: %r", i, item.get("date"))
                err_count += 1
                continue

            raw_desc = str(item.get("description", "")).strip()
            if not raw_desc:
                logger.debug("  [%d] SKIP — empty description", i)
                err_count += 1
                continue

            amount_raw = item.get("amount", 0)
            try:
                amount = Decimal(str(amount_raw))
            except Exception:
                logger.debug("  [%d] SKIP — bad amount: %r", i, amount_raw)
                err_count += 1
                continue

            currency = str(item.get("currency", "MKD")).strip() or "MKD"
            natural = compute_hash(str(raw_date), raw_desc, str(amount), currency)
            prepared.append((i, item, raw_date, raw_desc, amount, currency, natural))
        except Exception:
            logger.exception("  [%d] ERROR preparing item: %s", i, item)
            err_count += 1
            continue

    existing_naturals = await _load_existing_naturals(
        db, {p[6] for p in prepared}
    )
    occurrence: dict[str, int] = {}

    for i, item, raw_date, raw_desc, amount, currency, natural in prepared:
        try:
            if natural in existing_naturals:
                logger.debug("  [%d] DUPE — %s %s %.2f %s", i, raw_date, raw_desc[:40], amount, currency)
                dup_count += 1
                continue

            import_hash = _next_unique_hash(natural, occurrence)
            desc_clean = clean_description(raw_desc)
            merchant = extract_merchant(desc_clean)

            tx_account_id = item.get("account_id", account_id)

            tx = Transaction(
                date=raw_date,
                description=raw_desc,
                description_clean=desc_clean,
                amount=amount,
                currency=currency,
                merchant=merchant,
                import_hash=import_hash,
                import_log_id=log.id,
                account_id=tx_account_id,
            )
            db.add(tx)
            await db.flush()
            imported_ids.append(tx.id)
            new_count += 1
            logger.debug("  [%d] NEW  — %s %s %.2f %s", i, raw_date, raw_desc[:40], amount, currency)

        except Exception:
            logger.exception("  [%d] ERROR inserting item: %s", i, item)
            err_count += 1
            continue

    logger.info("  Loop done: new=%d  dupes=%d  errors=%d", new_count, dup_count, err_count)

    total = new_count + dup_count + err_count
    log.total_rows = total
    log.new_rows = new_count
    log.duplicate_rows = dup_count
    log.error_rows = err_count
    log.status = "success" if err_count == 0 else "partial"

    logger.info("  Committing to DB …")
    await db.commit()
    logger.info("  Committed. log_id=%d  status=%s", log.id, log.status)

    if categorize_fn and imported_ids:
        logger.info("  Auto-categorizing %d new transactions …", len(imported_ids))
        await categorize_fn(db, imported_ids)
        logger.info("  Categorization done")

    logger.info("import_from_parsed COMPLETE: log_id=%d  total=%d  new=%d  dupes=%d  errors=%d",
                log.id, total, new_count, dup_count, err_count)

    return {
        "log_id": log.id,
        "total": total,
        "new": new_count,
        "duplicates": dup_count,
        "errors": err_count,
    }
