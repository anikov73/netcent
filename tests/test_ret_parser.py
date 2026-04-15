from decimal import Decimal
from pathlib import Path

from app.services.ret_parser import detect, parse

EXAMPLE = Path(__file__).parent.parent / "examples" / "RetTransactions26032026121153.xls"


def _content() -> bytes:
    return EXAMPLE.read_bytes()


def test_detect_by_filename():
    assert detect("RetTransactions26032026121153.xls", b"") is True


def test_detect_by_content_sniff():
    assert detect("statement.xls", _content()) is True


def test_detect_negative():
    assert detect("random.xlsx", b"not an xls") is False


def test_parses_all_202_transactions():
    txs = parse(_content())
    assert len(txs) == 202, f"expected 202 transactions, got {len(txs)}"


def test_output_is_latin_only():
    """Parsed descriptions/merchants/notes must contain no Cyrillic characters."""
    txs = parse(_content())
    for tx in txs:
        for field in ("description", "merchant", "notes"):
            v = tx.get(field) or ""
            bad = [c for c in v if "\u0400" <= c <= "\u04FF"]
            assert not bad, f"Cyrillic in {field}: {v!r}"


def test_totals_match_file_header():
    """File header reports: 172 debits totalling 2,331,201.00 and 30 credits
    totalling 2,208,567.00. Our parsed signed amounts must reproduce both
    counts and totals (fees excluded — they're a separate column in the file)."""
    txs = parse(_content())

    # Back out fees to compare against the raw debit/credit totals
    debit_total = Decimal(0)
    credit_total = Decimal(0)
    debit_count = 0
    credit_count = 0
    for tx in txs:
        amt = Decimal(tx["amount"])
        fee = Decimal(0)
        if tx.get("notes") and "fee " in tx["notes"]:
            for part in tx["notes"].split("|"):
                part = part.strip()
                if part.startswith("fee "):
                    fee = Decimal(part.split()[1])
        raw = amt + fee if amt < 0 else amt  # unfold the fee we subtracted
        if raw < 0:
            debit_total += -raw
            debit_count += 1
        elif raw > 0:
            credit_total += raw
            credit_count += 1

    assert debit_count == 172, f"expected 172 debits, got {debit_count}"
    assert credit_count == 30, f"expected 30 credits, got {credit_count}"
    assert debit_total == Decimal("2331201.00"), f"debit total {debit_total}"
    assert credit_total == Decimal("2208567.00"), f"credit total {credit_total}"


def test_parsed_shape():
    txs = parse(_content())
    first = txs[0]
    assert set(["date", "description", "amount", "currency"]).issubset(first.keys())
    assert first["date"].count("-") == 2
    float(first["amount"])
    assert all(tx["currency"] == "MKD" for tx in txs)
