from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from .cache import CacheManager
from .client import _cache_key, _financial_period_matches
from .config import KapConfig
from .scrapers.base import BaseScraper, KapNotFoundError

if TYPE_CHECKING:
    from .models.company import Company, CompanyGeneralInfo
    from .models.disclosure import Disclosure, DisclosureDetail, DisclosureSubject, ExpectedDisclosure
    from .models.events import DerivedEvent, ScoredCompany
    from .models.financials import FinancialStatement
    from .models.market import Indice, Market, Sector

logger = logging.getLogger("kap.async_client")


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

    def _get_component(self, name: str) -> Any:
        """Import only the scraper required by the current async operation."""
        if name in self._components:
            return self._components[name]
        if name == "listings":
            from .scrapers.listings import ListingsScraper
            component = ListingsScraper(self.base_scraper, self.config)
        elif name == "disclosures":
            from .scrapers.disclosures import DisclosuresScraper
            component = DisclosuresScraper(self.base_scraper, self.config)
        elif name == "company_general":
            from .scrapers.company_general import CompanyGeneralScraper
            component = CompanyGeneralScraper(self.base_scraper, self.config)
        elif name == "financials":
            from .scrapers.financials import FinancialsScraper
            component = FinancialsScraper(self.base_scraper, self.config)
        elif name == "calendar":
            from .scrapers.calendar import CalendarScraper
            component = CalendarScraper(self.base_scraper, self.config)
            component.set_ticker_lookup(self._get_component("listings").lookup_ticker)
        else:
            raise AttributeError(f"Unknown KAP component: {name}")
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
        self.last_request_metrics = dict(self.base_scraper.last_request_metrics)

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
    ) -> Any:
        result = await self.cache.cached_call_async(
            key,
            fetch,
            expire=expire,
            force_refresh=force_refresh,
            refresh_async=refresh_async,
        )
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
            return [c.model_dump() for c in companies]

        raw = await self._cached_async(
            key,
            fetch,
            expire=self.config.cache_expiry_companies,
            force_refresh=force_refresh,
            refresh_async=refresh_async,
        )
        companies = [Company(**c) if isinstance(c, dict) else c for c in raw]
        if self.last_request_metrics.get("operation") != "registry":
            self._capture_metrics()
        if self.db and companies:
            self.db.save_companies(companies)
        return companies

    async def search_companies(self, query: str, online: bool = False) -> list[Company]:
        """Async search companies by ticker or name fragment."""
        self._begin_operation("company_search")
        result = await self.listings.asearch(query, online=online)
        self._capture_metrics()
        return result

    async def get_company(self, ticker: str, online: bool = False) -> Company | None:
        """Async retrieve a specific company by ticker code."""
        self._begin_operation("company_lookup")
        t = ticker.upper().strip()
        companies = await self.get_companies(online=online)
        for c in companies:
            if c.ticker == t:
                return c
        results = await self.search_companies(t, online=online)
        for r in results:
            if r.ticker == t:
                return r
        return None

    async def _resolve_member_oid(self, ticker_or_oid: str) -> str:
        clean = ticker_or_oid.strip()
        if len(clean) >= 20 and re_is_hex(clean):
            return clean
        oid = await self.listings.alookup_member_oid(clean)
        if oid:
            return oid
        comp = await self.get_company(clean)
        if comp and comp.company_id:
            return comp.company_id
        return clean

    async def get_company_general_info(self, ticker_or_oid: str, force_refresh: bool = False) -> CompanyGeneralInfo:
        """Async get comprehensive company profile."""
        from .models.company import CompanyGeneralInfo

        self._begin_operation("company_general")
        oid = await self._resolve_member_oid(ticker_or_oid)
        key = self._cache_key("company-general", oid=oid, lang=self.config.lang)

        async def fetch() -> dict[str, Any]:
            info = await self.company_general.aget_company_general_info(oid)
            return info.model_dump()

        raw = await self._cached_async(
            key,
            fetch,
            expire=self.config.cache_expiry_company_general,
            force_refresh=force_refresh,
        )
        self._capture_metrics()
        return CompanyGeneralInfo(**raw) if isinstance(raw, dict) else raw

    # ── Market Taxonomy ──────────────────────────────────────────────────────

    async def get_indices(self, force_refresh: bool = False) -> list[Indice]:
        """Async get all BIST indices."""
        from .models.market import Indice

        self._begin_operation("indices")
        key = self._cache_key("indices", lang=self.config.lang)
        async def fetch() -> list[dict[str, Any]]:
            return [i.model_dump() for i in await self.listings.aget_indices()]
        raw = await self._cached_async(
            key, fetch, expire=self.config.cache_expiry_indices, force_refresh=force_refresh
        )
        self._capture_metrics()
        indices = [Indice(**i) if isinstance(i, dict) else i for i in raw]
        return indices

    async def get_sectors(self, force_refresh: bool = False) -> list[Sector]:
        """Async get all sectors."""
        from .models.market import Sector

        self._begin_operation("sectors")
        key = self._cache_key("sectors", lang=self.config.lang)
        async def fetch() -> list[dict[str, Any]]:
            return [s.model_dump() for s in await self.listings.aget_sectors()]
        raw = await self._cached_async(
            key, fetch, expire=self.config.cache_expiry_sectors, force_refresh=force_refresh
        )
        self._capture_metrics()
        sectors = [Sector(**s) if isinstance(s, dict) else s for s in raw]
        return sectors

    async def get_markets(self, force_refresh: bool = False) -> list[Market]:
        """Async get all market segments."""
        from .models.market import Market

        self._begin_operation("markets")
        key = self._cache_key("markets", lang=self.config.lang)
        async def fetch() -> list[dict[str, Any]]:
            return [m.model_dump() for m in await self.listings.aget_markets()]
        raw = await self._cached_async(
            key, fetch, expire=self.config.cache_expiry_indices, force_refresh=force_refresh
        )
        self._capture_metrics()
        markets = [Market(**m) if isinstance(m, dict) else m for m in raw]
        return markets

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
            disclosures = await self.disclosures.aget_today_disclosures(
                member_type=member_type,
                disclosure_types=disclosure_types,
            )
            return [d.model_dump() for d in disclosures]

        raw = await self._cached_async(
            key,
            fetch,
            expire=self.config.cache_expiry_today,
            force_refresh=force_refresh,
            refresh_async=refresh_async,
        )
        self._capture_metrics()
        disclosures = [Disclosure(**d) if isinstance(d, dict) else d for d in raw]
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
        key = self._cache_key(
            "latest",
            limit=limit,
            ticker=(ticker or "").upper(),
            disclosure_types=sorted(disclosure_types or []),
            lang=self.config.lang,
        )
        async def fetch() -> list[dict[str, Any]]:
            disclosures = await self.disclosures.aget_latest_disclosures(
                limit=limit,
                ticker=ticker,
                disclosure_types=disclosure_types,
            )
            return [d.model_dump() for d in disclosures]

        raw = await self._cached_async(
            key,
            fetch,
            expire=self.config.cache_expiry_latest,
            force_refresh=force_refresh,
            refresh_async=refresh_async,
        )
        self._capture_metrics()
        disclosures = [Disclosure(**d) if isinstance(d, dict) else d for d in raw]
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
            disclosures = await self.disclosures.aget_company_disclosures(
                member_oid=oid,
                notification_type=notification_type,
                range_value=range_days,
                limit=limit,
            )
            return [item.model_dump() for item in disclosures]

        raw = await self._cached_async(
            key,
            fetch,
            expire=self.config.cache_expiry_default,
            force_refresh=force_refresh,
            refresh_async=refresh_async,
        )
        self._capture_metrics()
        disclosures = [Disclosure(**item) if isinstance(item, dict) else item for item in raw]
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
        oid = await self._resolve_member_oid(ticker_or_oid)
        key = self._cache_key(
            "historical-disclosures",
            oid=oid,
            from_date=from_date,
            to_date=to_date,
            disclosure_class=disclosure_class.upper(),
            subject_oid=subject_oid or "",
            lang=self.config.lang,
        )
        async def fetch() -> list[dict[str, Any]]:
            rows = await self.disclosures.aget_historical_disclosures_by_criteria(
                member_oid=oid,
                from_date=from_date,
                to_date=to_date,
                disclosure_class=disclosure_class,
                subject_oid=subject_oid or "",
            )
            return [item.model_dump() for item in rows]

        raw = await self._cached_async(
            key,
            fetch,
            expire=self.config.cache_expiry_default,
            force_refresh=force_refresh,
            refresh_async=refresh_async,
        )
        self._capture_metrics()
        rows = [Disclosure(**item) if isinstance(item, dict) else item for item in raw]
        return rows

    async def get_disclosure_detail(self, disclosure_index: int | str) -> DisclosureDetail:
        """Async fetch disclosure detail and text."""
        from .models.disclosure import DisclosureDetail

        self._begin_operation("disclosure_detail")
        key = self._cache_key("detail", disclosure_index=int(disclosure_index), lang=self.config.lang)
        async def fetch() -> dict[str, Any]:
            detail = await self.disclosures.aget_disclosure_detail(disclosure_index)
            return detail.model_dump()

        raw = await self._cached_async(
            key, fetch, expire=self.config.cache_expiry_disclosure_detail
        )
        self._capture_metrics()
        return DisclosureDetail(**raw) if isinstance(raw, dict) else raw

    async def get_expected_disclosures(self, days_ahead: int = 180, ticker_or_oid: str | None = None) -> list[ExpectedDisclosure]:
        """Async fetch expected forward-looking earnings release calendar."""
        from .models.disclosure import ExpectedDisclosure

        self._begin_operation("expected_disclosures")
        oid = await self._resolve_member_oid(ticker_or_oid) if ticker_or_oid else None
        key = self._cache_key("calendar", days_ahead=days_ahead, member_oid=oid or "", lang=self.config.lang)
        async def fetch() -> list[dict[str, Any]]:
            rows = await self.calendar.aget_expected_disclosures(days_ahead=days_ahead, member_oid=oid)
            return [row.model_dump() for row in rows]

        raw = await self._cached_async(
            key, fetch, expire=self.config.cache_expiry_latest
        )
        self._capture_metrics()
        rows = [ExpectedDisclosure(**row) if isinstance(row, dict) else row for row in raw]
        return rows

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
        key = self._cache_key(
            "financial-statement",
            lang=self.config.lang,
            ticker=(ticker or "").upper(),
            disclosure_index=int(disclosure_index),
        )
        async def fetch() -> dict[str, Any]:
            stmt = await self.financials.aget_financial_statement(disclosure_index, stock_code=ticker)
            return stmt.model_dump()

        raw = await self._cached_async(
            key,
            fetch,
            expire=self.config.cache_expiry_financials,
            force_refresh=force_refresh,
        )
        self._capture_metrics()
        stmt = FinancialStatement(**raw) if isinstance(raw, dict) else raw
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
        lookback_days = max(365, (datetime.date.today() - datetime.date(year, 1, 1)).days + 31)
        candidates = await self.get_company_disclosures(
            ticker_or_oid=ticker,
            notification_type="FR",
            range_days=lookback_days,
            limit=200,
        )
        if not candidates:
            candidates = await self.get_historical_disclosures(
                ticker_or_oid=ticker,
                from_date=datetime.date(year, 1, 1),
                to_date=datetime.date(year, 12, 31),
                disclosure_class="FR",
            )

        matching = [d for d in candidates if _financial_period_matches(d, year, period)]
        if not matching:
            wanted = f"{year}{f'/{period}' if period else ''}"
            raise KapNotFoundError(f"No financial report found for {ticker.upper()} ({wanted})")
        selected = max(matching, key=lambda item: item.disclosure_index)
        return await self.get_financial_statement(
            selected.disclosure_index,
            ticker=ticker,
            force_refresh=force_refresh,
        )

    async def download_financial_report_xls(self, ticker_or_oid: str, year: int | str = 2024) -> dict[str, Any]:
        """Async download zipped XLS financial report package."""
        self._begin_operation("financial_xls")
        oid = await self._resolve_member_oid(ticker_or_oid)
        key = self._cache_key("financial-xls", oid=oid, year=year, lang=self.config.lang)

        async def fetch() -> dict[str, Any]:
            return await self.financials.adownload_financial_report_xls(oid, year=year)

        result = await self._cached_async(
            key, fetch, expire=self.config.cache_expiry_financials
        )
        self._capture_metrics()
        return result

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
        from .models.events import DerivedEvent
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
        disc_type = disclosure.disclosure_type if disclosure else None

        if disc_index and detail is None and (body_text is None or not explicit_stock and resolved_stock == "UNKNOWN"):
            detail = await self.get_disclosure_detail(disc_index)
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


def re_is_hex(s: str) -> bool:
    import re
    return bool(re.fullmatch(r"[0-9a-fA-F]+", s))
