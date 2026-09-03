from __future__ import annotations

import json
import logging
import pkgutil
import re
import time
from functools import lru_cache
from typing import Any

from bs4 import BeautifulSoup

from ..config import KapConfig
from ..constants import (
    ENDPOINT_MEMBER_FILTER,
    ENDPOINT_SEARCH_COMBINED,
    LISTING_ROUTES,
    PUBLICLY_TRADEABLE_INDEX_CODES,
)
from ..models.company import Company
from ..models.market import Indice, Market, Sector, SubSector
from ..exceptions import KapDeadlineExceeded, KapValidationError
from .base import BaseScraper

logger = logging.getLogger("kap.scrapers.listings")

_TICKER_RE = re.compile(r"^[A-Z0-9]{2,6}$")


def _extract_next_payload_texts(html: str) -> str:
    """Extract raw Next.js server push JSON strings from HTML source."""
    payloads: list[str] = []
    marker = "self.__next_f.push(["
    i = 0
    while True:
        start = html.find(marker, i)
        if start < 0:
            break

        comma = html.find(",", start)
        if comma < 0:
            i = start + len(marker)
            continue

        quote = html.find('"', comma)
        if quote < 0:
            i = comma + 1
            continue

        j = quote + 1
        escaped = False
        chars: list[str] = []
        while j < len(html):
            ch = html[j]
            if ch == '"' and not escaped:
                break
            if ch == "\\" and not escaped:
                escaped = True
            else:
                escaped = False
            chars.append(ch)
            j += 1

        raw = "".join(chars)
        try:
            decoded = json.loads(f'"{raw}"')
        except Exception:
            decoded = raw
        payloads.append(decoded)
        i = j + 1

    return "\n".join(payloads)


def _extract_json_objects(text: str) -> list[dict[str, Any]]:
    """Extract all individual JSON dictionary objects embedded within decoded text stream."""
    decoder = json.JSONDecoder()
    rows: list[dict[str, Any]] = []
    i = 0
    n = len(text)
    seen: set[str] = set()

    while i < n:
        if text[i] != "{":
            i += 1
            continue
        try:
            obj, end = decoder.raw_decode(text[i:])
            if isinstance(obj, dict):
                row_key = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
                if row_key not in seen:
                    seen.add(row_key)
                    rows.append(obj)
                i += max(1, end)
                continue
        except Exception:
            pass
        i += 1
    return rows


def _iter_nested_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten dictionaries nested in a Next.js RSC payload.

    KAP currently serializes listings below wrappers such as ``data``,
    ``initialData`` and ``children``.  The wrapper itself is valid JSON, so a
    parser that only scans the outermost object silently loses every listing
    row.  Yielding all nested dictionaries keeps the individual listing
    parsers independent from those presentation-layer wrappers.
    """
    flattened: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            value_id = id(value)
            if value_id in seen_ids:
                return
            seen_ids.add(value_id)
            flattened.append(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for value in values:
        visit(value)
    return flattened


def _split_ticker_codes(value: str) -> list[str]:
    """Split KAP's occasional multi-code cell (for example ``A1CAP ACP``)."""
    raw = value.strip().upper()
    if not raw:
        return []
    parts = [part for part in re.split(r"[,;/\s]+", raw) if part]
    if len(parts) > 1 and all(_TICKER_RE.fullmatch(part) for part in parts):
        return parts
    return [raw]


def _absolute_url(base_url: str, path: str | None) -> str | None:
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if path.startswith("/"):
        return f"{base_url.rstrip('/')}{path}"
    return path


@lru_cache(maxsize=1)
def _bundled_index() -> tuple[tuple[Company, ...], dict[str, Company], dict[str, tuple[Company, ...]]]:
    """Load the bundled snapshot once and build exact ticker/name indexes."""
    try:
        raw = pkgutil.get_data("kap", "data/bist_companies_general.json")
        if not raw:
            return (), {}, {}
        data = json.loads(raw.decode("utf-8"))
        companies = tuple(
            Company(
                ticker=item["ticker"].upper().strip(),
                name=item.get("name", ""),
                city=item.get("city"),
                auditor=item.get("auditor"),
                company_id=item.get("company_id"),
                summary_page=item.get("summary_page"),
            )
            for item in data
            if item.get("ticker")
        )
        by_ticker = {company.ticker: company for company in companies}
        by_name: dict[str, list[Company]] = {}
        for company in companies:
            by_name.setdefault(company.name.strip().casefold(), []).append(company)
        return companies, by_ticker, {name: tuple(items) for name, items in by_name.items()}
    except Exception as e:
        logger.warning(f"Failed to load bundled companies JSON: {e}")
        return (), {}, {}


def get_bundled_companies() -> list[Company]:
    """Return the built-in offline snapshot without reparsing its JSON."""
    companies, _, _ = _bundled_index()
    return list(companies)


@lru_cache(maxsize=1)
def _member_oid_index() -> dict[str, str]:
    """Build the member OID -> ticker index once from the bundled snapshot."""
    companies, _, _ = _bundled_index()
    return {
        company.company_id: company.ticker
        for company in companies
        if company.company_id and company.ticker
    }


@lru_cache(maxsize=1)
def _search_indexes() -> tuple[dict[str, tuple[Company, ...]], dict[str, tuple[Company, ...]]]:
    """Build prefix and token indexes once; avoid scanning the registry per query."""
    companies, _, _ = _bundled_index()
    prefixes: dict[str, list[Company]] = {}
    tokens: dict[str, list[Company]] = {}
    for company in companies:
        ticker = company.ticker.upper()
        for end in range(1, len(ticker) + 1):
            prefixes.setdefault(ticker[:end], []).append(company)
        for token in re.findall(r"[A-Z0-9ÇĞİÖŞÜ]{2,}", company.name.upper()):
            tokens.setdefault(token.casefold(), []).append(company)
    return (
        {key: tuple(value) for key, value in prefixes.items()},
        {key: tuple(value) for key, value in tokens.items()},
    )


class ListingsScraper:
    """Scrapes company listings, indices, sectors, and markets directly from KAP web payloads."""

    def __init__(self, base_scraper: BaseScraper | None = None, config: KapConfig | None = None) -> None:
        self.config = config or KapConfig()
        self.base = base_scraper or BaseScraper(self.config)
        self.last_registry_metrics: dict[str, Any] = {}

    def _scrape_page_json_objects(self, route_key: str) -> list[dict[str, Any]]:
        route = LISTING_ROUTES[route_key].format(lang=self.config.lang)
        resp = self.base.request_sync("GET", route)
        def parse() -> list[dict[str, Any]]:
            html = resp.text
            payload_text = _extract_next_payload_texts(html)
            if not payload_text.strip():
                payload_text = html.replace('\\"', '"')
            return _extract_json_objects(payload_text)

        deadline = getattr(self.base, "operation_deadline", lambda: time.monotonic() + self.config.request_deadline_s)()
        return BaseScraper.run_with_deadline_sync(self.base, parse, deadline_at=deadline)

    async def _ascrape_page_json_objects(self, route_key: str) -> list[dict[str, Any]]:
        route = LISTING_ROUTES[route_key].format(lang=self.config.lang)
        resp = await self.base.request_async("GET", route)
        def parse() -> list[dict[str, Any]]:
            html = resp.text
            payload_text = _extract_next_payload_texts(html)
            if not payload_text.strip():
                payload_text = html.replace('\\"', '"')
            return _extract_json_objects(payload_text)

        deadline = getattr(self.base, "operation_deadline", lambda: time.monotonic() + self.config.request_deadline_s)()
        return await BaseScraper.run_with_deadline_async(self.base, parse, deadline_at=deadline)

    # ── Companies ────────────────────────────────────────────────────────────

    def _scrape_companies_page(self, *, deadline_at: float | None = None) -> list[Company]:
        route = LISTING_ROUTES["bist_sirketler"].format(lang=self.config.lang)
        started = time.perf_counter()
        stage = "fetch"
        timings: dict[str, Any] = {
            "operation": "registry",
            "operation_id": getattr(self.base, "last_request_metrics", {}).get("operation_id"),
            "deadline_s": self.config.request_deadline_s,
        }
        try:
            resp = self.base.request_sync(
                "GET",
                route,
                deadline_at=deadline_at,
                timing=timings,
            )
            html = resp.text
            if deadline_at is not None and time.monotonic() >= deadline_at:
                raise KapDeadlineExceeded("Registry deadline exceeded before parsing")
            stage = "parse"
            parse_started = time.perf_counter()

            def parse_and_validate() -> list[Company]:
                payload_text = _extract_next_payload_texts(html)
                rows = _extract_json_objects(payload_text) if payload_text.strip() else []
                parsed = self._parse_companies_rows(rows)
                if not parsed:
                    parsed = self._parse_companies_table(html)
                self._validate_live_registry(parsed)
                return parsed

            companies = BaseScraper.run_with_deadline_sync(self.base, parse_and_validate, deadline_at=deadline_at)
            timings["parse_s"] = round(time.perf_counter() - parse_started, 6)
            if deadline_at is not None and time.monotonic() >= deadline_at:
                raise KapDeadlineExceeded("Registry deadline exceeded after parsing")
            timings["stage"] = "ok"
            return companies
        except Exception as exc:
            timings["stage"] = stage
            timings["error"] = str(exc)
            raise
        finally:
            timings.setdefault("parse_s", 0.0)
            timings["total_s"] = round(time.perf_counter() - started, 6)
            timings.setdefault("fetch_s", timings["total_s"] - timings["parse_s"])
            self.last_registry_metrics = dict(timings)

    async def _ascrape_companies_page(self, *, deadline_at: float | None = None) -> list[Company]:
        route = LISTING_ROUTES["bist_sirketler"].format(lang=self.config.lang)
        started = time.perf_counter()
        stage = "fetch"
        timings: dict[str, Any] = {
            "operation": "registry",
            "operation_id": getattr(self.base, "last_request_metrics", {}).get("operation_id"),
            "deadline_s": self.config.request_deadline_s,
        }
        try:
            resp = await self.base.request_async(
                "GET",
                route,
                deadline_at=deadline_at,
                timing=timings,
            )
            html = resp.text
            if deadline_at is not None and time.monotonic() >= deadline_at:
                raise KapDeadlineExceeded("Registry deadline exceeded before parsing")
            stage = "parse"
            parse_started = time.perf_counter()

            def parse_and_validate() -> list[Company]:
                payload_text = _extract_next_payload_texts(html)
                rows = _extract_json_objects(payload_text) if payload_text.strip() else []
                parsed = self._parse_companies_rows(rows)
                if not parsed:
                    parsed = self._parse_companies_table(html)
                self._validate_live_registry(parsed)
                return parsed

            companies = await BaseScraper.run_with_deadline_async(self.base, parse_and_validate, deadline_at=deadline_at)
            timings["parse_s"] = round(time.perf_counter() - parse_started, 6)
            if deadline_at is not None and time.monotonic() >= deadline_at:
                raise KapDeadlineExceeded("Registry deadline exceeded after parsing")
            timings["stage"] = "ok"
            return companies
        except Exception as exc:
            timings["stage"] = stage
            timings["error"] = str(exc)
            raise
        finally:
            timings.setdefault("parse_s", 0.0)
            timings["total_s"] = round(time.perf_counter() - started, 6)
            timings.setdefault("fetch_s", timings["total_s"] - timings["parse_s"])
            self.last_registry_metrics = dict(timings)

    def _validate_live_registry(self, companies: list[Company]) -> None:
        """Reject a response that looks like an error page, partial payload, or wrong schema."""
        if len(companies) < self.config.registry_min_records:
            raise KapValidationError(
                f"Live registry returned {len(companies)} rows; minimum is {self.config.registry_min_records}"
            )
        tickers = [company.ticker for company in companies]
        invalid = [ticker for ticker in tickers if not _TICKER_RE.fullmatch(ticker)]
        if invalid:
            raise KapValidationError(f"Live registry contains invalid ticker format: {invalid[:3]}")
        if len(set(tickers)) != len(tickers):
            raise KapValidationError("Live registry contains duplicate ticker codes")
        if self.config.registry_require_company_ids:
            missing_ids = [company.ticker for company in companies if not re.fullmatch(r"[0-9a-fA-F]{32}", company.company_id or "")]
            if missing_ids:
                raise KapValidationError(f"Live registry is missing valid MKK member OIDs for {len(missing_ids)} rows")

    def get_companies(self, online: bool = False) -> list[Company]:
        """Get all BIST listed companies.

        Args:
            online: If False (default), returns the fast bundled offline snapshot (800+ tickers).
                    If True, scrapes the live BIST company registry from KAP.
        """
        if not online:
            bundled = get_bundled_companies()
            if bundled:
                return bundled

        return self._scrape_companies_page(deadline_at=time.monotonic() + self.config.request_deadline_s)

    async def aget_companies(self, online: bool = False) -> list[Company]:
        """Async get all BIST listed companies."""
        if not online:
            bundled = get_bundled_companies()
            if bundled:
                return bundled

        return await self._ascrape_companies_page(deadline_at=time.monotonic() + self.config.request_deadline_s)

    def _parse_companies_rows(self, rows: list[dict[str, Any]]) -> list[Company]:
        companies: list[Company] = []
        seen_tickers: set[str] = set()

        profile_map: dict[str, dict[str, Any]] = {}
        flat_rows = _iter_nested_dicts(rows)
        for r in flat_rows:
            mkk = str(r.get("mkkMemberOid") or "").strip()
            if mkk and ("stockCode" in r or "permaLink" in r or "kapMemberTitle" in r or "title" in r):
                profile_map[mkk] = r

        for r in flat_rows:
            stock_code_raw = str(r.get("stockCode") or "").strip()
            mkk_oid = str(r.get("mkkMemberOid") or "").strip()
            if not stock_code_raw:
                continue

            profile = profile_map.get(mkk_oid, {})
            name = (
                r.get("kapMemberTitle")
                or r.get("title")
                or profile.get("title")
                or profile.get("kapMemberTitle")
                or stock_code_raw
            )
            city = r.get("cityName") or profile.get("cityName")
            auditor = r.get("relatedMemberTitle") or profile.get("relatedMemberTitle")
            summary_page = _absolute_url(
                self.config.base_url,
                r.get("summaryPage")
                or r.get("summary_page")
                or r.get("permaLink")
                or r.get("url"),
            )

            for ticker in _split_ticker_codes(stock_code_raw):
                if ticker in seen_tickers:
                    continue
                seen_tickers.add(ticker)
                companies.append(
                    Company(
                        ticker=ticker,
                        name=name,
                        city=city,
                        auditor=auditor,
                        company_id=mkk_oid or None,
                        summary_page=summary_page
                        or f"{self.config.base_url.rstrip('/')}/{self.config.lang}/sirket/{ticker}",
                    )
                )

        companies.sort(key=lambda c: c.ticker)
        return companies

    def _parse_companies_table(self, html: str) -> list[Company]:
        """Parse the server-rendered company table when RSC payloads are absent."""
        soup = BeautifulSoup(html, "lxml")
        rows: list[dict[str, Any]] = []
        for tr in soup.select("table tr"):
            cells = tr.find_all(["td", "th"], recursive=False)
            if len(cells) < 4:
                continue
            values = [cell.get_text(" ", strip=True) for cell in cells[:4]]
            if values[0].casefold() in {"kod", "code"}:
                continue
            if not values[0] or not values[1]:
                continue
            link = cells[0].find("a", href=True)
            rows.append(
                {
                    "stockCode": values[0],
                    "kapMemberTitle": values[1],
                    "cityName": values[2] or None,
                    "relatedMemberTitle": values[3] or None,
                    "summaryPage": link.get("href") if link else None,
                }
            )
        return self._parse_companies_rows(rows)

    # ── Search & Member Lookup ───────────────────────────────────────────────

    def search(self, query: str, online: bool = False) -> list[Company]:
        """Search companies by ticker symbol or company name using KAP's search endpoint or local bundled index."""
        q = query.strip()
        if not q:
            return []

        if not online:
            return self._local_search(q)

        route = ENDPOINT_SEARCH_COMBINED.format(lang=self.config.lang)
        try:
            resp = self.base.request_sync("POST", route, json={"keyword": q})
            data = resp.json()
        except Exception:
            return self._local_search(q)

        results: list[Company] = []
        if isinstance(data, list):
            for cat in data:
                if cat.get("category") == "companyOrFunds":
                    for item in cat.get("results", []):
                        if item.get("searchType") == "C" and item.get("cmpOrFundCode"):
                            results.append(
                                Company(
                                    ticker=str(item.get("cmpOrFundCode")).upper().strip(),
                                    name=item.get("searchValue", ""),
                                    company_id=item.get("memberOrFundOid"),
                                    summary_page=f"https://www.kap.org.tr/{self.config.lang}/sirket/{item.get('cmpOrFundCode')}",
                                )
                            )
        return results or self._local_search(q)

    async def asearch(self, query: str, online: bool = False) -> list[Company]:
        """Async search companies by ticker symbol or company name."""
        q = query.strip()
        if not q:
            return []

        if not online:
            return self._local_search(q)

        route = ENDPOINT_SEARCH_COMBINED.format(lang=self.config.lang)
        try:
            resp = await self.base.request_async("POST", route, json={"keyword": q})
            data = resp.json()
        except Exception:
            return self._local_search(q)

        results: list[Company] = []
        if isinstance(data, list):
            for cat in data:
                if cat.get("category") == "companyOrFunds":
                    for item in cat.get("results", []):
                        if item.get("searchType") == "C" and item.get("cmpOrFundCode"):
                            results.append(
                                Company(
                                    ticker=str(item.get("cmpOrFundCode")).upper().strip(),
                                    name=item.get("searchValue", ""),
                                    company_id=item.get("memberOrFundOid"),
                                    summary_page=f"https://www.kap.org.tr/{self.config.lang}/sirket/{item.get('cmpOrFundCode')}",
                                )
                            )
        return results or self._local_search(q)

    def _local_search(self, query: str) -> list[Company]:
        normalized = query.strip()
        q = normalized.upper()
        companies, by_ticker, by_name = _bundled_index()
        exact = by_ticker.get(q)
        if exact:
            return [exact]
        exact_name = by_name.get(normalized.casefold())
        if exact_name:
            return list(exact_name)
        prefix_index, token_index = _search_indexes()
        starts = list(prefix_index.get(q, ()))
        query_tokens = [token.casefold() for token in re.findall(r"[A-Z0-9ÇĞİÖŞÜ]{2,}", q)]
        if query_tokens:
            token_sets = [set(token_index.get(token, ())) for token in query_tokens]
            common = set.intersection(*token_sets) if all(token_sets) else set()
            name_match = [c for c in companies if c in common and c not in starts]
        else:
            # Arbitrary substring search is inherently O(n); keep it as a
            # compatibility fallback only for fragments that are not tokens.
            name_match = [c for c in companies if q.casefold() in c.name.casefold() and c not in starts]
        return starts + name_match

    def lookup_member_oid(self, query: str) -> str | None:
        """Resolve a ticker or company name to its KAP MKK member OID."""
        q = query.strip().upper()
        # Fast path from offline dataset
        companies, by_ticker, by_name = _bundled_index()
        company = by_ticker.get(q)
        if company and company.company_id:
            return company.company_id
        exact_name = by_name.get(query.strip().casefold())
        if exact_name and exact_name[0].company_id:
            return exact_name[0].company_id

        route = ENDPOINT_MEMBER_FILTER.format(lang=self.config.lang, query=query.strip())
        try:
            resp = self.base.request_sync("GET", route)
            data = resp.json()
            if isinstance(data, list) and data:
                return data[0].get("mkkMemberOid")
        except Exception:
            pass
        return None

    def lookup_ticker(self, member_oid: str | None) -> str | None:
        """Resolve a member OID to its bundled ticker without a network call."""
        if not member_oid:
            return None
        return _member_oid_index().get(str(member_oid).strip())

    def lookup_ticker_by_title(self, company_title: str | None) -> str | None:
        """Resolve an exact KAP company title to one or more listed ticker codes."""
        if not company_title:
            return None
        _, _, by_name = _bundled_index()
        matches = by_name.get(str(company_title).strip().casefold(), ())
        tickers = sorted({company.ticker for company in matches})
        return ", ".join(tickers) if tickers else None

    def refresh_registry(self, output_path: str | None = None) -> list[Company]:
        """Fetch, validate, diff, and atomically refresh a local JSON snapshot."""
        import hashlib
        import os
        from datetime import datetime, timezone
        from pathlib import Path

        companies = self._scrape_companies_page()
        target = Path(output_path) if output_path else Path(__file__).resolve().parent.parent / "data" / "bist_companies_general.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = [company.model_dump() for company in companies]
        previous: list[dict[str, Any]] = []
        if target.exists():
            try:
                loaded = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    previous = [row for row in loaded if isinstance(row, dict)]
            except (OSError, ValueError):
                logger.warning("Could not read previous registry snapshot for diff: %s", target)
        previous_by_ticker = {
            str(row.get("ticker") or "").upper(): row
            for row in previous
            if row.get("ticker")
        }
        current_by_ticker = {company.ticker: company.model_dump() for company in companies}
        added = sorted(set(current_by_ticker) - set(previous_by_ticker))
        removed = sorted(set(previous_by_ticker) - set(current_by_ticker))
        changed = sorted(
            ticker
            for ticker in set(current_by_ticker) & set(previous_by_ticker)
            if current_by_ticker[ticker] != previous_by_ticker[ticker]
        )
        encoded = json.dumps(payload, ensure_ascii=False, indent=4).encode("utf-8")
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(encoded)
        os.replace(temporary, target)
        metadata = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": f"{self.config.base_url.rstrip('/')}{LISTING_ROUTES['bist_sirketler'].format(lang=self.config.lang)}",
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "schema_version": "1",
            "count": len(companies),
            "previous_count": len(previous),
            "diff": {
                "added": added,
                "removed": removed,
                "changed": changed,
            },
            "request_metrics": dict(self.last_registry_metrics),
        }
        metadata_target = target.with_suffix(".meta.json")
        metadata_temporary = metadata_target.with_suffix(metadata_target.suffix + ".tmp")
        metadata_temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(metadata_temporary, metadata_target)
        _bundled_index.cache_clear()
        _member_oid_index.cache_clear()
        _search_indexes.cache_clear()
        return companies

    async def alookup_member_oid(self, query: str) -> str | None:
        """Async resolve a ticker or company name to its KAP MKK member OID."""
        q = query.strip().upper()
        companies, by_ticker, by_name = _bundled_index()
        company = by_ticker.get(q)
        if company and company.company_id:
            return company.company_id
        exact_name = by_name.get(query.strip().casefold())
        if exact_name and exact_name[0].company_id:
            return exact_name[0].company_id

        route = ENDPOINT_MEMBER_FILTER.format(lang=self.config.lang, query=query.strip())
        try:
            resp = await self.base.request_async("GET", route)
            data = resp.json()
            if isinstance(data, list) and data:
                return data[0].get("mkkMemberOid")
        except Exception:
            pass
        return None

    # ── Indices ──────────────────────────────────────────────────────────────

    def get_indices(self) -> list[Indice]:
        """Fetch all Borsa Istanbul indices and their constituent stock tickers."""
        rows = self._scrape_page_json_objects("endeksler")
        return self._parse_indices_rows(rows)

    async def aget_indices(self) -> list[Indice]:
        """Async fetch all Borsa Istanbul indices and their constituent stock tickers."""
        rows = await self._ascrape_page_json_objects("endeksler")
        return self._parse_indices_rows(rows)

    def _parse_indices_rows(self, rows: list[dict[str, Any]]) -> list[Indice]:
        indices: dict[str, Indice] = {}
        for r in _iter_nested_dicts(rows):
            code = str(r.get("code") or "").strip().upper()
            if code and ("indicesNo" in r or "explanation" in r or "name" in r):
                if code not in indices:
                    indices[code] = Indice(
                        code=code,
                        name=r.get("name"),
                        indices_no=str(r.get("indicesNo")) if r.get("indicesNo") else None,
                        explanation=r.get("explanation"),
                        companies=[],
                    )
                content = r.get("content")
                if isinstance(content, list):
                    for member in content:
                        stock_code = str(member.get("stockCode") or "").strip().upper()
                        if stock_code and stock_code not in indices[code].companies:
                            indices[code].companies.append(stock_code)
        return list(indices.values())

    # ── Sectors ──────────────────────────────────────────────────────────────

    def get_sectors(self) -> list[Sector]:
        """Fetch all sectors, subsectors, and their constituent stock tickers."""
        rows = self._scrape_page_json_objects("sektorler")
        return self._parse_sectors_rows(rows)

    async def aget_sectors(self) -> list[Sector]:
        """Async fetch all sectors, subsectors, and their constituent stock tickers."""
        rows = await self._ascrape_page_json_objects("sektorler")
        return self._parse_sectors_rows(rows)

    def _parse_sectors_rows(self, rows: list[dict[str, Any]]) -> list[Sector]:
        sector_map: dict[str, Sector] = {}
        for r in _iter_nested_dicts(rows):
            sec_name = str(r.get("sectorName") or "").strip()
            if not sec_name:
                continue
            if sec_name not in sector_map:
                sector_map[sec_name] = Sector(
                    name=sec_name,
                    sector_no=str(r.get("sectorNo")) if r.get("sectorNo") else None,
                    sector_oid=r.get("sectorOid"),
                    main_sector_name=r.get("mainSectorName"),
                    sub_sectors=[],
                    companies=[],
                )
            stock_code = str(r.get("stockCode") or "").strip().upper()
            if stock_code and stock_code not in sector_map[sec_name].companies:
                sector_map[sec_name].companies.append(stock_code)
        return list(sector_map.values())

    # ── Markets ──────────────────────────────────────────────────────────────

    def get_markets(self) -> list[Market]:
        """Fetch all market segments (Yıldız Pazar, Ana Pazar, etc.) and constituent stocks."""
        rows = self._scrape_page_json_objects("pazarlar")
        return self._parse_markets_rows(rows)

    async def aget_markets(self) -> list[Market]:
        """Async fetch all market segments."""
        rows = await self._ascrape_page_json_objects("pazarlar")
        return self._parse_markets_rows(rows)

    def _parse_markets_rows(self, rows: list[dict[str, Any]]) -> list[Market]:
        market_map: dict[str, Market] = {}
        for r in _iter_nested_dicts(rows):
            m_name = str(r.get("marketName") or "").strip()
            if not m_name:
                continue
            if m_name not in market_map:
                market_map[m_name] = Market(
                    market_no=str(r.get("marketNo")) if r.get("marketNo") else None,
                    market_name=m_name,
                    market_oid=r.get("marketOid"),
                    financial_market_name=r.get("financialMarketName"),
                    companies=[],
                )
            members = r.get("marketDetailContentList")
            if isinstance(members, list):
                for mem in members:
                    stock_code = str(mem.get("stockCode") or "").strip().upper()
                    if stock_code and stock_code not in market_map[m_name].companies:
                        market_map[m_name].companies.append(stock_code)
        return list(market_map.values())
