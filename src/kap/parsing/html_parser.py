from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any
from bs4 import BeautifulSoup


DATE_REGEX = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
AMOUNT_REGEX = re.compile(
    r"\b([\d]{1,3}(?:[\.\s][\d]{3})*(?:,[\d]{1,2})?|[\d]+(?:,[\d]{1,2})?)\s*(TL|TRY|USD|EUR)\b",
    re.IGNORECASE,
)


def html_to_text(html: str) -> str:
    """Convert HTML content into clean, readable plain text.

    Strips script, style, and noscript elements, preserves meaningful paragraph breaks,
    and strips redundant whitespace.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text("\n")
    lines = [line.strip() for line in text.splitlines()]
    clean_lines = [line for line in lines if line]
    return "\n".join(clean_lines)


def clean_text(value: str | None) -> str:
    """Normalize whitespace and clean non-breaking spaces."""
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _normalized_number_text(value: str | None) -> str | None:
    """Reduce a Turkish/European formatted number to a plain decimal string."""
    text = clean_text(value)
    if not text or text in {"-", "--", "null", "None"}:
        return None

    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]

    # Remove non-numeric characters except comma, period, minus
    text = re.sub(r"[^0-9,.\-]", "", text)
    if not text or text in {"-", ".", ","}:
        return None

    if text.count("-") > 1:
        text = text.replace("-", "")
    if "-" in text[1:]:
        text = text[0] + text[1:].replace("-", "")

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "." in text:
        parts = text.split(".")
        if not (len(parts) == 2 and len(parts[1]) <= 2 and len(parts[0]) <= 3):
            text = text.replace(".", "")

    if negative and not text.startswith("-"):
        text = f"-{text}"
    return text


def normalize_numeric_value(value: str | None) -> float | int | None:
    """Convert Turkish/European formatted numbers (e.g. '1.234.567,89' or '(1.000)') into float/int."""
    text = _normalized_number_text(value)
    if text is None:
        return None
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return None


def normalize_decimal_value(value: str | None) -> Decimal | None:
    """Parse a Turkish/European number without introducing binary float error.

    The value is built straight from the normalized text. Routing it through
    ``float`` first would lose precision on the large magnitudes that appear in
    full-unit TRY financial statements.
    """
    text = _normalized_number_text(value)
    if text is None:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def extract_dates(text: str | None) -> list[str]:
    """Extract unique DD.MM.YYYY dates from text."""
    if not text:
        return []
    seen: list[str] = []
    for match in DATE_REGEX.findall(text):
        if match not in seen:
            seen.append(match)
    return seen


def extract_amounts(text: str | None) -> list[dict[str, Any]]:
    """Extract monetary amounts and currencies (TL, TRY, USD, EUR) from text."""
    if not text:
        return []
    results: list[dict[str, Any]] = []
    for raw_val, currency in AMOUNT_REGEX.findall(text):
        normalized = raw_val.replace(" ", "").replace(".", "").replace(",", ".")
        try:
            val = float(normalized)
            results.append({"value": val, "currency": currency.upper()})
        except ValueError:
            continue
    return results
