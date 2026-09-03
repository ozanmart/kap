from __future__ import annotations

import asyncio
import datetime
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from ._components import create_component
from .cache import CacheManager
from .client import (
    _cache_key,
    _dump,
    _dump_all,
    _financial_period_matches,
    _financial_selector_years,
    _is_financial_statement_disclosure,
    _load,
    _load_all,
)
from .config import KapConfig
from .constants import SUBJECT_OID_FINANCIAL_REPORT
from .exceptions import KapDeadlineExceeded, KapNotFoundError, KapValidationError
from .scrapers.base import BaseScraper
from ._validation import (
    disclosure_range,
    is_hex_token,
    normalize_ticker,
    positive_int,
    require_text,
    validate_date_range,
)

if TYPE_CHECKING:
    from .models.company import Company, CompanyGeneralInfo
    from .models.disclosure import Disclosure, DisclosureDetail, DisclosureSubject, ExpectedDisclosure
    from .models.events import DerivedEvent, ScoredCompany
    from .models.financials import FinancialStatement
    from .models.market import Indice, Market, Sector

class AsyncKapClient:
    """Asynchronous client for KAP (Public Disclosure Platform) and Borsa Istanbul."""

    def __init__(
        self,
        config: KapConfig | None = None,
        db_path: Path | str | None = None,
    ) -> None:
        self.config = config or KapConfig()
        self.base_scraper = BaseScraper(self.config)
        self.cache = CacheManager(
            cache_dir=self.config.cache_dir,
            enabled=self.config.enable_cache,
            stale_retention_s=self.config.stale_max_age_s,
            stale_if_error=self.config.stale_if_error,
            stale_while_revalidate=self.config.stale_while_revalidate,
        )
        self._components: dict[str, Any] = {}
        self._db_path = db_path
        self._db: Any = None
        self.last_request_metrics: dict[str, Any] = {}
        self._client_operation_deadline: float | None = None

    def _get_component(self, name: str) -> Any:
        """Import only the scraper required by the current async operation."""
        if name in self._components:
            return self._components[name]
        component = create_component(name, self.base_scraper, self.config, resolve=self._get_component)
        self._components[name] = component
        return component

    @property
    def listings(self) -> Any:
        return self._get_component("listings")

    @property
    def disclosures(self) -> Any:
        return self._get_component("disclosures")

    @property
    def company_general(self) -> Any:
        return self._get_component("company_general")

    @property
    def financials(self) -> Any:
        return self._get_component("financials")

    @property
    def calendar(self) -> Any:
        return self._get_component("calendar")

    @property
    def db(self) -> Any:
        if self._db is None and self._db_path:
            from .storage.sqlite import KapDatabase
            self._db = KapDatabase(self._db_path)
        return self._db

    def _begin_operation(self, name: str) -> None:
        self.base_scraper.begin_operation(name)
        self._client_operation_deadline = self.base_scraper.operation_deadline()
        self.last_request_metrics = dict(self.base_scraper.last_request_metrics)

    def _ensure_operation_budget(self) -> None:
        deadline = self._client_operation_deadline
        if deadline is not None and time.monotonic() >= deadline:
            self.last_request_metrics = {
                **self.base_scraper.last_request_metrics,
                "stage": "deadline",
                "error": "client operation deadline exceeded",
            }
            raise KapDeadlineExceeded("Client operation deadline exceeded")

    def _capture_metrics(self, component: Any | None = None) -> None:
        source = getattr(component, "last_registry_metrics", None) if component is not None else None
        self.last_request_metrics = dict(source or self.base_scraper.last_request_metrics)

    async def _cached_async(
        self,
        key: str,
        fetch: Callable[[], Awaitable[Any]],
        *,
        expire: int | None,
        force_refresh: bool = False,
        refresh_async: bool = False,
        enforce_deadline: bool = True,
    ) -> Any:
        if enforce_deadline:
            self._ensure_operation_budget()
        try:
            result = await self.cache.cached_call_async(
                key,
                fetch,
                expire=expire,
                force_refresh=force_refresh,
                refresh_async=refresh_async,
            )
        except Exception as exc:
            # Match the sync client: request_sync/request_async publish the
            # terminal metrics before the cache layer re-raises the failure.
            base_metrics = dict(self.base_scraper.last_request_metrics)
            client_metrics = dict(self.last_request_metrics)
            same_operation = (
                base_metrics.get("operation_id")
                and base_metrics.get("operation_id") == client_metrics.get("operation_id")
            )
            if client_metrics.get("stage") == "deadline" and same_operation:
                pass
            elif same_operation and (
                base_metrics.get("stage") != "cache_lookup"
                or int(base_metrics.get("attempts", 0)) > 0
            ):
                self.last_request_metrics = base_metrics
            else:
                metrics = client_metrics or base_metrics
                metrics.update(stage="error", error=f"{type(exc).__name__}: {exc}")
                self.last_request_metrics = metrics
            raise
        if enforce_deadline:
            self._ensure_operation_budget()
        return result

    async def aclose(self) -> None:
        await self.base_scraper.aclose()
        self.cache.close()
        if self._db:
            self._db.close()

    async def __aenter__(self) -> AsyncKapClient:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.aclose()

    def clear_cache(self) -> None:
        self.cache.clear()

    def _cache_key(self, namespace: str, **parts: Any) -> str:
        return _cache_key(self.config, namespace, **parts)

    # ── Companies ────────────────────────────────────────────────────────────

    async def get_companies(
        self,
        online: bool = False,
        force_refresh: bool = False,
        refresh_async: bool = False,
    ) -> list[Company]:
        """Async fetch list of all BIST companies."""
        from .models.company import Company

        self._begin_operation("companies")
        key = self._cache_key("companies", online=online, lang=self.config.lang)

        async def fetch() -> list[dict[str, Any]]:
            companies = await self.listings.aget_companies(online=online)
            self.last_request_metrics = dict(getattr(self.listings, "last_registry_metrics", self.base_scraper.last_request_metrics))
            return _dump_all(companies)

        raw = await self._cached_async(
            key,
            fetch,
            expire=self.config.cache_expiry_companies,
            force_refresh=force_refresh,
            refresh_async=refresh_async,
            enforce_deadline=online,
        )
        companies = _load_all(Company, raw)
        if self.last_request_metrics.get("operation") != "registry":
            self._capture_metrics()
        if self.db and companies:
            self.db.save_companies(companies)
        return companies

    async def search_companies(self, query: str, online: bool = False) -> list[Company]:
        """Async search companies by ticker or name fragment."""
        self._begin_operation("company_search")
        query = require_text(query, "query")
        result = await self.listings.asearch(query, online=online)
        self._capture_metrics()
        return result

    async def get_company(self, ticker: str, online: bool = False) -> Company | None:
        """Async retrieve a specific company by ticker code."""
        self._begin_operation("company_lookup")
        t = normalize_ticker(ticker)
        results = await self.listings.asearch(t, online=online)
        for r in results:
            if r.ticker == t:
                return r
        return None

    async def _resolve_member_oid(self, ticker_or_oid: str) -> str:
        clean = require_text(ticker_or_oid, "ticker_or_oid")
        if len(clean) >= 20 and is_hex_token(clean):
            return clean
        oid = await self.listings.alookup_member_oid(clean)
        if oid:
            return oid
        return clean

    async def get_company_general_info(self, ticker_or_oid: str, force_refresh: bool = False) -> CompanyGeneralInfo:
        """Async get comprehensive company profile."""
        from .models.company import CompanyGeneralInfo

        self._begin_operation("company_general")
        oid = await self._resolve_member_oid(ticker_or_oid)
        key = self._cache_key("company-general", oid=oid, lang=self.config.lang)

        async def fetch() -> dict[str, Any]:
            return _dump(await self.company_general.aget_company_general_info(oid))

        raw = await self._cached_async(
            key,
            fetch,
            expire=self.config.cache_expiry_company_general,
            force_refresh=force_refresh,
        )
        self._capture_metrics()
        info = _load(CompanyGeneralInfo, raw)
        if not info.company_title:
            raise KapNotFoundError(f"No company profile found for '{ticker_or_oid}'")
        if not info.ticker:
            requested = ticker_or_oid.strip().upper()
            ticker = requested if re.fullmatch(r"[A-Z0-9]{2,10}", requested) else self.listings.lookup_ticker(oid)
            if ticker:
                info = info.model_copy(update={"ticker": ticker})
        return info

    # ── Market Taxonomy ──────────────────────────────────────────────────────

    async def get_indices(self, force_refresh: bool = False) -> list[Indice]:
        """Async get all BIST indices."""
        from .models.market import Indice

        self._begin_operation("indices")
        key = self._cache_key("indices", lang=self.config.lang)
        async def fetch() -> list[dict[str, Any]]:
            return _dump_all(await self.listings.aget_indices())
        raw = await self._cached_async(
            key, fetch, expire=self.config.cache_expiry_indices, force_refresh=force_refresh
        )
        self._capture_metrics()
        return _load_all(Indice, raw)

    async def get_sectors(self, force_refresh: bool = False) -> list[Sector]:
        """Async get all sectors."""
        from .models.market import Sector

        self._begin_operation("sectors")
        key = self._cache_key("sectors", lang=self.config.lang)
        async def fetch() -> list[dict[str, Any]]:
            return _dump_all(await self.listings.aget_sectors())
        raw = await self._cached_async(
            key, fetch, expire=self.config.cache_expiry_sectors, force_refresh=force_refresh
        )
        self._capture_metrics()
        return _load_all(Sector, raw)

    async def get_markets(self, force_refresh: bool = False) -> list[Market]:
        """Async get all market segments."""
        from .models.market import Market

        self._begin_operation("markets")
        key = self._cache_key("markets", lang=self.config.lang)
        async def fetch() -> list[dict[str, Any]]:
            return _dump_all(await self.listings.aget_markets())
        raw = await self._cached_async(
            key, fetch, expire=self.config.cache_expiry_markets, force_refresh=force_refresh
        )
        self._capture_metrics()
        return _load_all(Market, raw)

    # ── Disclosures ──────────────────────────────────────────────────────────

    async def get_today_disclosures(
        self,
        member_type: str = "bist_sirketleri",
        disclosure_types: list[str] | None = None,
        force_refresh: bool = False,
        refresh_async: bool = False,
    ) -> list[Disclosure]:
        """Async get today's live disclosures."""
        from .models.disclosure import Disclosure

        self._begin_operation("today_disclosures")
        key = self._cache_key(
            "today",
            member_type=member_type,
            disclosure_types=sorted(disclosure_types or []),
            lang=self.config.lang,
        )
        async def fetch() -> list[dict[str, Any]]:
            return _dump_all(await self.disclosures.aget_today_disclosures(
                member_type=member_type,
                disclosure_types=disclosure_types,
            ))

        raw = await self._cached_async(
            key,
            fetch,
            expire=self.config.cache_expiry_today,
            force_refresh=force_refresh,
            refresh_async=refresh_async,
        )
        self._capture_metrics()
        disclosures = _load_all(Disclosure, raw)
        if self.db and disclosures:
            self.db.save_disclosures(disclosures)
        return disclosures

    async def get_latest_disclosures(
        self,
        limit: int = 50,
        ticker: str | None = None,
        disclosure_types: list[str] | None = None,
        force_refresh: bool = False,
        refresh_async: bool = False,
    ) -> list[Disclosure]:
        """Async get latest disclosures."""
        from .models.disclosure import Disclosure

        self._begin_operation("latest_disclosures")
        limit = positive_int(limit, "limit", maximum=200)
        ticker = normalize_ticker(ticker) if ticker else None
        key = self._cache_key(
            "latest",
            limit=limit,
            ticker=(ticker or "").upper(),
            disclosure_types=sorted(disclosure_types or []),
            lang=self.config.lang,
        )
        async def fetch() -> list[dict[str, Any]]:
            if not ticker:
                disclosures = await self.disclosures.aget_latest_disclosures(
                    limit=limit,
                    ticker=None,
                    disclosure_types=disclosure_types,
                )
            else:
                oid = await self._resolve_member_oid(ticker)
                disclosures = await self.disclosures.aget_company_disclosures(
                    member_oid=oid,
                    notification_type="ALL",
                    range_value=365,
                    limit=max(50, limit * 5),
                )
                if not disclosures:
                    disclosures = await self.disclosures.aget_company_disclosures(
                        member_oid=oid,
                        notification_type="ALL",
                        range_value=3650,
                        limit=max(50, limit * 5),
                    )
                if disclosure_types:
                    wanted = {item.upper() for item in disclosure_types}
                    disclosures = [
                        row
                        for row in disclosures
                        if (row.disclosure_type or "").upper() in wanted
                    ]
                disclosures.sort(key=lambda row: row.disclosure_index, reverse=True)
                disclosures = disclosures[: max(0, int(limit))]
            return _dump_all(disclosures)

        raw = await self._cached_async(
            key,
            fetch,
            expire=self.config.cache_expiry_latest,
            force_refresh=force_refresh,
            refresh_async=refresh_async,
        )
        self._capture_metrics()
        disclosures = _load_all(Disclosure, raw)
        if self.db and disclosures:
            self.db.save_disclosures(disclosures)
        return disclosures

    async def get_company_disclosures(
        self,
        ticker_or_oid: str,
        notification_type: str = "ALL",
        range_days: int = 365,
        limit: int = 50,
        force_refresh: bool = False,
        refresh_async: bool = False,
    ) -> list[Disclosure]:
        """Async get historical disclosures for a specific company."""
        from .models.disclosure import Disclosure

        self._begin_operation("company_disclosures")
        range_days = disclosure_range(range_days)
        limit = positive_int(limit, "limit", maximum=200)
        oid = await self._resolve_member_oid(ticker_or_oid)
        key = self._cache_key(
            "company-disclosures",
            oid=oid,
            notification_type=notification_type.upper(),
            range_days=range_days,
            limit=limit,
            lang=self.config.lang,
        )
        async def fetch() -> list[dict[str, Any]]:
            return _dump_all(await self.disclosures.aget_company_disclosures(
                member_oid=oid,
                notification_type=notification_type,
                range_value=range_days,
                limit=limit,
            ))

        raw = await self._cached_async(
            key,
            fetch,
            expire=self.config.cache_expiry_default,
            force_refresh=force_refresh,
            refresh_async=refresh_async,
        )
        self._capture_metrics()
        disclosures = _load_all(Disclosure, raw)
        if self.db and disclosures:
            self.db.save_disclosures(disclosures)
        return disclosures

    async def get_historical_disclosures(
        self,
        ticker_or_oid: str,
        from_date: datetime.date | None = None,
        to_date: datetime.date | None = None,
        disclosure_class: str = "FR",
        subject_oid: str | None = None,
        force_refresh: bool = False,
        refresh_async: bool = False,
    ) -> list[Disclosure]:
        """Async query historical disclosures via criteria POST endpoint."""
        from .models.disclosure import Disclosure

        self._begin_operation("historical_disclosures")
        validate_date_range(from_date, to_date)
        oid = await self._resolve_member_oid(ticker_or_oid)
        # The financial-report subject only exists inside the FR class; applying
        # it to another class would reject every row.
        effective_subject_oid = subject_oid or (
            SUBJECT_OID_FINANCIAL_REPORT if disclosure_class.upper() == "FR" else None
        )
        key = self._cache_key(
            "historical-disclosures",
            oid=oid,
            from_date=from_date,
            to_date=to_date,
            disclosure_class=disclosure_class.upper(),
            subject_oid=effective_subject_oid,
            lang=self.config.lang,
        )
        async def fetch() -> list[dict[str, Any]]:
            return _dump_all(await self.disclosures.aget_historical_disclosures_by_criteria(
                member_oid=oid,
                from_date=from_date,
                to_date=to_date,
                disclosure_class=disclosure_class,
                subject_oid=effective_subject_oid,
            ))

        raw = await self._cached_async(
            key,
            fetch,
            expire=self.config.cache_expiry_default,
            force_refresh=force_refresh,
            refresh_async=refresh_async,
        )
        self._capture_metrics()
        return _load_all(Disclosure, raw)

    async def get_company_disclosures_by_type(
        self,
        ticker_or_oid: str,
        disclosure_type: str = "FAR",
    ) -> list[dict[str, Any]]:
        """Async fetch company disclosures of a specific profile type."""
        self._begin_operation("company_disclosures_by_type")
        oid = await self._resolve_member_oid(ticker_or_oid)
        result = await self.disclosures.aget_company_disclosures_by_type(
            member_oid=oid,
            disclosure_type=disclosure_type,
        )
        self._capture_metrics()
        return result

    async def get_disclosure_subjects(self, disclosure_class: str = "FR") -> list[DisclosureSubject]:
        """Async fetch available disclosure subjects for a disclosure class."""
        self._begin_operation("disclosure_subjects")
        result = await self.disclosures.aget_disclosure_subjects(
            disclosure_class=disclosure_class,
        )
        self._capture_metrics()
        return result

    async def get_disclosure_detail(self, disclosure_index: int | str) -> DisclosureDetail:
        """Async fetch disclosure detail and text."""
        from .models.disclosure import DisclosureDetail

        self._begin_operation("disclosure_detail")
        disclosure_index = positive_int(disclosure_index, "disclosure_index")
        key = self._cache_key("detail", disclosure_index=int(disclosure_index), lang=self.config.lang)
        async def fetch() -> dict[str, Any]:
            return _dump(await self.disclosures.aget_disclosure_detail(disclosure_index))

        raw = await self._cached_async(
            key, fetch, expire=self.config.cache_expiry_disclosure_detail
        )
        self._capture_metrics()
        return _load(DisclosureDetail, raw)

    async def get_expected_disclosures(self, days_ahead: int = 180, ticker_or_oid: str | None = None) -> list[ExpectedDisclosure]:
        """Async fetch expected forward-looking earnings release calendar."""
        from .models.disclosure import ExpectedDisclosure

        self._begin_operation("expected_disclosures")
        days_ahead = positive_int(days_ahead, "days_ahead", maximum=3650)
        oid = await self._resolve_member_oid(ticker_or_oid) if ticker_or_oid else None
        key = self._cache_key("calendar", days_ahead=days_ahead, member_oid=oid or "", lang=self.config.lang)
        async def fetch() -> list[dict[str, Any]]:
            return _dump_all(await self.calendar.aget_expected_disclosures(days_ahead=days_ahead, member_oid=oid))

        raw = await self._cached_async(
            key, fetch, expire=self.config.cache_expiry_calendar
        )
        self._capture_metrics()
        return _load_all(ExpectedDisclosure, raw)

    # ── Financials ───────────────────────────────────────────────────────────

    async def get_financial_statement(
        self,
        disclosure_index: int | str,
        ticker: str | None = None,
        force_refresh: bool = False,
    ) -> FinancialStatement:
        """Async fetch and parse financial statement tables for an announcement."""
        from .models.financials import FinancialStatement

        self._begin_operation("financial_statement")
        disclosure_index = positive_int(disclosure_index, "disclosure_index")
        ticker = normalize_ticker(ticker) if ticker else None
        key = self._cache_key(
            "financial-statement",
            lang=self.config.lang,
            ticker=(ticker or "").upper(),
            disclosure_index=int(disclosure_index),
        )
        async def fetch() -> dict[str, Any]:
            return _dump(await self.financials.aget_financial_statement(disclosure_index, stock_code=ticker))

        raw = await self._cached_async(
            key,
            fetch,
            expire=self.config.cache_expiry_financials,
            force_refresh=force_refresh,
        )
        self._capture_metrics()
        stmt = _load(FinancialStatement, raw)
        if self.db and stmt:
            self.db.save_financial_statement(stmt)
        return stmt

    async def get_financials(
        self,
        ticker: str,
        year: int,
        period: str | None = None,
        force_refresh: bool = False,
    ) -> FinancialStatement:
        """Async find the matching financial-report disclosure and return its statement."""
        self._begin_operation("financials_lookup")
        ticker = normalize_ticker(ticker)
        year = positive_int(year, "year", maximum=2100)
        oid = await self._resolve_member_oid(ticker)
        from .models.disclosure import Disclosure
        candidates: list[Disclosure] = []
        matching: list[Disclosure] = []
        for selector_year in _financial_selector_years(year, period):
            async def fetch_candidates(selector_year=selector_year) -> list[dict[str, Any]]:
                return _dump_all(await self.disclosures.aget_company_disclosures(
                    member_oid=oid,
                    notification_type="FR",
                    range_value=selector_year,
                    limit=200,
                ))

            raw_candidates = await self._cached_async(
                self._cache_key(
                    "company-disclosures",
                    oid=oid,
                    notification_type="FR",
                    range_value=selector_year,
                    limit=200,
                    lang=self.config.lang,
                ),
                fetch_candidates,
                expire=self.config.cache_expiry_default,
            )
            rows = _load_all(Disclosure, raw_candidates)
            seen = {item.disclosure_index for item in candidates}
            candidates.extend(item for item in rows if item.disclosure_index not in seen)
            matching = [
                item
                for item in candidates
                if _is_financial_statement_disclosure(item)
                and _financial_period_matches(item, year, period)
            ]
            if matching:
                break
        if not matching:
            wanted = f"{year}{f'/{period}' if period else ''}"
            raise KapNotFoundError(f"No financial report found for {ticker.upper()} ({wanted})")

        from .models.financials import FinancialStatement

        async def fetch_one(selected: Disclosure) -> FinancialStatement:
            async def fetch_statement() -> dict[str, Any]:
                return _dump(await self.financials.aget_financial_statement(
                    selected.disclosure_index,
                    stock_code=ticker.upper(),
                    company_title=selected.company_title,
                ))

            raw_statement = await self._cached_async(
                self._cache_key(
                    "financial-statement",
                    lang=self.config.lang,
                    ticker=ticker.upper(),
                    disclosure_index=int(selected.disclosure_index),
                ),
                fetch_statement,
                expire=self.config.cache_expiry_financials,
                force_refresh=force_refresh,
            )
            return _load(FinancialStatement, raw_statement)

        ordered = sorted(matching, key=lambda item: item.disclosure_index, reverse=True)
        failures: list[str] = []

        def accept(selected: Disclosure, outcome: Any) -> FinancialStatement | None:
            """Keep the first usable statement in preference order, else record why."""
            if isinstance(outcome, BaseException):
                failures.append(f"#{selected.disclosure_index}: {type(outcome).__name__}: {outcome}")
                return None
            if outcome.items and any(str(year) in label for label in outcome.period_labels):
                return outcome
            failures.append(
                f"#{selected.disclosure_index}: items={len(outcome.items)}, periods={outcome.period_labels}"
            )
            return None

        # The highest-index filing satisfies almost every lookup, so fetch it
        # alone rather than paying for every candidate up front. Only a
        # corrected or duplicate filing reaches the fallback below, and those
        # remaining candidates are then fetched concurrently rather than one
        # sequential round trip at a time.
        head, rest = ordered[0], ordered[1:]
        try:
            statement = await fetch_one(head)
        except Exception as exc:  # noqa: BLE001 - reported alongside the other candidates
            outcome: Any = exc
        else:
            outcome = statement
        usable = accept(head, outcome)
        if usable is not None:
            if self.db:
                self.db.save_financial_statement(usable)
            return usable

        if rest:
            results = await asyncio.gather(*(fetch_one(item) for item in rest), return_exceptions=True)
            for selected, result in zip(rest, results):
                usable = accept(selected, result)
                if usable is not None:
                    if self.db:
                        self.db.save_financial_statement(usable)
                    return usable
        wanted = f"{year}{f'/{period}' if period else ''}"
        raise KapValidationError(
            f"Financial-report candidates for {ticker.upper()} ({wanted}) contained no usable statement: "
            + "; ".join(failures)
        )

    # ── Events ───────────────────────────────────────────────────────────────

    async def extract_events(
        self,
        disclosure: Disclosure | None = None,
        disclosure_detail: DisclosureDetail | None = None,
        body_text: str | None = None,
        disclosure_index: int | str | None = None,
        stock_code: str | None = None,
        ticker: str | None = None,
    ) -> DerivedEvent:
        """Async primary-event view kept for backward compatibility."""
        events = await self.extract_events_many(
            disclosure=disclosure,
            disclosure_detail=disclosure_detail,
            body_text=body_text,
            disclosure_index=disclosure_index,
            stock_code=stock_code,
            ticker=ticker,
        )
        return events[0]

    async def extract_events_many(
        self,
        disclosure: Disclosure | None = None,
        disclosure_detail: DisclosureDetail | None = None,
        body_text: str | None = None,
        disclosure_index: int | str | None = None,
        stock_code: str | None = None,
        ticker: str | None = None,
    ) -> list[DerivedEvent]:
        """Async extraction of every supported event with metadata recovery."""
        from .models.disclosure import DisclosureDetail
        from .parsing.event_extractor import extract_multiple_events_from_text

        self._begin_operation("event_extraction")
        detail = disclosure_detail
        disc_id = (disclosure.disclosure_id if disclosure else (detail.disclosure_id if detail else "")) or ""
        disc_index = (disclosure.disclosure_index if disclosure else (detail.disclosure_index if detail else disclosure_index)) or 0
        disc_index = int(disc_index)
        explicit_stock = stock_code or ticker
        resolved_stock = explicit_stock or (disclosure.stock_code if disclosure else (detail.stock_code if detail else None)) or "UNKNOWN"
        title = disclosure.title if disclosure else (detail.title if detail else None)
        pub_date = disclosure.publish_date if disclosure else (detail.publish_date if detail else None)
        disc_type = (disclosure.disclosure_type if disclosure else None) or (detail.disclosure_type if detail else None)

        if disc_index and detail is None and (body_text is None or not explicit_stock and resolved_stock == "UNKNOWN"):
            async def fetch_detail() -> dict[str, Any]:
                return _dump(await self.disclosures.aget_disclosure_detail(disc_index))

            raw_detail = await self._cached_async(
                self._cache_key("detail", disclosure_index=disc_index, lang=self.config.lang),
                fetch_detail,
                expire=self.config.cache_expiry_disclosure_detail,
            )
            detail = _load(DisclosureDetail, raw_detail)
            disc_id = disc_id or detail.disclosure_id or ""
            title = title or detail.title
            pub_date = pub_date or detail.publish_date
            if resolved_stock == "UNKNOWN":
                resolved_stock = detail.stock_code or detail.company_title or "UNKNOWN"

        text = body_text if body_text is not None else (detail.content_text if detail else "")
        if detail is not None:
            disc_id = disc_id or detail.disclosure_id or ""
            title = title or detail.title
            pub_date = pub_date or detail.publish_date
            disc_type = disc_type or detail.disclosure_type
            if resolved_stock == "UNKNOWN":
                resolved_stock = detail.stock_code or detail.company_title or "UNKNOWN"

        events = extract_multiple_events_from_text(
            disclosure_id=disc_id,
            disclosure_index=disc_index,
            company_key=resolved_stock,
            title=title,
            body_text=text,
            disclosure_type=disc_type,
            publish_date=pub_date,
        )
        if self.db:
            self.db.save_derived_events(events)
        return events

    def score_company_events(self, events: list[DerivedEvent], as_of: datetime.datetime | None = None) -> list[ScoredCompany]:
        from .parsing.event_extractor import score_events

        return score_events(events, as_of=as_of)
