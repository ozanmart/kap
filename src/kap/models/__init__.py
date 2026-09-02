"""Pydantic model namespace with lazy exports."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS = {
    "Company": (".company", "Company"),
    "CompanyGeneralInfo": (".company", "CompanyGeneralInfo"),
    "FreeFloatInfo": (".company", "FreeFloatInfo"),
    "Shareholder": (".company", "Shareholder"),
    "Subsidiary": (".company", "Subsidiary"),
    "Disclosure": (".disclosure", "Disclosure"),
    "ExpectedDisclosure": (".disclosure", "ExpectedDisclosure"),
    "DisclosureSubject": (".disclosure", "DisclosureSubject"),
    "DisclosureDetail": (".disclosure", "DisclosureDetail"),
    "FinancialLineItem": (".financials", "FinancialLineItem"),
    "FinancialStatement": (".financials", "FinancialStatement"),
    "Indice": (".market", "Indice"),
    "SubSector": (".market", "SubSector"),
    "Sector": (".market", "Sector"),
    "Market": (".market", "Market"),
    "EventType": (".events", "EventType"),
    "DerivedEvent": (".events", "DerivedEvent"),
    "ScoredCompany": (".events", "ScoredCompany"),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'kap.models' has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
