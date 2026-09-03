from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any
from bs4 import BeautifulSoup

from ..config import KapConfig
from ..models.company import CompanyGeneralInfo, FreeFloatInfo, Shareholder, Subsidiary
from ..parsing.html_parser import clean_text, normalize_numeric_value
from ..parsing.rsc import iter_rsc_items, normalize_rsc_key, unwrap_rsc_value
from .base import BaseScraper

logger = logging.getLogger("kap.scrapers.company_general")

LABEL_WEBSITE = "İnternet Adresi"
LABEL_ACTIVITY = "Şirketin Faaliyet Konusu"
LABEL_AUDITOR = "Bağımsız Denetim Kuruluşu"
LABEL_SECTOR = "Şirketin Sektörü"
LABEL_MARKET = "Sermaye Piyasası Aracının İşlem Gördüğü Pazar"
LABEL_INDICES = "Şirketin Dahil Olduğu Endeksler"

TITLE_EXCHANGES = "Son Durum İtibariyle Ortaklık Sermaye Piyasası Araçlarının Kote Edildiği Diğer Borsalar"
TITLE_SHAREHOLDERS = "Sermayede Doğrudan %5 veya Daha Fazla Paya veya Oy Hakkına Sahip Gerçek ve Tüzel Kişiler"
TITLE_FREE_FLOAT = "Fiili Dolaşımdaki Paylar"
TITLE_SUBSIDIARIES = "Bağlı Ortaklıklar, Finansal Duran Varlıklar ile Finansal Yatırımlar"


def _normalize_label(value: str | None) -> str:
    """Normalize live KAP table headers for spacing and punctuation changes."""
    folded = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(char for char in folded if char.isalnum() and not unicodedata.combining(char))


def _normalize_row_value(value: Any) -> Any:
    """Strip source-markup whitespace from text without flattening wrappers.

    Values taken straight from an RSC payload still carry the markup's newlines
    and non-breaking spaces. Non-text values stay untouched so their own
    handlers (for example :func:`_currency_code`) can still unwrap them.
    """
    if isinstance(value, str):
        return clean_text(value) or None
    return value


def _row_value(row: dict[str, Any], *keys: str) -> Any:
    """Read a table value using exact or normalized header aliases."""
    for key in keys:
        value = row.get(key)
        if value is not None:
            return _normalize_row_value(value)

    normalized = {_normalize_label(key): value for key, value in row.items()}
    for key in keys:
        value = normalized.get(_normalize_label(key))
        if value is not None:
            return _normalize_row_value(value)
    return None


def _find_title_node(soup: BeautifulSoup, title_text: str):
    target = clean_text(title_text)
    fallback = None
    for node in soup.select(".company__sgbf-h6-title, h3, h4, h5, h6"):
        text = clean_text(node.get_text(" ", strip=True))
        if text == target:
            return node
        if target and target in text and fallback is None:
            fallback = node
    return fallback


def _extract_scalar_field(soup: BeautifulSoup, title_text: str) -> str | None:
    title_node = _find_title_node(soup, title_text)
    if title_node is None:
        return None

    empty_values = {"-", "Bilgi Mevcut Değil", "Seçim Yapınız"}

    # Live KAP renders scalar fields as a label/value pair in the same small
    # flex container.  Looking at the next global DOM node can jump from the
    # activity section into the contact table (and used to return e-mail or
    # phone values as the website/activity/auditor fields).
    for parent in (title_node.parent, title_node.parent.parent if title_node.parent else None):
        if parent is None:
            continue
        for sibling in title_node.next_siblings if parent is title_node.parent else parent.find_all(recursive=False):
            if getattr(sibling, "name", None) is None:
                continue
            if sibling is title_node:
                continue
            val = clean_text(sibling.get_text(" ", strip=True))
            if val and val not in empty_values and val != clean_text(title_text):
                return val

        for candidate in parent.find_all(["span", "div", "p"], recursive=True):
            if candidate is title_node or candidate.find(title_node) is not None:
                continue
            classes = set(candidate.get("class") or [])
            if {"font-normal", "mt-2", "html__parser-container"}.intersection(classes):
                val = clean_text(candidate.get_text(" ", strip=True))
                if val and val not in empty_values and val != clean_text(title_text):
                    return val

    # Conservative fallback for older HTML: only consider the next element
    # before another section heading, never the next table in the entire page.
    for next_node in title_node.find_all_next(["p", "div", "span"], limit=8):
        if next_node is title_node:
            continue
        if next_node.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            break
        val = clean_text(next_node.get_text(" ", strip=True))
        if val and val not in empty_values and val != clean_text(title_text):
            return val
    return None


def _parse_html_table(table_node) -> list[dict[str, str]]:
    if not table_node:
        return []
    headers = [clean_text(th.get_text(" ", strip=True)) for th in table_node.select("thead th, tr th")]
    headers = [h for h in headers if h]
    if not headers:
        first_row = table_node.select_one("tr")
        if first_row:
            headers = [clean_text(td.get_text(" ", strip=True)) for td in first_row.find_all(["td", "th"])]

    rows: list[dict[str, str]] = []
    for tr in table_node.select("tbody tr, tr"):
        cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        if not cells or len(cells) < len(headers):
            continue
        row = {headers[i]: cells[i] for i in range(min(len(headers), len(cells)))}
        if any(v and v not in {"-", "Bilgi Mevcut Değil"} for v in row.values()):
            rows.append(row)
    return rows


def _extract_table_rows(soup: BeautifulSoup, title_text: str) -> list[dict[str, str]]:
    title_node = _find_title_node(soup, title_text)
    if title_node is None:
        return []

    # Scope the lookup to the section that owns the heading.  The previous
    # global ``find_next('table')`` crossed section boundaries and made the
    # subsidiary parser consume the contact/e-mail table on live pages.
    table = None
    for ancestor in title_node.parents:
        classes = set(ancestor.get("class") or [])
        if {"p-6", "px-0"}.issubset(classes):
            table = ancestor.find("table")
            break
        if ancestor.name in {"body", "html"}:
            break
    if table is None:
        for sibling in title_node.find_next_siblings():
            if getattr(sibling, "name", None) is None:
                continue
            table = sibling.find("table") if sibling.name != "table" else sibling
            if table is not None:
                break
    return _parse_html_table(table)


def _rsc_scalar_fields(html: str) -> dict[str, str]:
    """Read KAP's structured ``itemKey/itemObject.value`` scalar fields."""
    aliases = {
        "company_title": ("companytitle", "kapmembertitle", "unvan"),
        "website": ("internetadresi", "internetaddress", "website", "websitesi"),
        "activity_field": ("sirketinfaaliyetkonusu", "activityfield", "activitysubject"),
        "auditor": ("bagimsizdenetimkurulusu", "auditor", "independentaudit"),
        "sector": ("sirketinsektoru", "sector", "mainsector"),
        "market": ("sermayepiyasasiaracininislemgordugupazar", "market", "tradingmarket"),
        "indices": ("sirketindahilolduguendeksler", "indices", "index"),
    }
    result: dict[str, str] = {}
    for record in iter_rsc_items(html):
        haystack = " ".join(
            normalize_rsc_key(record.get(name))
            for name in ("item_key", "item_name")
        )
        value = unwrap_rsc_value(record.get("value"))
        if isinstance(value, list):
            value = " / ".join(clean_text(item) for item in value if clean_text(item))
        elif isinstance(value, dict):
            value = value.get("label") or value.get("name") or value.get("title")
        if value is None:
            continue
        clean_value = clean_text(str(value))
        if not clean_value or clean_value in {"-", "Bilgi Mevcut Değil", "Seçim Yapınız"}:
            continue
        for field, field_aliases in aliases.items():
            if field in result:
                continue
            if any(alias in haystack for alias in field_aliases):
                result[field] = clean_value
                break
    return result


def _rsc_table_rows(html: str, *title_fragments: str) -> list[dict[str, Any]]:
    """Return a structured table carried in a current KAP RSC item value."""
    wanted = tuple(_normalize_label(fragment) for fragment in title_fragments)
    for record in iter_rsc_items(html):
        key = " ".join(
            str(record.get(name) or "")
            for name in ("item_key", "item_name")
        )
        normalized = _normalize_label(key)
        if not any(fragment and fragment in normalized for fragment in wanted):
            continue
        value = unwrap_rsc_value(record.get("value"))
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def _currency_code(value: Any, default: str = "TRY") -> str:
    if isinstance(value, dict):
        value = value.get("key") or value.get("text") or value.get("value")
    text = clean_text(str(value or ""))
    return text.upper() if text else default


def parse_company_general_html(html: str, member_oid: str, url: str) -> CompanyGeneralInfo:
    """Parse raw HTML of KAP company general info page into CompanyGeneralInfo model."""
    soup = BeautifulSoup(html, "lxml")
    rsc_fields = _rsc_scalar_fields(html)

    wrapper = soup.select_one(".company__sgfb-wrapper, div[companyname]")
    company_title = clean_text(wrapper.get("companyname")) if wrapper else None
    if not company_title:
        h1 = soup.find("h1")
        company_title = clean_text(h1.get_text(strip=True)) if h1 else None

    website_raw = rsc_fields.get("website") or _extract_scalar_field(soup, LABEL_WEBSITE)
    websites: list[str] = []
    if website_raw:
        websites = [clean_text(w) for w in re.split(r"\s+/\s+", website_raw) if clean_text(w)]

    activity_field = rsc_fields.get("activity_field") or _extract_scalar_field(soup, LABEL_ACTIVITY)
    auditor = rsc_fields.get("auditor") or _extract_scalar_field(soup, LABEL_AUDITOR)
    sector = rsc_fields.get("sector") or _extract_scalar_field(soup, LABEL_SECTOR)
    market = rsc_fields.get("market") or _extract_scalar_field(soup, LABEL_MARKET)
    indices = rsc_fields.get("indices") or _extract_scalar_field(soup, LABEL_INDICES)

    # Shareholders >=5%
    raw_shareholders = _extract_table_rows(soup, TITLE_SHAREHOLDERS)
    if not raw_shareholders:
        raw_shareholders = _rsc_table_rows(html, "sermayede_dogrudan", TITLE_SHAREHOLDERS)
    shareholders: list[Shareholder] = []
    for r in raw_shareholders:
        title = _row_value(
            r,
            "Ortağın Adı-Soyadı/Ticaret Ünvanı",
            "Ortağın Adı Soyadı / Ticaret Ünvanı",
            "shareholder",
        ) or _normalize_row_value(list(r.values())[0])
        if not title or _normalize_label(str(title)) in {"diğer", "diger", "toplam", "other", "total"}:
            continue
        nominal = normalize_numeric_value(
            _row_value(
                r,
                "Sermayedeki Payı (TL)",
                "Sermayedeki Payı(TL)",
                "Sermayedeki Payı",
                "shareInCapital",
            )
        )
        share_ratio = normalize_numeric_value(
            _row_value(
                r,
                "Sermayedeki Payı (%)",
                "Sermayedeki Payı(%)",
                "Sermaye Payı (%)",
                "ratioInCapital",
            )
        )
        voting_ratio = normalize_numeric_value(
            _row_value(
                r,
                "Oy Hakkı Oranı (%)",
                "Oy Hakkı Oranı(%)",
                "Oy Hakkı Payı (%)",
                "votingRightRatio",
            )
        )
        shareholders.append(
            Shareholder(
                name_or_title=title,
                nominal_value=float(nominal) if nominal is not None else None,
                share_ratio=float(share_ratio) if share_ratio is not None else None,
                voting_ratio=float(voting_ratio) if voting_ratio is not None else None,
            )
        )

    # Free Float
    raw_float = _extract_table_rows(soup, TITLE_FREE_FLOAT)
    if not raw_float:
        raw_float = _rsc_table_rows(html, "fiili_dolasimdaki_pay", TITLE_FREE_FLOAT)
    free_floats: list[FreeFloatInfo] = []
    ticker = None
    for r in raw_float:
        code = _row_value(r, "Borsa Kodu", "Pay Kodu", "isin", "stockCode")
        if code and not ticker:
            ticker = str(code).strip().upper()
        nominal = normalize_numeric_value(
            _row_value(
                r,
                "Fiili Dolaşımdaki Payların Nominal Tutarı (TL)",
                "Fiili Dolaşımdaki Pay Tutarı(TL)",
                "Nominal Tutar",
                "actualSharesOutstanding",
            )
        )
        ratio = normalize_numeric_value(
            _row_value(
                r,
                "Fiili Dolaşımdaki Payların Halka Açık Piyasa Değerine Oranı (%)",
                "Fiili Dolaşımdaki Pay Oranı(%)",
                "Fiili Dolaşım Oranı (%)",
                "Oran (%)",
                "actualOutstandingSharesRatio",
            )
        )
        free_floats.append(
            FreeFloatInfo(
                stock_code=str(code).strip().upper() if code else None,
                nominal_value=float(nominal) if nominal is not None else None,
                float_ratio=float(ratio) if ratio is not None else None,
            )
        )

    # Subsidiaries & Affiliates
    raw_sub = _extract_table_rows(soup, TITLE_SUBSIDIARIES)
    if not raw_sub:
        raw_sub = _rsc_table_rows(html, "bagli_ortakliklar", TITLE_SUBSIDIARIES)
    subsidiaries: list[Subsidiary] = []
    for r in raw_sub:
        sub_title = _row_value(r, "Ticaret Ünvanı", "Şirket Ünvanı", "companyTitle") or _normalize_row_value(list(r.values())[0])
        if not sub_title:
            continue
        act = _row_value(r, "Faaliyet Konusu", "scopeOfActivitiesOfCompany")
        cap = normalize_numeric_value(
            _row_value(r, "Ödenmiş/Çıkarılmış Sermayesi", "Sermayesi", "paidInOrIssuedCapital")
        )
        amt = normalize_numeric_value(
            _row_value(r, "Şirketin Sermayedeki Payı", "Pay Tutarı", "capitalShareOfCompany")
        )
        sub_ratio = normalize_numeric_value(
            _row_value(
                r,
                "Şirketin Sermayedeki Payı (%)",
                "Sermaye Payı (%)",
                "Oran (%)",
                "ratioOfCapitalShareOfCompany",
            )
        )
        curr = _currency_code(_row_value(r, "Para Birimi", "monetaryUnit"))
        subsidiaries.append(
            Subsidiary(
                company_title=sub_title,
                activity_field=act,
                paid_capital=float(cap) if cap is not None else None,
                share_amount=float(amt) if amt is not None else None,
                share_ratio=float(sub_ratio) if sub_ratio is not None else None,
                currency=curr,
            )
        )

    # Other Exchanges
    other_exchanges: list[dict[str, Any]] = [dict(x) for x in _extract_table_rows(soup, TITLE_EXCHANGES)]

    return CompanyGeneralInfo(
        member_oid=member_oid,
        ticker=ticker,
        company_title=company_title or rsc_fields.get("company_title"),
        website=websites[0] if websites else None,
        websites=websites,
        activity_field=activity_field,
        auditor=auditor,
        sector=sector,
        market=market,
        indices=indices,
        other_exchanges=other_exchanges,
        major_shareholders=shareholders,
        free_float=free_floats,
        subsidiaries=subsidiaries,
        source_url=url,
    )


class CompanyGeneralScraper:
    """Scrapes comprehensive company profile and corporate governance metadata from KAP."""

    def __init__(self, base_scraper: BaseScraper | None = None, config: KapConfig | None = None) -> None:
        self.config = config or KapConfig()
        self.base = base_scraper or BaseScraper(self.config)

    def get_company_general_info(self, member_oid: str) -> CompanyGeneralInfo:
        """Fetch and parse Genel Bilgiler for a given company by its MKK Member OID."""
        url = f"/{self.config.lang}/sirket-bilgileri/genel/{member_oid.strip()}"
        resp = self.base.request_sync("GET", url)
        full_url = f"{self.config.base_url.rstrip('/')}{url}"
        return self.base.run_with_deadline_sync(
            lambda: parse_company_general_html(resp.text, member_oid=member_oid, url=full_url),
            deadline_at=self.base.operation_deadline(),
        )

    async def aget_company_general_info(self, member_oid: str) -> CompanyGeneralInfo:
        """Async fetch and parse Genel Bilgiler."""
        url = f"/{self.config.lang}/sirket-bilgileri/genel/{member_oid.strip()}"
        resp = await self.base.request_async("GET", url)
        full_url = f"{self.config.base_url.rstrip('/')}{url}"
        return await self.base.run_with_deadline_async(
            lambda: parse_company_general_html(resp.text, member_oid=member_oid, url=full_url),
            deadline_at=self.base.operation_deadline(),
        )
