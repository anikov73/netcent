"""Parser for Ret account-transaction .xls exports (e.g. RetTransactions*.xls).

These are Macedonian-bank "retail account" statements exported to Excel
97-2003. Layout:

- Metadata header (period, account number, holder name, totals) in the first
  ~22 rows.
- Two-row column-header block around row 25-26 with Cyrillic labels
  ("ред. бр. на нал.", "Датум", "Износ", "Задолжување", "Побарување", ...).
- Each transaction occupies TWO rows: the data row (sequence number in col 3)
  plus a trailing row with the counterparty account number / currency code in
  col 5. The trailing row has no sequence number.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

import xlrd

from app.services.transliteration import macedonian_to_english

logger = logging.getLogger(__name__)

# 0-based column indexes for the Ret layout
COL_SEQ = 3
COL_DATE = 4
COL_PAYEE = 5           # also holds counterparty account on the trailing row
COL_PURPOSE = 8
COL_DEBIT = 15
COL_CREDIT = 17
COL_FEE = 19
COL_BALANCE = 24

HEADER_MARKER = "ред. бр. на нал."


def detect(filename: str, content: bytes) -> bool:
    name = (filename or "").lower()
    if name.startswith("rettransactions") and name.endswith((".xls", ".xlsx")):
        return True
    try:
        book = xlrd.open_workbook(file_contents=content)
        sh = book.sheet_by_index(0)
        for r in range(min(40, sh.nrows)):
            for c in range(sh.ncols):
                if HEADER_MARKER in str(sh.cell_value(r, c)):
                    return True
    except Exception:
        return False
    return False


def _parse_date(val: Any) -> str | None:
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_mkd(val: Any) -> Decimal:
    """Parse Macedonian number format '2.896,00' → Decimal. Returns 0 for blank."""
    s = str(val).strip()
    if not s:
        return Decimal(0)
    try:
        return Decimal(s.replace(".", "").replace(",", "."))
    except Exception:
        return Decimal(0)


def _find_header_row(sh) -> int:
    for r in range(min(40, sh.nrows)):
        for c in range(sh.ncols):
            if HEADER_MARKER in str(sh.cell_value(r, c)):
                return r
    raise ValueError("Ret header row not found")


def _seq_of(val: Any) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def parse(content: bytes) -> list[dict]:
    """Parse a Ret .xls file into transaction dicts compatible with `import_from_parsed`.

    Signed amount convention: debit → negative, credit → positive. Fees (if any)
    are folded into the amount so the balance math stays consistent.
    """
    book = xlrd.open_workbook(file_contents=content)
    sh = book.sheet_by_index(0)
    header_row = _find_header_row(sh)

    out: list[dict] = []
    r = header_row + 1
    while r < sh.nrows:
        seq = _seq_of(sh.cell_value(r, COL_SEQ))
        if seq is None:
            r += 1
            continue

        date = _parse_date(sh.cell_value(r, COL_DATE))
        if not date:
            logger.debug("ret_parser: seq %s row %d — bad date", seq, r)
            r += 1
            continue

        payee = str(sh.cell_value(r, COL_PAYEE)).strip()
        purpose = str(sh.cell_value(r, COL_PURPOSE)).strip()
        debit = _parse_mkd(sh.cell_value(r, COL_DEBIT))
        credit = _parse_mkd(sh.cell_value(r, COL_CREDIT))
        fee = _parse_mkd(sh.cell_value(r, COL_FEE))

        # The next row (trailing) usually holds counterparty account in col 5.
        counterparty = ""
        if r + 1 < sh.nrows and _seq_of(sh.cell_value(r + 1, COL_SEQ)) is None:
            counterparty = str(sh.cell_value(r + 1, COL_PAYEE)).strip()

        # Compose description: payee [; purpose if distinct]
        description_parts = [payee] if payee else []
        if purpose and purpose != payee:
            description_parts.append(purpose)
        description = " — ".join(description_parts)
        if not description:
            # Some rows (e.g. internal transfers) have no payee/purpose text —
            # fall back to the counterparty account from the trailing row so
            # the transaction is still captured.
            if r + 1 < sh.nrows and _seq_of(sh.cell_value(r + 1, COL_SEQ)) is None:
                cp = str(sh.cell_value(r + 1, COL_PAYEE)).strip()
                description = f"Transfer — {cp}" if cp else "Transfer"
            else:
                description = "Transfer"

        amount = credit - debit
        # Fold the fee into the signed amount (fees are always expenses)
        if fee:
            amount -= fee

        notes_parts = []
        if counterparty:
            notes_parts.append(f"acct {counterparty}")
        if fee:
            notes_parts.append(f"fee {fee} MKD")
        notes = " | ".join(notes_parts) or None

        out.append({
            "date": date,
            "description": macedonian_to_english(description),
            "amount": str(amount),
            "currency": "MKD",
            "merchant": macedonian_to_english(payee) or None,
            "notes": macedonian_to_english(notes),
        })
        r += 2  # skip the trailing counterparty row

    logger.info("ret_parser: parsed %d transactions (header row %d, total rows %d)",
                len(out), header_row, sh.nrows)
    return out
