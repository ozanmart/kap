"""Scraper namespace with lazy exports."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS = {
    "BaseScraper": (".base", "BaseScraper"),
    "KapError": ("..exceptions", "KapError"),
    "KapConnectionError": ("..exceptions", "KapConnectionError"),
    "KapDeadlineExceeded": ("..exceptions", "KapDeadlineExceeded"),
    "KapValidationError": ("..exceptions", "KapValidationError"),
    "KapNotFoundError": ("..exceptions", "KapNotFoundError"),
    "ListingsScraper": (".listings", "ListingsScraper"),
    "get_bundled_companies": (".listings", "get_bundled_companies"),
    "DisclosuresScraper": (".disclosures", "DisclosuresScraper"),
    "CompanyGeneralScraper": (".company_general", "CompanyGeneralScraper"),
    "parse_company_general_html": (".company_general", "parse_company_general_html"),
    "FinancialsScraper": (".financials", "FinancialsScraper"),
    "parse_financial_statement_html": (".financials", "parse_financial_statement_html"),
    "CalendarScraper": (".calendar", "CalendarScraper"),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'kap.scrapers' has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
