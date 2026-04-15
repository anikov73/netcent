"""Parser for CMS card-transaction .xls exports (e.g. CmsTransactions*.xls).

These files are Excel 97-2003 workbooks exported from a Macedonian bank's
card-transaction statement tool. They have a fixed shape:

- ~15 leading metadata rows (account number, period, debit/credit totals).
- A header row with Cyrillic labels including "Датум на трансакција".
- Data rows below, each with: transaction date, booking date, description,
  card-number mask, original amount+currency, MKD amount, running balance.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal
from io import BytesIO

import xlrd

from app.services.transliteration import macedonian_to_english

logger = logging.getLogger(__name__)

# Column indexes in the CMS .xls layout (0-based)
COL_TRANS_DATE = 1
COL_VALUE_DATE = 3
COL_DESCRIPTION = 6
COL_CARD = 13
COL_AMOUNT_ORIG = 15       # e.g. "- 19,99 USD"
COL_AMOUNT_MKD = 16        # e.g. "- 1.072,00 MKD"
COL_BALANCE = 17

HEADER_MARKER = "Датум на трансакција"


def detect(filename: str, content: bytes) -> bool:
    """Return True if this looks like a CMS card-transactions .xls export."""
    name = (filename or "").lower()
    if name.startswith("cmstransactions") and name.endswith((".xls", ".xlsx")):
        return True
    # Fallback: sniff the file for the Cyrillic header marker
    try:
        book = xlrd.open_workbook(file_contents=content)
        sh = book.sheet_by_index(0)
        scan_rows = min(40, sh.nrows)
        for r in range(scan_rows):
            for c in range(sh.ncols):
                if HEADER_MARKER in str(sh.cell_value(r, c)):
                    return True
    except Exception:
        return False
    return False


def _parse_date(val: str) -> str | None:
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


_AMOUNT_CUR_RE = re.compile(r"^\s*(-?)\s*([\d\.\,]+)\s*([A-Z]{3})?\s*$")


def _parse_amount(val: str) -> tuple[Decimal | None, str | None]:
    """Parse strings like '- 1.072,00 MKD' or '- 19,99 USD' or '2.957,00 MKD'."""
    if val is None:
        return None, None
    s = str(val).strip()
    if not s:
        return None, None
    m = _AMOUNT_CUR_RE.match(s)
    if not m:
        return None, None
    sign, num, cur = m.groups()
    # European format: 1.234,56 — dot is thousands, comma is decimal
    num = num.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(num)
    except Exception:
        return None, None
    if sign == "-":
        amount = -amount
    return amount, cur


def _find_header_row(sh) -> int:
    for r in range(min(40, sh.nrows)):
        for c in range(sh.ncols):
            if HEADER_MARKER in str(sh.cell_value(r, c)):
                return r
    raise ValueError("CMS header row not found")


def parse(content: bytes) -> list[dict]:
    """Parse a CMS .xls file into a list of transaction dicts.

    Returns dicts compatible with `import_from_parsed`:
      {date, value_date, description, amount, currency, merchant, notes}

    The MKD (domestic) amount is used as the primary amount since that's what
    actually posts to the account. The original-currency amount is preserved in
    `notes` for FX transactions.
    """
    book = xlrd.open_workbook(file_contents=content)
    sh = book.sheet_by_index(0)
    header_row = _find_header_row(sh)

    out: list[dict] = []
    for r in range(header_row + 1, sh.nrows):
        trans_date_raw = sh.cell_value(r, COL_TRANS_DATE)
        if not str(trans_date_raw).strip():
            continue  # skip blank spacer rows

        trans_date = _parse_date(trans_date_raw)
        if not trans_date:
            logger.debug("cms_parser: row %d skipped — bad date %r", r, trans_date_raw)
            continue

        value_date = _parse_date(sh.cell_value(r, COL_VALUE_DATE))
        description = str(sh.cell_value(r, COL_DESCRIPTION)).strip()
        card = str(sh.cell_value(r, COL_CARD)).strip()

        mkd_amount, mkd_cur = _parse_amount(sh.cell_value(r, COL_AMOUNT_MKD))
        orig_amount, orig_cur = _parse_amount(sh.cell_value(r, COL_AMOUNT_ORIG))

        # Prefer MKD (domestic posting amount); fall back to original.
        if mkd_amount is not None:
            amount, currency = mkd_amount, mkd_cur or "MKD"
        elif orig_amount is not None:
            amount, currency = orig_amount, orig_cur or "MKD"
        else:
            logger.debug("cms_parser: row %d skipped — unparseable amount", r)
            continue

        notes_parts = []
        if card:
            notes_parts.append(f"card {card}")
        if orig_amount is not None and orig_cur and orig_cur != currency:
            notes_parts.append(f"{orig_amount} {orig_cur}")
        notes = " | ".join(notes_parts) or None

        out.append({
            "date": trans_date,
            "value_date": value_date,
            "description": macedonian_to_english(description),
            "amount": str(amount),
            "currency": currency,
            "merchant": None,
            "notes": macedonian_to_english(notes),
        })

    logger.info("cms_parser: parsed %d transactions (header row %d, total rows %d)",
                len(out), header_row, sh.nrows)
    return out
