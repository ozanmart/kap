"""KAP SDK public entrypoint.

The package root intentionally stays lightweight. Importing ``kap`` or using
the bundled ticker index must not initialize SQLite, MCP, financial parsers, or
the complete Pydantic model graph. Public classes are resolved on first use.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__version__ = "0.1.0"

_LAZY_EXPORTS = {
    "KapClient": (".client", "KapClient"),
    "AsyncKapClient": (".async_client", "AsyncKapClient"),
    "KapConfig": (".config", "KapConfig"),
    "KapError": (".exceptions", "KapError"),
    "KapConnectionError": (".exceptions", "KapConnectionError"),
    "KapDeadlineExceeded": (".exceptions", "KapDeadlineExceeded"),
    "KapValidationError": (".exceptions", "KapValidationError"),
    "KapNotFoundError": (".exceptions", "KapNotFoundError"),
    "KapToolkit": (".tools.toolkit", "KapToolkit"),
    "KapDatabase": (".storage.sqlite", "KapDatabase"),
    "Company": (".models.company", "Company"),
    "CompanyGeneralInfo": (".models.company", "CompanyGeneralInfo"),
    "Shareholder": (".models.company", "Shareholder"),
    "FreeFloatInfo": (".models.company", "FreeFloatInfo"),
    "Subsidiary": (".models.company", "Subsidiary"),
    "Disclosure": (".models.disclosure", "Disclosure"),
    "ExpectedDisclosure": (".models.disclosure", "ExpectedDisclosure"),
    "DisclosureSubject": (".models.disclosure", "DisclosureSubject"),
    "DisclosureDetail": (".models.disclosure", "DisclosureDetail"),
    "FinancialLineItem": (".models.financials", "FinancialLineItem"),
    "FinancialStatement": (".models.financials", "FinancialStatement"),
    "Indice": (".models.market", "Indice"),
    "SubSector": (".models.market", "SubSector"),
    "Sector": (".models.market", "Sector"),
    "Market": (".models.market", "Market"),
    "EventType": (".models.events", "EventType"),
    "DerivedEvent": (".models.events", "DerivedEvent"),
    "ScoredCompany": (".models.events", "ScoredCompany"),
}

__all__ = ["__version__", *_LAZY_EXPORTS, "get_companies", "search_companies", "get_company", "get_today_disclosures", "get_latest_disclosures"]


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'kap' has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))


_default_client: Any = None


def _get_default_client() -> Any:
    global _default_client
    if _default_client is None:
        _default_client = __getattr__("KapClient")()
    return _default_client


def get_companies(online: bool = False) -> list[Any]:
    """Convenience helper to retrieve BIST listed companies."""
    return _get_default_client().get_companies(online=online)


def search_companies(query: str) -> list[Any]:
    """Convenience helper to search BIST companies."""
    return _get_default_client().search_companies(query)


def get_company(ticker: str) -> Any:
    """Convenience helper to get a company by ticker."""
    return _get_default_client().get_company(ticker)


def get_today_disclosures(member_type: str = "bist_sirketleri") -> list[Any]:
    """Convenience helper to get today's live disclosures."""
    return _get_default_client().get_today_disclosures(member_type=member_type)


def get_latest_disclosures(limit: int = 50, ticker: str | None = None) -> list[Any]:
    """Convenience helper to get latest disclosures."""
    return _get_default_client().get_latest_disclosures(limit=limit, ticker=ticker)
