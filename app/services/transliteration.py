"""Deterministic Macedonian → English conversion for parsed bank data.

Two passes:
  1. Replace known Macedonian banking phrases with their English equivalents
     (longest match first, so specific phrases win over general ones).
  2. Transliterate any remaining Cyrillic characters to Latin using the
     standard Macedonian scheme.

No AI calls. Designed to be idempotent on already-Latin input.
"""

from __future__ import annotations

import re

# --- Macedonian Cyrillic → Latin (official transliteration) ------------------

_CHAR_MAP = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D",
    "Ѓ": "Gj", "Е": "E", "Ж": "Zh", "З": "Z", "Ѕ": "Dz",
    "И": "I", "Ј": "J", "К": "K", "Л": "L", "Љ": "Lj",
    "М": "M", "Н": "N", "Њ": "Nj", "О": "O", "П": "P",
    "Р": "R", "С": "S", "Т": "T", "Ќ": "Kj", "У": "U",
    "Ф": "F", "Х": "H", "Ц": "C", "Ч": "Ch", "Џ": "Dj",
    "Ш": "Sh",
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
    "ѓ": "gj", "е": "e", "ж": "zh", "з": "z", "ѕ": "dz",
    "и": "i", "ј": "j", "к": "k", "л": "l", "љ": "lj",
    "м": "m", "н": "n", "њ": "nj", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "ќ": "kj", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "џ": "dj",
    "ш": "sh",
}


def _transliterate(text: str) -> str:
    return "".join(_CHAR_MAP.get(ch, ch) for ch in text)


# --- Phrase translations -----------------------------------------------------
#
# Ordered longest-first so "Провизија за траен налог за" matches before the
# shorter "Провизија за" or "Траен налог".

_PHRASES: list[tuple[str, str]] = [
    # Long specific phrases
    ("Провизија за траен налог за", "Standing-order fee for"),
    ("Лично банкарство – месечен надомест", "Personal banking – monthly fee"),
    ("Лично банкарство - месечен надомест", "Personal banking - monthly fee"),
    ("Ibank трансфер од ТРС", "Ibank transfer from current account"),
    ("Ibank трансфер на ТРС", "Ibank transfer to current account"),
    ("Ibank трансфер", "Ibank transfer"),
    # Shorter bank-term phrases
    ("Траен налог", "Standing order"),
    ("Провизија за", "Fee for"),
    ("Провизија", "Fee"),
    ("Останати плаќања", "Other payments"),
    ("Назив и седиште на примачот", "Recipient name and address"),
    ("Цел на дознаката", "Payment purpose"),
    ("Број на налози", "Order count"),
    ("Број на сметката", "Account number"),
    ("Број на картичката", "Card number"),
    ("Датум на трансакција", "Transaction date"),
    ("Датум на книжењето", "Booking date"),
    ("Задолжување", "Debit"),
    ("Побарување", "Credit"),
    ("Состојба", "Balance"),
    ("Износ", "Amount"),
    ("Вкупно", "Total"),
    ("Промет", "Turnover"),
    ("Опис", "Description"),
]


def macedonian_to_english(text: str | None) -> str | None:
    """Translate known banking phrases, then transliterate remaining Cyrillic.

    Returns the original input if it's falsy. Whitespace is collapsed at the
    end for tidiness.
    """
    if not text:
        return text
    s = text
    for cyr, eng in _PHRASES:
        if cyr in s:
            s = s.replace(cyr, eng)
    s = _transliterate(s)
    # Normalise whitespace that may have expanded during phrase replacement
    s = re.sub(r"[ \t]+", " ", s).strip()
    return s
