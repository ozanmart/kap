"""Public exception hierarchy for the KAP SDK.

Keeping errors in a small dependency-free module lets applications import and
handle them without importing the HTTP/scraper stack.  ``scrapers.base``
re-exports these names for backwards compatibility with older integrations.
"""

from __future__ import annotations


class KapError(Exception):
    """Base exception for all KAP SDK errors."""


class KapConnectionError(KapError):
    """Raised when a KAP resource cannot be reached."""


class KapDeadlineExceeded(KapConnectionError):
    """Raised when an operation deadline expires during I/O or parsing."""


class KapValidationError(KapError):
    """Raised when a KAP response is incomplete or unsafe to accept."""


class KapNotFoundError(KapError):
    """Raised when a requested company, disclosure, or resource is absent."""


__all__ = [
    "KapError",
    "KapConnectionError",
    "KapDeadlineExceeded",
    "KapValidationError",
    "KapNotFoundError",
]
