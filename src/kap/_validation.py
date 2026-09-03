"""Small runtime validators for the public client surface."""

from __future__ import annotations

from datetime import date
import re
from typing import Any

from .exceptions import KapValidationError


def require_text(value: Any, field: str) -> str:
    """Return trimmed text or raise a user-facing validation error."""
    if not isinstance(value, str) or not value.strip():
        raise KapValidationError(f"{field} must be a non-empty string")
    return value.strip()


def normalize_ticker(value: Any, field: str = "ticker") -> str:
    """Normalize a ticker-like value without silently accepting empty input."""
    return require_text(value, field).upper()


def is_hex_token(value: str) -> bool:
    """Return whether a string is composed solely of hexadecimal characters."""
    return bool(re.fullmatch(r"[0-9a-fA-F]+", value))


def positive_int(value: Any, field: str, *, maximum: int | None = None) -> int:
    """Validate a bounded positive integer used by public SDK methods."""
    if isinstance(value, bool):
        raise KapValidationError(f"{field} must be an integer")
    if isinstance(value, float) and not value.is_integer():
        raise KapValidationError(f"{field} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise KapValidationError(f"{field} must be an integer") from exc
    if result < 1:
        raise KapValidationError(f"{field} must be greater than zero")
    if maximum is not None and result > maximum:
        raise KapValidationError(f"{field} must be less than or equal to {maximum}")
    return result


def disclosure_range(value: Any, field: str = "range_days") -> int:
    """Validate KAP's company-feed window: 1-365 days, or a four-digit year.

    KAP answers any other value with an empty list instead of an error, so a
    366-day request is indistinguishable from a company that filed nothing.
    Reject it here rather than reporting the empty result as a real answer.
    """
    result = positive_int(value, field)
    current_year = date.today().year
    if result <= 365 or 2000 <= result <= current_year:
        return result
    raise KapValidationError(
        f"{field} must be 1-365 days or a four-digit year between 2000 and {current_year}; "
        f"KAP returns no rows for {result}"
    )


def validate_date_range(from_date: date | None, to_date: date | None) -> None:
    """Reject an inverted historical query before it reaches KAP."""
    if from_date is not None and not isinstance(from_date, date):
        raise KapValidationError("from_date must be a datetime.date")
    if to_date is not None and not isinstance(to_date, date):
        raise KapValidationError("to_date must be a datetime.date")
    if from_date is not None and to_date is not None and from_date > to_date:
        raise KapValidationError("from_date cannot be later than to_date")


__all__ = [
    "disclosure_range",
    "is_hex_token",
    "normalize_ticker",
    "positive_int",
    "require_text",
    "validate_date_range",
]
