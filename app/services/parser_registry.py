"""Registry of deterministic (non-AI) file parsers.

Each entry bundles a human-readable label, a detector that inspects the
filename + raw bytes, and a parser that returns a list of dicts compatible
with `import_from_parsed`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.services import cms_parser, ret_parser


@dataclass(frozen=True)
class ParserSpec:
    key: str
    label: str
    description: str
    detect: Callable[[str, bytes], bool]
    parse: Callable[[bytes], list[dict]]


PARSERS: list[ParserSpec] = [
    ParserSpec(
        key="cms",
        label="CMS card transactions",
        description="Card-transaction export (e.g. CmsTransactions*.xls).",
        detect=cms_parser.detect,
        parse=cms_parser.parse,
    ),
    ParserSpec(
        key="ret",
        label="Ret account transactions",
        description="Retail account statement (e.g. RetTransactions*.xls).",
        detect=ret_parser.detect,
        parse=ret_parser.parse,
    ),
]


def detect_format(filename: str, content: bytes) -> ParserSpec | None:
    """Return the first parser spec that matches, or None if unknown."""
    for spec in PARSERS:
        try:
            if spec.detect(filename, content):
                return spec
        except Exception:
            continue
    return None


def get_parser(key: str) -> ParserSpec | None:
    for spec in PARSERS:
        if spec.key == key:
            return spec
    return None
