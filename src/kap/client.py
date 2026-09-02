from __future__ import annotations

import datetime
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .cache import CacheManager
from .config import KapConfig
from .scrapers.base import BaseScraper, KapNotFoundError

if TYPE_CHECKING:
    from .models.company import Company, CompanyGeneralInfo
    from .models.disclosure import Disclosure, DisclosureDetail, DisclosureSubject, ExpectedDisclosure
    from .models.events import DerivedEvent, ScoredCompany
    from .models.financials import FinancialStatement
    from .models.market import Indice, Market, Sector

logger = logging.getLogger("kap.client")


def _cache_key(config: KapConfig, namespace: str, **parts: Any) -> str:
    """Build the shared versioned cache key used by sync and async clients."""
    canonical = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
    return f"kap:v{config.parser_schema_version}:{namespace}:{digest}"


class KapClient:
    """Synchronous client for KAP (Public Disclosure Platform) and Borsa Istanbul."""

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
        """Import only the scraper required by the operation being executed."""
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

    def close(self) -> None:
        self.base_scraper.close()
        self.cache.close()
        if self._db:
            self._db.close()

    def __enter__(self) -> KapClient:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def clear_cache(self) -> None:
        """Clear all cached responses."""
        self.cache.clear()

    def _begin_operation(self, name: str) -> None:
        self.base_scraper.begin_operation(name)
        self.last_request_metrics = dict(self.base_scraper.last_request_metrics)

    def _cached_call(self, key: str, func: Any, **kwargs: Any) -> Any:
        result = self.cache.cached_call(key, func, **kwargs)
        if self.last_request_metrics.get("operation") != "registry":
            self.last_request_metrics = dict(self.base_scraper.last_request_metrics)
        return result

    def _cache_key(self, namespace: str, **parts: Any) -> str:
        """Build a versioned, parameter-sensitive cache key."""
        return _cache_key(self.config, namespace, **parts)

    # ── Companies ────────────────────────────────────────────────────────────

    def get_companies(
        self,
        online: bool = False,
        force_refresh: bool = False,
        refresh_async: bool = False,
    ) -> list[Company]:
        """Fetch list of all BIST companies (offline bundled snapshot by default)."""
        self._begin_operation("companies")
        key = self._cache_key("companies", online=online, lang=self.config.lang)
        companies = self._cached_call(
            key,
            lambda: self.listings.get_companies(online=online),
            expire=self.config.cache_expiry_companies,
            force_refresh=force_refresh,
            refresh_async=refresh_async,
        )
        registry_metrics = getattr(self.listings, "last_registry_metrics", {})
        if registry_metrics.get("operation_id") == self.last_request_metrics.get("operation_id"):
            self.last_request_metrics = dict(registry_metrics)
        if self.db and companies:
            self.db.save_companies(companies)
        return companies

    def search_companies(self, query: str, online: bool = False) -> list[Company]:
        """Search companies by ticker or name fragment."""
        self._begin_operation("company_search")
        result = self.listings.search(query, online=online)
        self.last_request_metrics = dict(self.base_scraper.last_request_metrics)
        return result

    def get_company(self, ticker: str, online: bool = False) -> Company | None:
        """Retrieve a specific company by ticker code."""
        self._begin_operation("company_lookup")
        t = ticker.upper().strip()
        companies = self.get_companies(online=online)
        for c in companies:
            if c.ticker == t:
                return c
        # Fallback to search
        results = self.search_companies(t, online=online)
        for r in results:
            if r.ticker == t:
                return r
        return None

    def _resolve_member_oid(self, ticker_or_oid: str) -> str:
        """Resolve ticker or member OID to member OID."""
        clean = ticker_or_oid.strip()
        if len(clean) >= 20 and re_is_hex(clean):
            return clean
        oid = self.listings.lookup_member_oid(clean)
        if oid:
            return oid
        comp = self.get_company(clean)
        if comp and comp.company_id:
            return comp.company_id
        return clean

    def get_company_general_info(self, ticker_or_oid: str, force_refresh: bool = False) -> CompanyGeneralInfo:
        """Get comprehensive company profile (shareholders >=5%, float, subsidiaries, etc.)."""
        self._begin_operation("company_general")
        oid = self._resolve_member_oid(ticker_or_oid)
        key = self._cache_key("company-general", oid=oid, lang=self.config.lang)
        info = self._cached_call(
            key,
            lambda: self.company_general.get_company_general_info(oid),
            expire=self.config.cache_expiry_company_general,
            force_refresh=force_refresh,
        )
        return info

    # ── Market Taxonomy ──────────────────────────────────────────────────────

    def get_indices(self, force_refresh: bool = False) -> list[Indice]:
        """Get all BIST indices and their member stock codes."""
        self._begin_operation("indices")
        return self._cached_call(
            self._cache_key("indices", lang=self.config.lang),
            lambda: self.listings.get_indices(),
            expire=self.config.cache_expiry_indices,
            force_refresh=force_refresh,
        )

    def get_sectors(self, force_refresh: bool = False) -> list[Sector]:
        """Get all sectors and subsectors with member stocks."""
        self._begin_operation("sectors")
        return self._cached_call(
            self._cache_key("sectors", lang=self.config.lang),
            lambda: self.listings.get_sectors(),
            expire=self.config.cache_expiry_sectors,
            force_refresh=force_refresh,
        )

    def get_markets(self, force_refresh: bool = False) -> list[Market]:
        """Get all trading market segments (Yıldız Pazar, etc.) with member stocks."""
        self._begin_operation("markets")
        return self._cached_call(
            self._cache_key("markets", lang=self.config.lang),
            lambda: self.listings.get_markets(),
            expire=self.config.cache_expiry_indices,
            force_refresh=force_refresh,
        )

    # ── Disclosures ──────────────────────────────────────────────────────────

    def get_today_disclosures(
        self,
        member_type: str = "bist_sirketleri",
        disclosure_types: list[str] | None = None,
    ) -> list[Disclosure]:
        """Get today's live disclosures in Istanbul time."""
        self._begin_operation("today_disclosures")
        key = self._cache_key(
            "today",
            member_type=member_type,
            disclosure_types=sorted(disclosure_types or []),
            lang=self.config.lang,
        )
        disclosures = self._cached_call(
            key,
            lambda: self.disclosures.get_today_disclosures(
                member_type=member_type,
                disclosure_types=disclosure_types,
            ),
            expire=self.config.cache_expiry_today,
        )
        if self.db and disclosures:
            self.db.save_disclosures(disclosures)
        return disclosures

    def get_latest_disclosures(
        self,
        limit: int = 50,
        ticker: str | None = None,
        disclosure_types: list[str] | None = None,
    ) -> list[Disclosure]:
        """Get latest disclosures across all markets or for a specific ticker."""
        self._begin_operation("latest_disclosures")
        key = self._cache_key(
            "latest",
            limit=limit,
            ticker=(ticker or "").upper(),
            disclosure_types=sorted(disclosure_types or []),
            lang=self.config.lang,
        )
        disclosures = self._cached_call(
            key,
            lambda: self.disclosures.get_latest_disclosures(
                limit=limit,
                ticker=ticker,
                disclosure_types=disclosure_types,
            ),
            expire=self.config.cache_expiry_latest,
        )
        if self.db and disclosures:
            self.db.save_disclosures(disclosures)
        return disclosures

    def get_company_disclosures(
        self,
        ticker_or_oid: str,
        notification_type: str = "ALL",
        range_days: int = 365,
        limit: int = 50,
    ) -> list[Disclosure]:
        """Get historical disclosures for a specific company."""
        self._begin_operation("company_disclosures")
        oid = self._resolve_member_oid(ticker_or_oid)
        key = self._cache_key(
            "company-disclosures",
            oid=oid,
            notification_type=notification_type.upper(),
            range_days=range_days,
            limit=limit,
            lang=self.config.lang,
        )
        disclosures = self._cached_call(
            key,
            lambda: self.disclosures.get_company_disclosures(
                member_oid=oid,
                notification_type=notification_type,
                range_value=range_days,
                limit=limit,
            ),
            expire=self.config.cache_expiry_default,
        )
        if self.db and disclosures:
            self.db.save_disclosures(disclosures)
        return disclosures

    def get_historical_disclosures(
        self,
        ticker_or_oid: str,
        from_date: datetime.date | None = None,
        to_date: datetime.date | None = None,
        disclosure_class: str = "FR",
        subject_oid: str | None = None,
    ) -> list[Disclosure]:
        """Query historical disclosures via criteria POST endpoint."""
        self._begin_operation("historical_disclosures")
        oid = self._resolve_member_oid(ticker_or_oid)
        key = self._cache_key(
            "historical-disclosures",
            oid=oid,
            from_date=from_date,
            to_date=to_date,
            disclosure_class=disclosure_class.upper(),
            subject_oid=subject_oid or "",
            lang=self.config.lang,
        )
        return self._cached_call(
            key,
            lambda: self.disclosures.get_historical_disclosures_by_criteria(
                member_oid=oid,
                from_date=from_date,
                to_date=to_date,
                disclosure_class=disclosure_class,
                subject_oid=subject_oid or "",
            ),
            expire=self.config.cache_expiry_default,
        )

    def get_company_disclosures_by_type(self, ticker_or_oid: str, disclosure_type: str = "FAR") -> list[dict[str, Any]]:
        """Fetch disclosures of a specific type (e.g. 'FAR' - Activity Reports, 'KYUR', 'SUR', 'KDP')."""
        self._begin_operation("company_disclosures_by_type")
        oid = self._resolve_member_oid(ticker_or_oid)
        result = self.disclosures.get_company_disclosures_by_type(member_oid=oid, disclosure_type=disclosure_type)
        self.last_request_metrics = dict(self.base_scraper.last_request_metrics)
        return result

    def get_disclosure_subjects(self, disclosure_class: str = "FR") -> list[DisclosureSubject]:
        """Fetch available disclosure subjects for a disclosure class ('FR', 'ODA', 'DG')."""
        self._begin_operation("disclosure_subjects")
        result = self.disclosures.get_disclosure_subjects(disclosure_class=disclosure_class)
        self.last_request_metrics = dict(self.base_scraper.last_request_metrics)
        return result

    def get_disclosure_detail(self, disclosure_index: int | str) -> DisclosureDetail:
        """Fetch disclosure detail and plain-text body by announcement index."""
        self._begin_operation("disclosure_detail")
        key = self._cache_key("detail", disclosure_index=int(disclosure_index), lang=self.config.lang)
        return self._cached_call(
            key,
            lambda: self.disclosures.get_disclosure_detail(disclosure_index),
            expire=self.config.cache_expiry_disclosure_detail,
        )

    def get_expected_disclosures(self, days_ahead: int = 180, ticker_or_oid: str | None = None) -> list[ExpectedDisclosure]:
        """Fetch expected forward-looking earnings release calendar."""
        self._begin_operation("expected_disclosures")
        oid = self._resolve_member_oid(ticker_or_oid) if ticker_or_oid else None
        key = self._cache_key("calendar", days_ahead=days_ahead, member_oid=oid or "", lang=self.config.lang)
        return self._cached_call(
            key,
            lambda: self.calendar.get_expected_disclosures(days_ahead=days_ahead, member_oid=oid),
            expire=self.config.cache_expiry_latest,
        )

    # ── Financials ───────────────────────────────────────────────────────────

    def get_financial_statement(
        self,
        disclosure_index: int | str,
        ticker: str | None = None,
        force_refresh: bool = False,
    ) -> FinancialStatement:
        """Fetch and parse financial statement tables for an announcement."""
        self._begin_operation("financial_statement")
        key = self._cache_key(
            "financial-statement",
            lang=self.config.lang,
            ticker=(ticker or "").upper(),
            disclosure_index=int(disclosure_index),
        )
        stmt = self._cached_call(
            key,
            lambda: self.financials.get_financial_statement(disclosure_index, stock_code=ticker),
            expire=self.config.cache_expiry_financials,
            force_refresh=force_refresh,
        )
        if self.db and stmt:
            self.db.save_financial_statement(stmt)
        return stmt

    def get_financials(
        self,
        ticker: str,
        year: int,
        period: str | None = None,
        force_refresh: bool = False,
    ) -> FinancialStatement:
        """Find the matching financial-report disclosure and return its statement."""
        self._begin_operation("financials_lookup")
        # The SGBF endpoint expects a day range, not a calendar year.  Use it
        # first for compatibility with deployments that cap criteria searches,
        # then narrow with the exact calendar-year criteria endpoint.
        lookback_days = max(365, (datetime.date.today() - datetime.date(year, 1, 1)).days + 31)
        candidates = self.get_company_disclosures(
            ticker_or_oid=ticker,
            notification_type="FR",
            range_days=lookback_days,
            limit=200,
        )
        if not candidates:
            candidates = self.get_historical_disclosures(
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
        return self.get_financial_statement(
            selected.disclosure_index,
            ticker=ticker,
            force_refresh=force_refresh,
        )

    def download_financial_report_xls(self, ticker_or_oid: str, year: int | str = 2024) -> dict[str, Any]:
        """Download zipped XLS financial report package from KAP and parse tables."""
        self._begin_operation("financial_xls")
        oid = self._resolve_member_oid(ticker_or_oid)
        key = f"fin_xls_{oid}_{year}"
        return self._cached_call(
            key,
            lambda: self.financials.download_financial_report_xls(oid, year=year),
            expire=self.config.cache_expiry_financials,
        )

    # ── Events & AI Signals ──────────────────────────────────────────────────

    def extract_events(
        self,
        disclosure: Disclosure | None = None,
        disclosure_detail: DisclosureDetail | None = None,
        body_text: str | None = None,
        disclosure_index: int | str | None = None,
        stock_code: str | None = None,
        ticker: str | None = None,
    ) -> DerivedEvent:
        """Extract the primary structured event, keeping the historical single-event API."""
        return self.extract_events_many(
            disclosure=disclosure,
            disclosure_detail=disclosure_detail,
            body_text=body_text,
            disclosure_index=disclosure_index,
            stock_code=stock_code,
            ticker=ticker,
        )[0]

    def extract_events_many(
        self,
        disclosure: Disclosure | None = None,
        disclosure_detail: DisclosureDetail | None = None,
        body_text: str | None = None,
        disclosure_index: int | str | None = None,
        stock_code: str | None = None,
        ticker: str | None = None,
    ) -> list[DerivedEvent]:
        """Extract every supported event and recover missing disclosure metadata when possible."""
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

        # A caller may provide body text while omitting the ticker. Fetch the detail
        # page in that case for identity/title metadata without replacing the text.
        if disc_index and detail is None and (body_text is None or not explicit_stock and resolved_stock == "UNKNOWN"):
            detail = self.get_disclosure_detail(disc_index)
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
        """Aggregate and score derived events per company with time-decay weighting."""
        from .parsing.event_extractor import score_events

        return score_events(events, as_of=as_of)


def re_is_hex(s: str) -> bool:
    import re
    return bool(re.fullmatch(r"[0-9a-fA-F]+", s))


def _financial_period_matches(disclosure: Disclosure, year: int, period: str | None) -> bool:
    """Match KAP's Turkish/English report-period labels without relying on one title format."""
    haystack = " ".join(
        value
        for value in (
            disclosure.title,
            disclosure.publish_date,
            json.dumps(disclosure.raw, ensure_ascii=False, default=str),
        )
        if value
    ).casefold()
    if str(year) not in haystack:
        return False
    if not period:
        return True

    normalized = re.sub(r"[^a-z0-9çğıöşü]+", "", period.casefold())
    normalized_haystack = re.sub(r"[^a-z0-9çğıöşü]+", "", haystack)
    compact = re.sub(r"[^0-9]", "", haystack)
    quarter_patterns = {
        "q1": ("1çeyrek", "1ceyrek", "1quarter", "1q", "ilkçeyrek"),
        "q2": ("2çeyrek", "2ceyrek", "2quarter", "2q", "ikinciçeyrek"),
        "q3": ("3çeyrek", "3ceyrek", "3quarter", "3q", "üçüncüçeyrek", "ucuncuceyrek"),
        "q4": ("4çeyrek", "4ceyrek", "4quarter", "4q", "dördüncüçeyrek", "dorduncuceyrek"),
    }
    if normalized in {"annual", "yillik", "year", "fullyear", "fy"}:
        return any(token in normalized_haystack for token in ("yıllık", "yillik", "annual", "fullyear")) or "3112" + str(year) in compact
    for quarter, aliases in quarter_patterns.items():
        if normalized == quarter or normalized in aliases:
            month = {"q1": "03", "q2": "06", "q3": "09", "q4": "12"}[quarter]
            return any(alias.replace(" ", "") in normalized_haystack for alias in aliases) or f"{month}{year}" in compact
    return normalized in normalized_haystack
