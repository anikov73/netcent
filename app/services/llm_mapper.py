"""Extract transactions from any bank statement file using an LLM."""
import json
import logging
import time
from io import BytesIO

import pandas as pd

from app.config import settings

logger = logging.getLogger(__name__)


# ── File reading ──────────────────────────────────────────────────────────────

def _read_raw(content: bytes, filename: str) -> pd.DataFrame:
    ext = filename.rsplit(".", 1)[-1].lower()
    logger.debug("_read_raw: filename=%s  ext=%s  size=%d bytes", filename, ext, len(content))
    buf = BytesIO(content)
    if ext == "csv":
        for sep in [",", ";", "\t"]:
            try:
                df = pd.read_csv(buf, sep=sep, dtype=str, header=None)
                if len(df.columns) > 1:
                    logger.debug("CSV read OK with sep=%r  shape=%s", sep, df.shape)
                    return df
                buf.seek(0)
            except Exception:
                buf.seek(0)
        return pd.read_csv(buf, dtype=str, header=None)
    elif ext in ("xlsx", "xls"):
        df = pd.read_excel(buf, dtype=str, header=None)
        logger.debug("Excel read OK  shape=%s", df.shape)
        return df
    raise ValueError(f"Unsupported file format: {ext}")


def _file_to_text(df: pd.DataFrame, max_rows: int = 800) -> str:
    """Convert raw DataFrame to a compact text table for the LLM."""
    lines = []
    count = 0
    empty_skipped = 0
    for _, row in df.iterrows():
        cells = [str(v).strip() if str(v) not in ("nan", "None") else "" for v in row]
        if all(c == "" for c in cells):
            empty_skipped += 1
            continue
        lines.append("\t".join(cells))
        count += 1
        if count >= max_rows:
            lines.append(f"... (truncated — file has {len(df)} total rows)")
            break
    logger.debug(
        "_file_to_text: %d non-empty rows included, %d empty rows skipped, text length=%d chars",
        count, empty_skipped, sum(len(l) for l in lines),
    )
    return "\n".join(lines)


# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a bank statement parser. You receive the raw text of a spreadsheet and must extract \
every financial transaction from it.

Return a JSON object with one key "transactions" containing an array. Each element must have:
  - "date": ISO date string YYYY-MM-DD
  - "description": the merchant / payee / purpose text
  - "amount": number — negative for money out (expenses/debits), positive for money in (income/credits)
  - "currency": 3-letter ISO code (e.g. "MKD", "EUR", "USD", "CHF"). Default to "MKD" if unclear.

Rules:
- Skip header rows, summary rows, balance rows, and empty rows — only include actual transactions.
- IGNORE columns named "Состојба Локална валута", "Состојба", or any column that represents a \
  running balance — never use balance values as transaction amounts.
- If separate debit and credit columns exist: debit → negative amount, credit → positive amount. \
  Specifically: "Задолжување" (Macedonian for "debit/charged") → negative (money out); \
  "Побарување" (Macedonian for "credit/received") → positive (money in). \
  A row will have a value in one of these columns and be empty in the other — use whichever is non-empty.
- Currency selection: if a row contains amounts in multiple currencies, always use the MKD amount. \
  If no currency is indicated next to an amount, default to "MKD".
- If an amount column has a sign or directional indicator (e.g. "- 19,99"), preserve the sign.
- Amounts may use European formatting (1.234,56 means 1234.56) — convert to plain numbers.
- The file may be in Macedonian (Cyrillic). Transliterate or translate descriptions to English/Latin. \
  For example: "Траен налог" → "Standing order", "Водовод" → "Water utility", \
  "Сметка" → "Bill", "Плаќање" → "Payment". Merchant names: keep as-is but in Latin letters.
- Return ONLY the JSON object, no markdown, no explanation.
"""


# ── Main extraction function ──────────────────────────────────────────────────

async def extract_transactions(content: bytes, filename: str) -> list[dict]:
    """
    Send the entire file to OpenAI and get back a list of parsed transactions.
    Each item: {date: str, description: str, amount: float, currency: str}
    """
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not configured")

    from openai import AsyncOpenAI

    logger.info("━" * 60)
    logger.info("OPENAI EXTRACTION START  file=%s  size=%d bytes", filename, len(content))

    # ── Step 1: read file ──
    logger.info("  [1/4] Reading file …")
    t0 = time.perf_counter()
    df = _read_raw(content, filename)
    logger.info("        Done in %.0fms  shape=%s", (time.perf_counter() - t0) * 1000, df.shape)

    # ── Step 2: convert to text ──
    logger.info("  [2/4] Converting to text table …")
    t0 = time.perf_counter()
    file_text = _file_to_text(df)
    text_lines = file_text.count("\n") + 1
    text_chars = len(file_text)
    logger.info("        Done in %.0fms  lines=%d  chars=%d", (time.perf_counter() - t0) * 1000, text_lines, text_chars)

    # ── Step 3: build & log the prompt ──
    logger.info("  [3/4] Sending to OpenAI (model=%s) …", settings.openai_model)
    user_message = f"File: {filename}\n\n{file_text}"
    logger.debug("── OPENAI REQUEST ──────────────────────────────────────────")
    logger.debug("  model    : %s", settings.openai_model)
    logger.debug("  sys_chars: %d", len(SYSTEM_PROMPT))
    logger.debug("  usr_chars: %d", len(user_message))
    logger.debug("── SYSTEM PROMPT (truncated to 500 chars) ──────────────────")
    logger.debug("%s", SYSTEM_PROMPT[:500])
    logger.debug("── USER MESSAGE (first 1000 chars) ─────────────────────────")
    logger.debug("%s", user_message[:1000])
    if len(user_message) > 1000:
        logger.debug("  … (%d more chars) …", len(user_message) - 1000)
    logger.debug("────────────────────────────────────────────────────────────")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    t0 = time.perf_counter()

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    elapsed = (time.perf_counter() - t0) * 1000
    usage = response.usage

    # ── Step 4: log & parse response ──
    logger.info("  [4/4] Response received in %.0fms", elapsed)
    logger.info("        tokens: prompt=%d  completion=%d  total=%d",
                usage.prompt_tokens, usage.completion_tokens, usage.total_tokens)

    raw = response.choices[0].message.content
    logger.debug("── OPENAI RESPONSE (first 2000 chars) ──────────────────────")
    logger.debug("%s", raw[:2000])
    if len(raw) > 2000:
        logger.debug("  … (%d more chars) …", len(raw) - 2000)
    logger.debug("────────────────────────────────────────────────────────────")

    result = json.loads(raw)
    transactions = result.get("transactions", [])

    logger.info("OPENAI EXTRACTION DONE  transactions=%d  total_time=%.0fms",
                len(transactions), elapsed)
    logger.info("━" * 60)

    if transactions:
        logger.debug("First 3 extracted transactions:")
        for tx in transactions[:3]:
            logger.debug("  %s", tx)

    return transactions
