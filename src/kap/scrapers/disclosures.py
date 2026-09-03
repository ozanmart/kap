from __future__ import annotations

import asyncio
import datetime
from datetime import datetime as dt_cls, timedelta
import logging
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

from ..config import KapConfig
from ..constants import (
    DEFAULT_MEMBER_TYPE_CODE,
    DISCLOSURE_TYPE_CODES,
    ENDPOINT_COMPANY_DETAIL_SGBF,
    ENDPOINT_COMPANY_DISCLOSURES_BY_TYPE,
    ENDPOINT_DISCLOSURE_MAIN,
    ENDPOINT_DISCLOSURE_PAGE,
    ENDPOINT_DISCLOSURE_SUBJECTS,
    ENDPOINT_HISTORICAL_DISCLOSURES,
    ISTANBUL_TZ,
    MEMBER_TYPE_CODES,
    SUBJECT_OID_ACTIVITY_REPORT,
    SUBJECT_OID_FINANCIAL_REPORT,
    VALID_COMPANY_DISCLOSURE_TYPES,
)
from ..models.disclosure import Disclosure, DisclosureDetail, DisclosureSubject
from ..exceptions import KapError, KapValidationError
from ..parsing.html_parser import html_to_text
from .base import BaseScraper
from ..parsing.rsc import (
    extract_json_objects as _extract_json_objects,
    extract_next_payload_texts as _extract_next_payload_texts,
    iter_nested_dicts as _iter_nested_dicts,
    iter_nested_dicts,
    iter_rsc_items,
    normalize_rsc_key,
    unwrap_rsc_value,
)

logger = logging.getLogger("kap.scrapers.disclosures")

LATEST_MEMBER_TYPES = [
    MEMBER_TYPE_CODES["bist_sirketleri"],
    MEMBER_TYPE_CODES["duzenleyici_denetleyici_kurumlar"],
]

_TICKER_TOKEN_RE = re.compile(r"^[A-Z0-9]{2,10}$")


def _ticker_set(value: Any) -> set[str]:
    """Return exact ticker tokens from KAP's comma/space separated fields."""
    if value is None:
        return set()
    values = value if isinstance(value, (list, tuple, set)) else re.split(r"[,;/\s]+", str(value))
    return {
        str(token).strip().upper()
        for token in values
        if str(token).strip() and _TICKER_TOKEN_RE.fullmatch(str(token).strip().upper())
    }


def _matches_ticker(disclosure: Disclosure, ticker: str) -> bool:
    wanted = ticker.strip().upper()
    return wanted in _ticker_set(disclosure.stock_code) or wanted in _ticker_set(disclosure.related_stocks)


def _dedupe_disclosures(items: list[Disclosure]) -> list[Disclosure]:
    """Remove duplicate feed rows while retaining their first full payload."""
    unique: list[Disclosure] = []
    seen: set[str] = set()
    for item in items:
        key = str(item.disclosure_index or item.disclosure_id or "")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _require_list_payload(
    data: Any,
    *,
    endpoint: str,
    envelope_keys: tuple[str, ...] = ("data", "items", "disclosures", "content", "result"),
) -> list[Any]:
    """Accept KAP's known list/envelope shapes and reject error/HTML objects."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in envelope_keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
    raise KapValidationError(
        f"Unexpected {endpoint} response schema: expected a list, got {type(data).__name__}"
    )


def _historical_date_windows(
    from_date: datetime.date,
    to_date: datetime.date,
) -> list[tuple[datetime.date, datetime.date]]:
    """Split historical searches into KAP's accepted one-year windows."""
    today = dt_cls.today().date()
    end = min(to_date, today)
    if from_date > end:
        return []
    windows: list[tuple[datetime.date, datetime.date]] = []
    start = from_date
    while start <= end:
        window_end = min(start + timedelta(days=365), end)
        windows.append((start, window_end))
        start = window_end + timedelta(days=1)
    return windows


def _historical_payload(
    member_oid: str | None,
    from_date: datetime.date,
    to_date: datetime.date,
    disclosure_class: str,
    subject_oid: str,
    member_type: str = DEFAULT_MEMBER_TYPE_CODE,
) -> dict[str, Any]:
    """Mirror the current public KAP detailed-inquiry form payload."""
    return {
        "fromDate": str(from_date),
        "toDate": str(to_date),
        "memberType": member_type,
        "mkkMemberOidList": [member_oid] if member_oid else [],
        "inactiveMkkMemberOidList": [],
        "disclosureClass": disclosure_class,
        "subjectList": [subject_oid] if subject_oid else [],
        "isLate": "",
        "mainSector": "",
        "sector": "",
        "subSector": "",
        "marketOid": "",
        "index": "",
        "bdkReview": "",
        "bdkMemberOidList": [],
        "year": "",
        "term": "",
        "ruleType": "",
        "period": "",
        "fromSrc": False,
        "srcCategory": "",
        "disclosureIndexList": [],
    }


def _absolute_url(base_url: str, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _extract_detail_title(soup: BeautifulSoup) -> str | None:
    selectors = (
        ".notification__table .text-danger.font-semibold.text-xl",
        ".notification__table [class*='text-xl']",
        "h1",
    )
    for selector in selectors:
        for node in soup.select(selector):
            title = " ".join(node.get_text(" ", strip=True).split())
            if title and title.casefold() not in {"kap", "bildirim"}:
                return _clean_detail_title(title)
    return None


def _clean_detail_title(value: str | None) -> str | None:
    """Remove language/zoom controls that are rendered beside real titles."""
    title = " ".join(str(value or "").split())
    if not title:
        return None
    title = re.sub(r"\s+(?:A\+|A-|EN|TR)(?:\s+(?:A\+|A-|EN|TR))*\s*$", "", title, flags=re.IGNORECASE)
    return title.strip() or None


def _extract_detail_body_html(soup: BeautifulSoup, disclosure_index: int | str) -> str:
    class_name = f"notification-body-scale-{disclosure_index}"
    candidates = [
        node
        for node in soup.find_all(class_=True)
        if class_name in (node.get("class") or [])
        and "disclosureScrollableAreaScrollBar" not in (node.get("class") or [])
    ]
    if candidates:
        node = max(candidates, key=lambda item: len(item.get_text(" ", strip=True)))
        return str(node)
    return str(soup)


def _extract_rsc_attachment_objects(html: str) -> list[dict[str, Any]]:
    payload_text = _extract_next_payload_texts(html)
    if not payload_text.strip():
        return []
    return [
        row
        for row in _iter_nested_dicts(_extract_json_objects(payload_text))
        if row.get("objId") or row.get("fileId") or row.get("downloadUrl")
    ]


def _normalize_publish_date(value: str) -> str:
    """Normalize KAP's detail/feed timestamp variants to DD.MM.YYYY."""
    text = " ".join(value.split())
    for fmt in (
        "%Y.%m.%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
    ):
        try:
            return dt_cls.strptime(text, fmt).strftime("%d.%m.%Y %H:%M:%S")
        except ValueError:
            continue
    return text


def _extract_rsc_detail_metadata(html: str) -> dict[str, Any]:
    """Extract identity metadata from KAP's structured detail-page records."""
    aliases = {
        "disclosure_id": {"disclosureid", "notificationid", "bildirimid"},
        "publish_date": {"publishdate", "publishedat", "publisheddate", "yayinlanmatarihi"},
        "stock_code": {"stockcode", "companycode", "borsakodu", "paykodu"},
        "company_title": {"companytitle", "kapmembertitle", "companyname"},
        "title": {"disclosuretitle", "notificationtitle", "subject", "baslik", "title"},
        "disclosure_type": {"disclosuretype", "notificationtype"},
        "disclosure_class": {"disclosureclass", "notificationclass", "bildirimsinifi"},
    }
    rejected_values = {
        "bildirim konuları",
        "bildirim konulari",
        "bildirim tipi",
        "gönderim tarihi",
        "gonderim tarihi",
        "yıl",
        "yil",
        "periyot",
    }

    def valid_value(field: str, value: Any) -> str | None:
        if isinstance(value, (dict, list)) or value is None:
            return None
        text = " ".join(str(value).replace("\xa0", " ").split())
        if not text or text.casefold() in rejected_values:
            return None
        if field == "publish_date" and not re.search(
            r"(?:\d{2}[./-]\d{2}[./-]\d{4}|\d{4}[./-]\d{2}[./-]\d{2})",
            text,
        ):
            return None
        if field == "publish_date":
            return _normalize_publish_date(text)
        if field == "stock_code" and not _TICKER_TOKEN_RE.fullmatch(text.upper()):
            return None
        return text

    metadata: dict[str, Any] = {}
    payload = _extract_next_payload_texts(html)
    # Current KAP pages put identity under sendData.disclosure.disclosureBasic,
    # while older pages expose itemKey/itemObject records. Prefer exact keys in
    # the complete disclosureBasic object: generic UI records also contain keys
    # such as ``title`` whose values are labels ("Bildirim Konuları").
    if payload.strip():
        rows = list(iter_nested_dicts(_extract_json_objects(payload)))
        all_aliases = {alias for values in aliases.values() for alias in values}
        rows.sort(
            key=lambda row: sum(normalize_rsc_key(key) in all_aliases for key in row),
            reverse=True,
        )
        for row in rows:
            for key, value in row.items():
                normalized_key = normalize_rsc_key(str(key))
                for field, field_aliases in aliases.items():
                    if field in metadata or normalized_key not in field_aliases:
                        continue
                    clean_value = valid_value(field, unwrap_rsc_value(value))
                    if clean_value is not None:
                        metadata[field] = clean_value
                        break

    # Conservative compatibility fallback. Exact normalized keys prevent a UI
    # label record from overriding the actual disclosureBasic value.
    for record in iter_rsc_items(html):
        keys = {
            normalize_rsc_key(record.get("item_key")),
            normalize_rsc_key(record.get("item_name")),
        }
        for field, field_aliases in aliases.items():
            if field in metadata or not keys.intersection(field_aliases):
                continue
            clean_value = valid_value(field, unwrap_rsc_value(record.get("value")))
            if clean_value is not None:
                metadata[field] = clean_value
                break
    return metadata


def _extract_attachment_urls(
    soup: BeautifulSoup,
    html: str,
    base_url: str,
    lang: str,
) -> list[str]:
    urls: list[str] = []
    for anchor in soup.select(
        "a[href*='/api/file/download/'], "
        "a[href*='/api/disclosure/download/'], "
        "a.modal-attachment"
    ):
        href = str(anchor.get("href") or "").strip()
        if href:
            full_url = _absolute_url(base_url, href)
            if full_url not in urls:
                urls.append(full_url)

    for attachment in _extract_rsc_attachment_objects(html):
        href = attachment.get("downloadUrl") or attachment.get("fileUrl") or attachment.get("url")
        obj_id = attachment.get("objId") or attachment.get("fileId") or attachment.get("id")
        if not href and obj_id:
            href = f"/{lang}/api/file/download/{obj_id}"
        if href:
            full_url = _absolute_url(base_url, str(href))
            if full_url not in urls:
                urls.append(full_url)
    return urls


def parse_disclosure_detail_html(
    html: str,
    disclosure_index: int | str,
    url: str,
    base_url: str,
    lang: str,
) -> DisclosureDetail:
    """Parse a KAP notification page, including its current attachment schema."""
    soup = BeautifulSoup(html, "lxml")
    index = int(disclosure_index)
    rsc_metadata = _extract_rsc_detail_metadata(html)
    title = _clean_detail_title(rsc_metadata.get("title")) or _extract_detail_title(soup)
    body_text = html_to_text(_extract_detail_body_html(soup, index))

    company_links = soup.select("a[href*='/sirket-bilgileri/ozet/']")
    company_title = None
    stock_code = None
    if company_links:
        link_texts = [" ".join(a.get_text(" ", strip=True).split()) for a in company_links]
        company_title = next((text for text in link_texts if text and not re.fullmatch(r"[A-Z0-9]{2,10}", text.upper())), None)
        for text in link_texts:
            tokens = [token.strip().upper() for token in re.split(r"[,;/\s]+", text) if token.strip()]
            if tokens and all(_TICKER_TOKEN_RE.fullmatch(token) for token in tokens):
                # KAP may show a primary exchange ticker followed by member
                # aliases (for example "GARAN, TGB"). The detail model keeps
                # the first code as its stable primary ticker.
                stock_code = tokens[0]
                break

    stock_code = stock_code or str(rsc_metadata.get("stock_code") or "").strip().upper() or None
    company_title = company_title or rsc_metadata.get("company_title")
    publish_date = rsc_metadata.get("publish_date")
    disclosure_id = rsc_metadata.get("disclosure_id")
    disclosure_type = rsc_metadata.get("disclosure_type")
    disclosure_class = rsc_metadata.get("disclosure_class") or disclosure_type
    if disclosure_class:
        disclosure_class = str(disclosure_class).upper().replace("Ö", "O")
    attachment_urls = _extract_attachment_urls(soup, html, base_url, lang)
    attachment_metadata = _extract_rsc_attachment_objects(html)
    return DisclosureDetail(
        disclosure_index=index,
        disclosure_id=disclosure_id,
        title=title,
        content_text=body_text,
        url=url,
        stock_code=stock_code,
        company_title=company_title,
        publish_date=publish_date,
        disclosure_type=disclosure_type,
        disclosure_class=disclosure_class,
        attachment_urls=attachment_urls,
        attachment_metadata=attachment_metadata,
        raw={**rsc_metadata, "attachments": attachment_metadata},
    )


def _normalize_raw_disclosure(item: dict[str, Any], lang: str = "tr") -> Disclosure:
    """Normalize KAP raw response dictionary into a clean Disclosure model."""
    basic = item.get("disclosureBasic") if isinstance(item, dict) else None
    basic = basic if isinstance(basic, dict) else {}

    disc_id = str(
        basic.get("disclosureId")
        or item.get("disclosureId")
        or basic.get("id")
        or item.get("id")
        or ""
    ) or None
    raw_index = basic.get("disclosureIndex") or item.get("disclosureIndex") or 0
    try:
        disc_index = int(raw_index)
    except (TypeError, ValueError):
        disc_index = 0
    stock_value = basic.get("stockCode") or item.get("stockCode") or item.get("stockCodes")
    stock_tokens = sorted(_ticker_set(stock_value))
    stock_code = ", ".join(stock_tokens) or None

    related_value = basic.get("relatedStocks") or item.get("relatedStocks")
    related_tokens = sorted(_ticker_set(related_value))
    related_stocks = ", ".join(related_tokens) or (str(related_value).strip() if related_value else None)

    return Disclosure(
        disclosure_id=disc_id,
        disclosure_index=disc_index,
        publish_date=basic.get("publishDate") or item.get("publishDate"),
        company_title=(
            basic.get("companyTitle")
            or item.get("companyTitle")
            or item.get("kapMemberTitle")
            or item.get("kapTitle")
        ),
        stock_code=stock_code,
        related_stocks=related_stocks,
        title=basic.get("title") or item.get("title") or item.get("subject"),
        disclosure_type=(
            basic.get("disclosureType")
            or item.get("disclosureType")
            or basic.get("disclosureClass")
            or item.get("disclosureClass")
        ),
        disclosure_class=basic.get("disclosureClass") or item.get("disclosureClass"),
        disclosure_category=basic.get("disclosureCategory") or item.get("disclosureCategory"),
        url=f"https://www.kap.org.tr/{lang}/Bildirim/{disc_index}" if disc_index else None,
        raw=item,
    )


class DisclosuresScraper:
    """Handles real-time and historical disclosure querying from KAP API endpoints."""

    def __init__(self, base_scraper: BaseScraper | None = None, config: KapConfig | None = None) -> None:
        self.config = config or KapConfig()
        self.base = base_scraper or BaseScraper(self.config)

    # ── Main Feed ────────────────────────────────────────────────────────────

    def fetch_main_feed(self, payload: dict[str, Any] | None = None) -> list[Disclosure]:
        """Fetch the active disclosure list from KAP main endpoint."""
        route = ENDPOINT_DISCLOSURE_MAIN.format(lang=self.config.lang)
        resp = self.base.request_sync("POST", route, json=payload or {})
        def parse() -> list[Disclosure]:
            data = _require_list_payload(resp.json(), endpoint="main disclosure feed")
            return _dedupe_disclosures([_normalize_raw_disclosure(x, self.config.lang) for x in data if isinstance(x, dict)])

        return self.base.run_with_deadline_sync(parse, deadline_at=self.base.operation_deadline())

    async def afetch_main_feed(self, payload: dict[str, Any] | None = None) -> list[Disclosure]:
        """Async fetch the active disclosure list from KAP main endpoint."""
        route = ENDPOINT_DISCLOSURE_MAIN.format(lang=self.config.lang)
        resp = await self.base.request_async("POST", route, json=payload or {})
        def parse() -> list[Disclosure]:
            data = _require_list_payload(resp.json(), endpoint="main disclosure feed")
            return _dedupe_disclosures([_normalize_raw_disclosure(x, self.config.lang) for x in data if isinstance(x, dict)])

        return await self.base.run_with_deadline_async(parse, deadline_at=self.base.operation_deadline())

    # ── Today's Disclosures ──────────────────────────────────────────────────

    def get_today_disclosures(
        self,
        member_type: str = "bist_sirketleri",
        disclosure_types: list[str] | None = None,
    ) -> list[Disclosure]:
        """Get today's disclosures in Istanbul time.

        Args:
            member_type: Member type key ('bist_sirketleri', 'yatirim_kuruluslari', etc. or code 'IGS')
            disclosure_types: List of disclosure type codes (e.g. ['ODA', 'FR'])
        """
        member_code = MEMBER_TYPE_CODES.get(member_type, member_type or DEFAULT_MEMBER_TYPE_CODE)
        today = dt_cls.now(ISTANBUL_TZ).date()
        if member_code == DEFAULT_MEMBER_TYPE_CODE:
            # The active main feed is an incomplete, time-varying window and
            # leaks general BIST/KAP notices into an IGS request. The detailed
            # public query is the website's authoritative complete day view.
            disclosure_class = disclosure_types[0] if disclosure_types and len(disclosure_types) == 1 else ""
            route = ENDPOINT_HISTORICAL_DISCLOSURES.format(lang=self.config.lang)
            resp = self.base.request_sync(
                "POST",
                route,
                json=_historical_payload(None, today, today, disclosure_class, "", member_code),
            )
            today_items = self.base.run_with_deadline_sync(
                lambda: [
                    _normalize_raw_disclosure(item, self.config.lang)
                    for item in _require_list_payload(resp.json(), endpoint="today company disclosures")
                    if isinstance(item, dict)
                ],
                deadline_at=self.base.operation_deadline(),
            )
        else:
            payload: dict[str, Any] = {"memberTypes": [member_code]}
            if disclosure_types:
                payload["disclosureTypes"] = disclosure_types
            all_disclosures = self.fetch_main_feed(payload)
            today_prefix = today.strftime("%d.%m.%Y")
            today_items = [d for d in all_disclosures if d.publish_date and d.publish_date.startswith(today_prefix)]
        if disclosure_types:
            wanted = {str(item).upper() for item in disclosure_types}
            today_items = [d for d in today_items if (d.disclosure_type or "").upper() in wanted]
        today_items.sort(key=lambda d: d.disclosure_index, reverse=True)
        return today_items

    async def aget_today_disclosures(
        self,
        member_type: str = "bist_sirketleri",
        disclosure_types: list[str] | None = None,
    ) -> list[Disclosure]:
        """Async get today's disclosures."""
        member_code = MEMBER_TYPE_CODES.get(member_type, member_type or DEFAULT_MEMBER_TYPE_CODE)
        today = dt_cls.now(ISTANBUL_TZ).date()
        if member_code == DEFAULT_MEMBER_TYPE_CODE:
            disclosure_class = disclosure_types[0] if disclosure_types and len(disclosure_types) == 1 else ""
            route = ENDPOINT_HISTORICAL_DISCLOSURES.format(lang=self.config.lang)
            resp = await self.base.request_async(
                "POST",
                route,
                json=_historical_payload(None, today, today, disclosure_class, "", member_code),
            )
            today_items = await self.base.run_with_deadline_async(
                lambda: [
                    _normalize_raw_disclosure(item, self.config.lang)
                    for item in _require_list_payload(resp.json(), endpoint="today company disclosures")
                    if isinstance(item, dict)
                ],
                deadline_at=self.base.operation_deadline(),
            )
        else:
            payload: dict[str, Any] = {"memberTypes": [member_code]}
            if disclosure_types:
                payload["disclosureTypes"] = disclosure_types
            all_disclosures = await self.afetch_main_feed(payload)
            today_prefix = today.strftime("%d.%m.%Y")
            today_items = [d for d in all_disclosures if d.publish_date and d.publish_date.startswith(today_prefix)]
        if disclosure_types:
            wanted = {str(item).upper() for item in disclosure_types}
            today_items = [d for d in today_items if (d.disclosure_type or "").upper() in wanted]
        today_items.sort(key=lambda d: d.disclosure_index, reverse=True)
        return today_items

    # ── Latest Disclosures ───────────────────────────────────────────────────

    def get_latest_disclosures(
        self,
        limit: int = 50,
        ticker: str | None = None,
        disclosure_types: list[str] | None = None,
    ) -> list[Disclosure]:
        """Get the latest disclosures across all companies or filtered by ticker."""
        payload: dict[str, Any] = {
            "memberTypes": list(LATEST_MEMBER_TYPES),
            "disclosureTypes": list(disclosure_types or []),
        }

        items = self.fetch_main_feed(payload)
        if disclosure_types:
            wanted = {str(item).upper() for item in disclosure_types}
            items = [d for d in items if (d.disclosure_type or "").upper() in wanted]
        if ticker:
            items = [d for d in items if _matches_ticker(d, ticker)]
        items.sort(key=lambda d: d.disclosure_index, reverse=True)
        return items[: max(0, int(limit))]

    async def aget_latest_disclosures(
        self,
        limit: int = 50,
        ticker: str | None = None,
        disclosure_types: list[str] | None = None,
    ) -> list[Disclosure]:
        """Async get the latest disclosures."""
        payload: dict[str, Any] = {
            "memberTypes": list(LATEST_MEMBER_TYPES),
            "disclosureTypes": list(disclosure_types or []),
        }

        items = await self.afetch_main_feed(payload)
        if disclosure_types:
            wanted = {str(item).upper() for item in disclosure_types}
            items = [d for d in items if (d.disclosure_type or "").upper() in wanted]
        if ticker:
            items = [d for d in items if _matches_ticker(d, ticker)]
        items.sort(key=lambda d: d.disclosure_index, reverse=True)
        return items[: max(0, int(limit))]

    # ── Company Historical Disclosures ───────────────────────────────────────

    def get_company_disclosures(
        self,
        member_oid: str,
        notification_type: str = "ALL",
        range_value: int = 365,
        limit: int = 50,
    ) -> list[Disclosure]:
        """Fetch historical announcements for a specific company by member OID.

        Args:
            member_oid: KAP MKK member OID
            notification_type: Filter code ('ALL', 'FR', 'ODA', 'DUY', 'DG')
            range_value: Days range (e.g. 30, 90, 365) or year (e.g. 2024)
            limit: Maximum items to return
        """
        route = ENDPOINT_COMPANY_DETAIL_SGBF.format(
            lang=self.config.lang,
            member_oid=member_oid.strip(),
            notification_type=notification_type.upper().strip(),
            range_value=range_value,
        )
        resp = self.base.request_sync("GET", route)
        def parse() -> list[Disclosure]:
            data = _require_list_payload(resp.json(), endpoint="company disclosures")
            items = [_normalize_raw_disclosure(x, self.config.lang) for x in data if isinstance(x, dict)]
            items.sort(key=lambda d: d.disclosure_index, reverse=True)
            return items[: max(1, limit)]

        return self.base.run_with_deadline_sync(parse, deadline_at=self.base.operation_deadline())

    async def aget_company_disclosures(
        self,
        member_oid: str,
        notification_type: str = "ALL",
        range_value: int = 365,
        limit: int = 50,
    ) -> list[Disclosure]:
        """Async fetch historical announcements for a specific company."""
        route = ENDPOINT_COMPANY_DETAIL_SGBF.format(
            lang=self.config.lang,
            member_oid=member_oid.strip(),
            notification_type=notification_type.upper().strip(),
            range_value=range_value,
        )
        resp = await self.base.request_async("GET", route)
        def parse() -> list[Disclosure]:
            data = _require_list_payload(resp.json(), endpoint="company disclosures")
            items = [_normalize_raw_disclosure(x, self.config.lang) for x in data if isinstance(x, dict)]
            items.sort(key=lambda d: d.disclosure_index, reverse=True)
            return items[: max(1, limit)]

        return await self.base.run_with_deadline_async(parse, deadline_at=self.base.operation_deadline())

    def get_historical_disclosures_by_criteria(
        self,
        member_oid: str,
        from_date: datetime.date | None = None,
        to_date: datetime.date | None = None,
        disclosure_class: str = "FR",
        subject_oid: str = SUBJECT_OID_FINANCIAL_REPORT,
    ) -> list[Disclosure]:
        """Query historical disclosures via criteria POST endpoint."""
        from_d = from_date or (dt_cls.today().date() - timedelta(days=365))
        to_d = to_date or dt_cls.today().date()

        route = ENDPOINT_HISTORICAL_DISCLOSURES.format(lang=self.config.lang)
        results: list[Disclosure] = []
        for start, end in _historical_date_windows(from_d, to_d):
            resp = self.base.request_sync(
                "POST",
                route,
                json=_historical_payload(member_oid, start, end, disclosure_class, subject_oid),
            )
            rows = self.base.run_with_deadline_sync(
                lambda resp=resp: [
                    _normalize_raw_disclosure(x, self.config.lang)
                    for x in _require_list_payload(resp.json(), endpoint="historical disclosures")
                    if isinstance(x, dict)
                ],
                deadline_at=self.base.operation_deadline(),
            )
            results.extend(rows)
        return sorted(_dedupe_disclosures(results), key=lambda item: item.disclosure_index, reverse=True)

    async def aget_historical_disclosures_by_criteria(
        self,
        member_oid: str,
        from_date: datetime.date | None = None,
        to_date: datetime.date | None = None,
        disclosure_class: str = "FR",
        subject_oid: str = SUBJECT_OID_FINANCIAL_REPORT,
    ) -> list[Disclosure]:
        """Async query historical disclosures via criteria POST endpoint."""
        from_d = from_date or (dt_cls.today().date() - timedelta(days=365))
        to_d = to_date or dt_cls.today().date()

        route = ENDPOINT_HISTORICAL_DISCLOSURES.format(lang=self.config.lang)

        async def fetch_window(start: datetime.date, end: datetime.date) -> list[Disclosure]:
            resp = await self.base.request_async(
                "POST",
                route,
                json=_historical_payload(member_oid, start, end, disclosure_class, subject_oid),
            )
            return await self.base.run_with_deadline_async(
                lambda: [
                    _normalize_raw_disclosure(x, self.config.lang)
                    for x in _require_list_payload(resp.json(), endpoint="historical disclosures")
                    if isinstance(x, dict)
                ],
                deadline_at=self.base.operation_deadline(),
            )

        # KAP only accepts one-year windows, so a decade-long query is ten
        # requests. Run them concurrently under the shared max_concurrency
        # semaphore instead of paying ten sequential round trips; gather
        # preserves window order, so deduplication still keeps the earliest
        # window's payload for a disclosure that appears in two windows.
        windows = _historical_date_windows(from_d, to_d)
        results: list[Disclosure] = []
        for rows in await asyncio.gather(*(fetch_window(start, end) for start, end in windows)):
            results.extend(rows)
        return sorted(_dedupe_disclosures(results), key=lambda item: item.disclosure_index, reverse=True)

    # ── Disclosure by Type (FAR, KYUR, SUR, KDP, DEG) ─────────────────────────

    def get_company_disclosures_by_type(self, member_oid: str, disclosure_type: str = "FAR") -> list[dict[str, Any]]:
        """Fetch disclosures of a specific type (e.g. 'FAR' - Activity Reports, 'KYUR', 'SUR', 'KDP')."""
        dtype = disclosure_type.upper().strip()
        if dtype not in VALID_COMPANY_DISCLOSURE_TYPES:
            raise ValueError(f"Invalid disclosure_type '{dtype}'. Must be one of: {sorted(VALID_COMPANY_DISCLOSURE_TYPES.keys())}")

        route = ENDPOINT_COMPANY_DISCLOSURES_BY_TYPE.format(
            lang=self.config.lang,
            disclosure_type=dtype,
            member_oid=member_oid.strip(),
        )
        resp = self.base.request_sync("GET", route)
        return self.base.run_with_deadline_sync(
            lambda: [
                x.get("disclosureBasic", x)
                for x in _require_list_payload(resp.json(), endpoint=f"{dtype} disclosures")
                if isinstance(x, dict)
            ],
            deadline_at=self.base.operation_deadline(),
        )

    async def aget_company_disclosures_by_type(
        self,
        member_oid: str,
        disclosure_type: str = "FAR",
    ) -> list[dict[str, Any]]:
        """Async fetch disclosures of a specific company-profile type."""
        dtype = disclosure_type.upper().strip()
        if dtype not in VALID_COMPANY_DISCLOSURE_TYPES:
            raise ValueError(
                f"Invalid disclosure_type '{dtype}'. Must be one of: "
                f"{sorted(VALID_COMPANY_DISCLOSURE_TYPES.keys())}"
            )
        route = ENDPOINT_COMPANY_DISCLOSURES_BY_TYPE.format(
            lang=self.config.lang,
            disclosure_type=dtype,
            member_oid=member_oid.strip(),
        )
        resp = await self.base.request_async("GET", route)
        return await self.base.run_with_deadline_async(
            lambda: [
                x.get("disclosureBasic", x)
                for x in _require_list_payload(resp.json(), endpoint=f"{dtype} disclosures")
                if isinstance(x, dict)
            ],
            deadline_at=self.base.operation_deadline(),
        )

    # ── Disclosure Subjects ──────────────────────────────────────────────────

    def get_disclosure_subjects(self, disclosure_class: str = "FR") -> list[DisclosureSubject]:
        """Fetch available disclosure subjects for a disclosure class ('FR', 'ODA', 'DG')."""
        route = ENDPOINT_DISCLOSURE_SUBJECTS.format(lang=self.config.lang, disclosure_class=disclosure_class.upper())
        resp = self.base.request_sync("GET", route)
        return self.base.run_with_deadline_sync(
            lambda: [
                DisclosureSubject(
                    disclosure_class=x.get("disclosureClass", disclosure_class),
                    subject=x.get("subject", ""),
                    subject_oid=x.get("subjectOid", ""),
                )
                for x in _require_list_payload(resp.json(), endpoint="disclosure subjects")
                if isinstance(x, dict)
            ],
            deadline_at=self.base.operation_deadline(),
        )

    async def aget_disclosure_subjects(self, disclosure_class: str = "FR") -> list[DisclosureSubject]:
        """Async fetch available disclosure subjects for a class."""
        route = ENDPOINT_DISCLOSURE_SUBJECTS.format(
            lang=self.config.lang,
            disclosure_class=disclosure_class.upper(),
        )
        resp = await self.base.request_async("GET", route)
        return await self.base.run_with_deadline_async(
            lambda: [
                DisclosureSubject(
                    disclosure_class=x.get("disclosureClass", disclosure_class),
                    subject=x.get("subject", ""),
                    subject_oid=x.get("subjectOid", ""),
                )
                for x in _require_list_payload(resp.json(), endpoint="disclosure subjects")
                if isinstance(x, dict)
            ],
            deadline_at=self.base.operation_deadline(),
        )

    # ── Disclosure Detail HTML & Attachments ──────────────────────────────────

    def get_disclosure_detail(self, disclosure_index: int | str) -> DisclosureDetail:
        """Fetch single disclosure page, parse clean text and list attachments."""
        route = ENDPOINT_DISCLOSURE_PAGE.format(lang=self.config.lang, disclosure_index=disclosure_index)
        resp = self.base.request_sync("GET", route)
        full_url = f"{self.config.base_url.rstrip('/')}{route}"
        return self.base.run_with_deadline_sync(
            lambda: parse_disclosure_detail_html(
                resp.text,
                disclosure_index=disclosure_index,
                url=full_url,
                base_url=self.config.base_url,
                lang=self.config.lang,
            ),
            deadline_at=self.base.operation_deadline(),
        )

    async def aget_disclosure_detail(self, disclosure_index: int | str) -> DisclosureDetail:
        """Async fetch single disclosure detail."""
        route = ENDPOINT_DISCLOSURE_PAGE.format(lang=self.config.lang, disclosure_index=disclosure_index)
        resp = await self.base.request_async("GET", route)
        full_url = f"{self.config.base_url.rstrip('/')}{route}"
        return await self.base.run_with_deadline_async(
            lambda: parse_disclosure_detail_html(
                resp.text,
                disclosure_index=disclosure_index,
                url=full_url,
                base_url=self.config.base_url,
                lang=self.config.lang,
            ),
            deadline_at=self.base.operation_deadline(),
        )
