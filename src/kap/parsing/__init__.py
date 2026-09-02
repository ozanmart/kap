"""Parsing helpers with lazy exports."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS = {
    "html_to_text": (".html_parser", "html_to_text"),
    "clean_text": (".html_parser", "clean_text"),
    "normalize_numeric_value": (".html_parser", "normalize_numeric_value"),
    "extract_dates": (".html_parser", "extract_dates"),
    "extract_amounts": (".html_parser", "extract_amounts"),
    "detect_event_type": (".event_extractor", "detect_event_type"),
    "detect_event_types": (".event_extractor", "detect_event_types"),
    "extract_events_from_text": (".event_extractor", "extract_events_from_text"),
    "extract_multiple_events_from_text": (".event_extractor", "extract_multiple_events_from_text"),
    "score_events": (".event_extractor", "score_events"),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'kap.parsing' has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
