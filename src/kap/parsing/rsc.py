"""Small, dependency-free helpers for Next.js React Server Component payloads.

KAP pages currently render the useful data twice: once as a human-facing HTML
tree and once as structured ``self.__next_f.push`` records.  The latter is the
stable source for scalar metadata and attachment identities, while HTML stays
as a fallback for older pages and fixtures.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator


def extract_next_payload_texts(html: str) -> str:
    """Decode the string payloads emitted by ``self.__next_f.push``."""
    if not html:
        return ""
    payloads: list[str] = []
    marker = "self.__next_f.push(["
    cursor = 0
    while True:
        start = html.find(marker, cursor)
        if start < 0:
            break
        comma = html.find(",", start + len(marker))
        if comma < 0:
            cursor = start + len(marker)
            continue
        quote = html.find('"', comma)
        if quote < 0:
            cursor = comma + 1
            continue

        end = quote + 1
        escaped = False
        chars: list[str] = []
        while end < len(html):
            char = html[end]
            if char == '"' and not escaped:
                break
            chars.append(char)
            if char == "\\" and not escaped:
                escaped = True
            else:
                escaped = False
            end += 1
        raw = "".join(chars)
        try:
            payloads.append(json.loads(f'"{raw}"'))
        except (TypeError, ValueError, json.JSONDecodeError):
            payloads.append(raw)
        cursor = end + 1
    return "\n".join(payloads)


def extract_json_objects(text: str) -> list[dict[str, Any]]:
    """Extract complete JSON objects embedded in an RSC text stream."""
    decoder = json.JSONDecoder()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    cursor = 0
    while cursor < len(text):
        if text[cursor] != "{":
            cursor += 1
            continue
        try:
            obj, end = decoder.raw_decode(text[cursor:])
        except (TypeError, ValueError, json.JSONDecodeError):
            cursor += 1
            continue
        if isinstance(obj, dict):
            fingerprint = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
            if fingerprint not in seen:
                seen.add(fingerprint)
                rows.append(obj)
            cursor += max(end, 1)
        else:
            cursor += max(end, 1)
    return rows


def iter_nested_dicts(values: Any) -> Iterator[dict[str, Any]]:
    """Yield each nested dictionary once from decoded RSC objects."""
    seen: set[int] = set()

    def visit(value: Any) -> Iterator[dict[str, Any]]:
        if isinstance(value, dict):
            marker = id(value)
            if marker in seen:
                return
            seen.add(marker)
            yield value
            for child in value.values():
                yield from visit(child)
        elif isinstance(value, list):
            for child in value:
                yield from visit(child)

    yield from visit(values)


def normalize_rsc_key(value: Any) -> str:
    """Normalize RSC item keys/names for tolerant alias matching."""
    return re.sub(r"[^a-z0-9çğıöşü]+", "", str(value or "").casefold())


def unwrap_rsc_value(value: Any) -> Any:
    """Unwrap KAP's ``itemObject.value`` and similar value wrappers."""
    current = value
    seen: set[int] = set()
    while isinstance(current, dict):
        marker = id(current)
        if marker in seen:
            break
        seen.add(marker)
        for key in ("value", "itemValue", "text", "displayValue"):
            if key in current and current[key] is not None:
                current = current[key]
                break
        else:
            return current
    return current


def iter_rsc_items(html: str) -> Iterator[dict[str, Any]]:
    """Yield normalized ``itemKey/itemName/itemObject`` records."""
    payload = extract_next_payload_texts(html)
    if not payload.strip():
        return
    for row in iter_nested_dicts(extract_json_objects(payload)):
        if not any(key in row for key in ("itemKey", "itemName", "itemObject")):
            continue
        key = row.get("itemKey") or row.get("key") or row.get("name")
        name = row.get("itemName") or row.get("label") or row.get("title")
        if key is None and name is None:
            continue
        raw_value = row.get("itemObject", row.get("value"))
        yield {
            "item_key": str(key or ""),
            "item_name": str(name or ""),
            "value": unwrap_rsc_value(raw_value),
            "raw": row,
        }
