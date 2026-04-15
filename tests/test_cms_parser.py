from pathlib import Path

from app.services.cms_parser import detect, parse

EXAMPLE = Path(__file__).parent.parent / "examples" / "CmsTransactions26032026121233.xls"


def _content() -> bytes:
    return EXAMPLE.read_bytes()


def test_detect_by_filename():
    assert detect("CmsTransactions26032026121233.xls", b"") is True


def test_detect_by_content_sniff():
    # Renamed file should still be detected via header sniff
    assert detect("statement.xls", _content()) is True


def test_detect_negative():
    assert detect("random.xlsx", b"not an xls") is False


def test_parses_all_413_transactions():
    txs = parse(_content())
    assert len(txs) == 413, f"expected 413 transactions, got {len(txs)}"


def test_parsed_shape():
    txs = parse(_content())
    first = txs[0]
    assert set(["date", "description", "amount", "currency"]).issubset(first.keys())
    # Date should be ISO
    assert first["date"].count("-") == 2
    # Amount should be parseable as number
    float(first["amount"])
    # Every row has a currency
    assert all(tx["currency"] for tx in txs)


def test_output_is_latin_only():
    """Parsed descriptions/notes must contain no Cyrillic characters."""
    txs = parse(_content())
    for tx in txs:
        for field in ("description", "merchant", "notes"):
            v = tx.get(field) or ""
            bad = [c for c in v if "\u0400" <= c <= "\u04FF"]
            assert not bad, f"Cyrillic in {field}: {v!r}"


def test_totals_match_file_header():
    # The file header reports: 400 debit orders, 13 credit orders = 413 total.
    txs = parse(_content())
    debits = [tx for tx in txs if float(tx["amount"]) < 0]
    credits = [tx for tx in txs if float(tx["amount"]) > 0]
    assert len(debits) == 400, f"expected 400 debits, got {len(debits)}"
    assert len(credits) == 13, f"expected 13 credits, got {len(credits)}"
