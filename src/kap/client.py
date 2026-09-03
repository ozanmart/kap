from __future__ import annotations

import datetime
import hashlib
import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._components import create_component
from .cache import CacheManager
from .config import KapConfig
from .constants import SUBJECT_OID_FINANCIAL_REPORT
from .exceptions import KapDeadlineExceeded, KapNotFoundError, KapValidationError
from .scrapers.base import BaseScraper
from ._validation import is_hex_token, normalize_ticker, positive_int, require_text, validate_date_range

if TYPE_CHECKING:
    from .models.company import Company, CompanyGeneralInfo
    from .models.disclosure import Disclosure, DisclosureDetail, DisclosureSubject, ExpectedDisclosure
    from .models.events import DerivedEvent, ScoredCompany
    from .models.financials import FinancialStatement
    from .models.market import Indice, Market, Sector

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
        self._client_operation_deadline: float | None = None

    def _get_component(self, name: str) -> Any:
        """Import only the scraper required by the operation being executed."""
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

    def _cached_call(self, key: str, func: Any, **kwargs: Any) -> Any:
        enforce_deadline = bool(kwargs.pop("enforce_deadline", True))
        if enforce_deadline:
            self._ensure_operation_budget()
        try:
            result = self.cache.cached_call(key, func, **kwargs)
        except Exception as exc:
            # The scraper publishes the terminal request metrics before
            # raising. Preserve those metrics for callers inspecting a failed
            # cached live request instead of leaving cache_lookup/0 behind.
            base_metrics = dict(self.base_scraper.last_request_metrics)
            client_metrics = dict(self.last_request_metrics)
            same_operation = (
                base_metrics.get("operation_id")
                and base_metrics.get("operation_id") == client_metrics.get("operation_id")
            )
            if client_metrics.get("stage") == "deadline" and same_operation:
                # A nested client budget check is more authoritative than the
                # base scraper's unchanged cache_lookup placeholder.
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
            enforce_deadline=online,
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
        query = require_text(query, "query")
        result = self.listings.search(query, online=online)
        self.last_request_metrics = dict(self.base_scraper.last_request_metrics)
        return result

    def get_company(self, ticker: str, online: bool = False) -> Company | None:
        """Retrieve a specific company by ticker code."""
        self._begin_operation("company_lookup")
        t = normalize_ticker(ticker)
        results = self.listings.search(t, online=online)
        for r in results:
            if r.ticker == t:
                return r
        return None

    def _resolve_member_oid(self, ticker_or_oid: str) -> str:
        """Resolve ticker or member OID to member OID."""
        clean = require_text(ticker_or_oid, "ticker_or_oid")
        if len(clean) >= 20 and is_hex_token(clean):
            return clean
        oid = self.listings.lookup_member_oid(clean)
        if oid:
            return oid
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
        if not info.ticker:
            requested = ticker_or_oid.strip().upper()
            ticker = requested if re.fullmatch(r"[A-Z0-9]{2,10}", requested) else self.listings.lookup_ticker(oid)
            if ticker:
                info = info.model_copy(update={"ticker": ticker})
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
            expire=self.config.cache_expiry_markets,
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
        limit = positive_int(limit, "limit", maximum=200)
        ticker = normalize_ticker(ticker) if ticker else None
        key = self._cache_key(
            "latest",
            limit=limit,
            ticker=(ticker or "").upper(),
            disclosure_types=sorted(disclosure_types or []),
            lang=self.config.lang,
        )

        def fetch() -> list[Disclosure]:
            if not ticker:
                return self.disclosures.get_latest_disclosures(
                    limit=limit,
                    ticker=None,
                    disclosure_types=disclosure_types,
                )
            oid = self._resolve_member_oid(ticker)
            rows = self.disclosures.get_company_disclosures(
                member_oid=oid,
                notification_type="ALL",
                range_value=365,
                limit=max(50, limit * 5),
            )
            if not rows:
                rows = self.disclosures.get_company_disclosures(
                    member_oid=oid,
                    notification_type="ALL",
                    range_value=3650,
                    limit=max(50, limit * 5),
                )
            if disclosure_types:
                wanted = {item.upper() for item in disclosure_types}
                rows = [row for row in rows if (row.disclosure_type or "").upper() in wanted]
            rows.sort(key=lambda row: row.disclosure_index, reverse=True)
            return rows[: max(0, int(limit))]

        disclosures = self._cached_call(
            key,
            fetch,
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
        range_days = positive_int(range_days, "range_days", maximum=3650)
        limit = positive_int(limit, "limit", maximum=200)
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
        validate_date_range(from_date, to_date)
        oid = self._resolve_member_oid(ticker_or_oid)
        effective_subject_oid = subject_oid or SUBJECT_OID_FINANCIAL_REPORT
        key = self._cache_key(
            "historical-disclosures",
            oid=oid,
            from_date=from_date,
            to_date=to_date,
            disclosure_class=disclosure_class.upper(),
            subject_oid=effective_subject_oid,
            lang=self.config.lang,
        )
        return self._cached_call(
            key,
            lambda: self.disclosures.get_historical_disclosures_by_criteria(
                member_oid=oid,
                from_date=from_date,
                to_date=to_date,
                disclosure_class=disclosure_class,
                subject_oid=effective_subject_oid,
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
        disclosure_index = positive_int(disclosure_index, "disclosure_index")
        key = self._cache_key("detail", disclosure_index=int(disclosure_index), lang=self.config.lang)
        return self._cached_call(
            key,
            lambda: self.disclosures.get_disclosure_detail(disclosure_index),
            expire=self.config.cache_expiry_disclosure_detail,
        )

    def get_expected_disclosures(self, days_ahead: int = 180, ticker_or_oid: str | None = None) -> list[ExpectedDisclosure]:
        """Fetch expected forward-looking earnings release calendar."""
        self._begin_operation("expected_disclosures")
        days_ahead = positive_int(days_ahead, "days_ahead", maximum=3650)
        oid = self._resolve_member_oid(ticker_or_oid) if ticker_or_oid else None
        key = self._cache_key("calendar", days_ahead=days_ahead, member_oid=oid or "", lang=self.config.lang)
        return self._cached_call(
            key,
            lambda: self.calendar.get_expected_disclosures(days_ahead=days_ahead, member_oid=oid),
            expire=self.config.cache_expiry_calendar,
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
        disclosure_index = positive_int(disclosure_index, "disclosure_index")
        ticker = normalize_ticker(ticker) if ticker else None
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
        ticker = normalize_ticker(ticker)
        year = positive_int(year, "year", maximum=2100)
        oid = self._resolve_member_oid(ticker)
        candidates: list[Disclosure] = []
        matching: list[Disclosure] = []
        for selector_year in _financial_selector_years(year, period):
            rows = self._cached_call(
                self._cache_key(
                    "company-disclosures",
                    oid=oid,
                    notification_type="FR",
                    range_value=selector_year,
                    limit=200,
                    lang=self.config.lang,
                ),
                lambda selector_year=selector_year: self.disclosures.get_company_disclosures(
                    member_oid=oid,
                    notification_type="FR",
                    range_value=selector_year,
                    limit=200,
                ),
                expire=self.config.cache_expiry_default,
            )
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
        failures: list[str] = []
        for selected in sorted(matching, key=lambda item: item.disclosure_index, reverse=True):
            statement = self._cached_call(
                self._cache_key(
                    "financial-statement",
                    lang=self.config.lang,
                    ticker=ticker.upper(),
                    disclosure_index=int(selected.disclosure_index),
                ),
                lambda selected=selected: self.financials.get_financial_statement(
                    selected.disclosure_index,
                    stock_code=ticker.upper(),
                    company_title=selected.company_title,
                ),
                expire=self.config.cache_expiry_financials,
                force_refresh=force_refresh,
            )
            if statement.items and any(str(year) in label for label in statement.period_labels):
                if self.db:
                    self.db.save_financial_statement(statement)
                return statement
            failures.append(
                f"#{selected.disclosure_index}: items={len(statement.items)}, periods={statement.period_labels}"
            )
        wanted = f"{year}{f'/{period}' if period else ''}"
        raise KapValidationError(
            f"Financial-report candidates for {ticker.upper()} ({wanted}) contained no usable statement: "
            + "; ".join(failures)
        )

    def download_financial_report_xls(self, ticker_or_oid: str, year: int | str = 2024) -> dict[str, Any]:
        """Download zipped XLS financial report package from KAP and parse tables."""
        self._begin_operation("financial_xls")
        year = positive_int(year, "year", maximum=2100)
        oid = self._resolve_member_oid(ticker_or_oid)
        key = self._cache_key("financial-xls", oid=oid, year=year, lang=self.config.lang)
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
            detail = self._cached_call(
                self._cache_key("detail", disclosure_index=disc_index, lang=self.config.lang),
                lambda: self.disclosures.get_disclosure_detail(disc_index),
                expire=self.config.cache_expiry_disclosure_detail,
            )
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


def _financial_period_matches(disclosure: Disclosure, year: int, period: str | None) -> bool:
    """Match KAP's Turkish/English report-period labels without relying on one title format."""
    raw = disclosure.raw if isinstance(disclosure.raw, dict) else {}
    basic = raw.get("disclosureBasic") if isinstance(raw.get("disclosureBasic"), dict) else raw
    raw_year = basic.get("year")
    if raw_year is not None and str(raw_year).strip():
        try:
            if int(float(str(raw_year).strip())) != int(year):
                return False
        except (TypeError, ValueError):
            return False

    haystack = " ".join(
        value
        for value in (
            disclosure.title,
            str(basic.get("title") or ""),
            str(basic.get("summary") or ""),
            str(basic.get("subject") or ""),
            str(basic.get("ruleType") or ""),
            str(basic.get("ruleTypeTerm") or ""),
            str(basic.get("term") or ""),
            str(basic.get("period") or ""),
        )
        if value
    ).casefold()
    if raw_year is None and str(year) not in haystack:
        return False
    if not period:
        return True

    normalized = re.sub(r"[^a-z0-9çğıöşü]+", "", period.casefold())
    reporting_term = basic.get("donem")
    try:
        reporting_term = int(float(str(reporting_term))) if reporting_term is not None else None
    except (TypeError, ValueError):
        reporting_term = None
    normalized_haystack = re.sub(r"[^a-z0-9çğıöşü]+", "", haystack)
    compact = re.sub(r"[^0-9]", "", haystack)
    quarter_patterns = {
        "q1": ("1çeyrek", "1ceyrek", "1quarter", "1q", "ilkçeyrek"),
        "q2": ("2çeyrek", "2ceyrek", "2quarter", "2q", "ikinciçeyrek"),
        "q3": ("3çeyrek", "3ceyrek", "3quarter", "3q", "üçüncüçeyrek", "ucuncuceyrek"),
        "q4": ("4çeyrek", "4ceyrek", "4quarter", "4q", "dördüncüçeyrek", "dorduncuceyrek"),
    }
    if normalized in {"annual", "yillik", "year", "fullyear", "fy"}:
        return reporting_term == 4 or any(token in normalized_haystack for token in ("yıllık", "yillik", "annual", "fullyear", "12aylık", "12aylik")) or "3112" + str(year) in compact
    for quarter, aliases in quarter_patterns.items():
        if normalized == quarter or normalized in aliases:
            month = {"q1": "03", "q2": "06", "q3": "09", "q4": "12"}[quarter]
            term = {"q1": 1, "q2": 2, "q3": 3, "q4": 4}[quarter]
            return reporting_term == term or any(alias.replace(" ", "") in normalized_haystack for alias in aliases) or f"{month}{year}" in compact
    return normalized in normalized_haystack


def _financial_selector_years(year: int, period: str | None) -> tuple[int, ...]:
    """Choose KAP publication-year selectors with the fewest live requests."""
    normalized = re.sub(r"[^a-z0-9]+", "", (period or "").casefold())
    next_year_first = normalized in {
        "annual", "yillik", "year", "fullyear", "fy", "q4", "4q", "4ceyrek",
    }
    return (year + 1, year) if next_year_first else (year, year + 1)


def _is_financial_statement_disclosure(disclosure: Disclosure) -> bool:
    """Separate the actual statement from other records in KAP's broad FR class."""
    raw = disclosure.raw if isinstance(disclosure.raw, dict) else {}
    basic = raw.get("disclosureBasic") if isinstance(raw.get("disclosureBasic"), dict) else raw
    text = " ".join(
        str(value)
        for value in (
            disclosure.title,
            basic.get("title"),
            basic.get("subject"),
            basic.get("summary"),
        )
        if value
    ).casefold()
    normalized = re.sub(r"[^a-z0-9çğıöşü]+", "", text)
    if any(token in normalized for token in ("sorumlulukbeyanı", "sorumlulukbeyani", "faaliyetraporu")):
        return False
    return "finansalrapor" in normalized or "financialreport" in normalized
