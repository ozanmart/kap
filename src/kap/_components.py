"""Lazy scraper component construction shared by sync and async clients."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import Any

from .config import KapConfig


_COMPONENTS: dict[str, tuple[str, str]] = {
    "listings": (".scrapers.listings", "ListingsScraper"),
    "disclosures": (".scrapers.disclosures", "DisclosuresScraper"),
    "company_general": (".scrapers.company_general", "CompanyGeneralScraper"),
    "financials": (".scrapers.financials", "FinancialsScraper"),
    "calendar": (".scrapers.calendar", "CalendarScraper"),
}


def create_component(
    name: str,
    base_scraper: Any,
    config: KapConfig,
    *,
    resolve: Callable[[str], Any] | None = None,
) -> Any:
    """Create one scraper lazily and wire cross-component dependencies.

    Scrapers remain import-on-demand so ``import kap`` and offline registry
    lookups stay lightweight.  ``resolve`` is supplied by a client to reuse
    its component cache when the calendar needs listing lookups.
    """
    try:
        module_name, class_name = _COMPONENTS[name]
    except KeyError as exc:
        raise AttributeError(f"Unknown KAP component: {name}") from exc

    component_class = getattr(import_module(module_name, __package__), class_name)
    component = component_class(base_scraper, config)
    if name == "calendar":
        listings = resolve("listings") if resolve is not None else None
        if listings is not None:
            component.set_ticker_lookup(listings.lookup_ticker)
            component.set_company_title_lookup(listings.lookup_ticker_by_title)
    return component


__all__ = ["create_component"]
