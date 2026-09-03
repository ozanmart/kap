from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal
from bs4 import BeautifulSoup

from ..config import KapConfig
from ..constants import ENDPOINT_DISCLOSURE_PAGE, STATEMENT_NAME_BY_ROLE
from ..models.financials import FinancialLineItem, FinancialStatement
from ..parsing.html_parser import clean_text, normalize_decimal_value, normalize_numeric_value
from .base import BaseScraper

_ROLE_CLASS_RE = re.compile(r"^tbl_[a-z]+_role_(\d+)$")
_TABLE_ROLE_SELECTOR = (
    "table.financial-table[class*='tbl_'][class*='_role_'], "
    "table[class*='tbl_'][class*='_role_']"
)
_PERIOD_DATE_RE = re.compile(r"\b(\d{2}[./]\d{2}[./]\d{4})\b")


def _extract_statement_role_code(table_node) -> str | None:
    for cls in table_node.get("class") or []:
        match = _ROLE_CLASS_RE.match(str(cls))
        if match:
            return match.group(1)
    return None


def _extract_taxonomy_code(raw_value: str | None) -> str:
    raw = clean_text(raw_value)
    if not raw:
        return ""
    return clean_text(raw.split("|", 1)[0])


def _extract_period_labels(table_node) -> list[str]:
    labels: list[str] = []
    for header_cell in table_node.select("td.context-header, th.context-header"):
        tr_node = header_cell.select_one(".multi-language-content.content-tr")
        raw = tr_node.get_text("\n", strip=True) if tr_node else header_cell.get_text("\n", strip=True)
        label = clean_text(raw)
        if label and label not in labels:
            labels.append(label)
    return labels


def _normalize_period_label(value: str) -> str | None:
    match = _PERIOD_DATE_RE.search(value)
    if not match:
        return None
    return match.group(1).replace("/", ".")


def _presentation_metadata(soup: BeautifulSoup) -> tuple[str | None, int | None]:
    """Read statement currency and presentation scale from the report header."""
    text = clean_text(soup.get_text(" ", strip=True))
    scale: int | None = None
    currency: str | None = None

    # Current KAP renders this as a two-cell row such as
    # ``Sunum Para Birimi | 1.000.000 TL``.
    presentation_value: str | None = None
    for row in soup.find_all("tr"):
        cells = [
            clean_text(cell.get_text(" ", strip=True))
            for cell in row.find_all(["th", "td"], recursive=False)
        ]
        if len(cells) >= 2 and _normalize_metadata_label(cells[0]) in {
            "sunumparabirimi",
            "presentationcurrency",
        }:
            presentation_value = cells[-1]
            break

    if presentation_value:
        currency_token = re.search(r"\b(TRY|TL|USD|EUR|GBP)\b", presentation_value, flags=re.IGNORECASE)
        if currency_token:
            currency = currency_token.group(1).upper()
            if currency == "TL":
                currency = "TRY"
        number_token = re.search(r"\d[\d.,]*", presentation_value)
        if number_token:
            parsed_scale = normalize_numeric_value(number_token.group(0))
            if parsed_scale is not None and float(parsed_scale) > 0:
                scale = int(parsed_scale)
        elif currency:
            scale = 1

    scale_match = re.search(
        r"(?:Ölçek|Olcek|Scale|Sunum\s+Ölçeği|Presentation\s+Scale)\s*[:\-]?\s*([\w.,]+)",
        text,
        flags=re.IGNORECASE,
    )
    if scale is None and scale_match:
        raw_scale = scale_match.group(1).casefold()
        named_scales = {
            "bin": 1_000,
            "thousand": 1_000,
            "milyon": 1_000_000,
            "million": 1_000_000,
            "milyar": 1_000_000_000,
            "billion": 1_000_000_000,
        }
        if raw_scale in named_scales:
            scale = named_scales[raw_scale]
        else:
            parsed = normalize_numeric_value(scale_match.group(1))
            if parsed is not None:
                scale = int(parsed)
    currency_match = re.search(
        r"(?:Sunum\s+Para\s+Birimi|Para\s+Birimi|Presentation\s+Currency|Currency)\s*[:\-]?\s*"
        r"(Türk\s+Lirası|Turk\s+Lirasi|TRY|TL|USD|EUR|GBP)",
        text,
        flags=re.IGNORECASE,
    )
    if currency is None and currency_match:
        currency = currency_match.group(1).upper()
        if currency in {"TL", "TÜRK LİRASI", "TÜRK LIRASI", "TURK LIRASI"}:
            currency = "TRY"
    return currency, scale


def _normalize_metadata_label(value: str) -> str:
    return re.sub(r"[^a-z0-9çğıöşü]+", "", value.casefold())


def parse_financial_statement_html(
    html: str,
    disclosure_index: int,
    source_url: str | None = None,
    stock_code: str | None = None,
    company_title: str | None = None,
    publish_date: str | None = None,
) -> FinancialStatement:
    """Parse structured financial statement tables from KAP disclosure HTML."""
    soup = BeautifulSoup(html, "lxml")
    currency, scale = _presentation_metadata(soup)
    items: list[FinancialLineItem] = []
    statement_counts: Counter[str] = Counter()
    all_period_labels: list[str] = []

    for table in soup.select(_TABLE_ROLE_SELECTOR):
        role_code = _extract_statement_role_code(table) or "unknown"
        statement_name = STATEMENT_NAME_BY_ROLE.get(role_code, "other_statement")
        period_labels = _extract_period_labels(table)
        for lbl in period_labels:
            if lbl not in all_period_labels:
                all_period_labels.append(lbl)

        for row in table.select("tr"):
            taxonomy_node = row.select_one(".taxonomy-field-name")
            if taxonomy_node is None:
                continue

            taxonomy_code = _extract_taxonomy_code(taxonomy_node.get_text(" ", strip=True))
            if not taxonomy_code:
                continue

            metric_tr_node = row.select_one(".taxonomy-field-title .multi-language-content.content-tr")
            if metric_tr_node is None:
                metric_tr_node = row.select_one(".taxonomy-field-title")
            metric_name_tr = clean_text(metric_tr_node.get_text(" ", strip=True)) if metric_tr_node else None

            metric_en_node = row.select_one(".taxonomy-field-title .multi-language-content.content-en")
            metric_name_en = clean_text(metric_en_node.get_text(" ", strip=True)) if metric_en_node else None

            # Values
            value_cells = row.select("td.taxonomy-context-value")
            for p_idx, cell in enumerate(value_cells):
                classes = set(cell.get("class") or [])
                style = str(cell.get("style") or "").lower()
                if "display-none" in classes or "display:none" in style:
                    continue

                val_node = cell.select_one(".taxonomy-label-field") or cell
                val_text = clean_text(val_node.get_text(" ", strip=True))
                val_raw = clean_text(val_node.get("title")) or val_text
                if not val_text and not val_raw:
                    continue

                numeric_val = normalize_decimal_value(val_raw)
                normalized_val = numeric_val * Decimal(scale) if numeric_val is not None and scale else numeric_val
                period_lbl = period_labels[p_idx] if p_idx < len(period_labels) else f"Period {p_idx + 1}"

                item = FinancialLineItem(
                    disclosure_index=disclosure_index,
                    statement_role_code=role_code,
                    statement_name=statement_name,
                    taxonomy_code=taxonomy_code,
                    metric_name_tr=metric_name_tr,
                    metric_name_en=metric_name_en,
                    period_label=period_lbl,
                    period_index=p_idx,
                    value_text=val_text or val_raw,
                    value_numeric=numeric_val,
                    reported_value=numeric_val,
                    currency=currency,
                    scale=scale,
                    normalized_value=normalized_val,
                )
                items.append(item)
                statement_counts[statement_name] += 1

    return FinancialStatement(
        disclosure_index=disclosure_index,
        stock_code=stock_code,
        company_title=company_title,
        publish_date=publish_date,
        period_labels=all_period_labels,
        statement_counts=dict(statement_counts),
        items=items,
        source_url=source_url,
        currency=currency,
        scale=scale,
    )


class FinancialsScraper:
    """Extracts and parses financial statements via HTML disclosure tables and KAP XLS downloads."""

    def __init__(self, base_scraper: BaseScraper | None = None, config: KapConfig | None = None) -> None:
        self.config = config or KapConfig()
        self.base = base_scraper or BaseScraper(self.config)

    def get_financial_statement(
        self,
        disclosure_index: int | str,
        stock_code: str | None = None,
        company_title: str | None = None,
    ) -> FinancialStatement:
        """Fetch and parse financial statements directly from a KAP disclosure page."""
        route = ENDPOINT_DISCLOSURE_PAGE.format(lang=self.config.lang, disclosure_index=disclosure_index)
        resp = self.base.request_sync("GET", route)
        full_url = f"{self.config.base_url.rstrip('/')}{route}"
        return self.base.run_with_deadline_sync(
            lambda: parse_financial_statement_html(
                resp.text,
                disclosure_index=int(disclosure_index),
                source_url=full_url,
                stock_code=stock_code,
                company_title=company_title,
            ),
            deadline_at=self.base.operation_deadline(),
        )

    async def aget_financial_statement(
        self,
        disclosure_index: int | str,
        stock_code: str | None = None,
        company_title: str | None = None,
    ) -> FinancialStatement:
        """Async fetch and parse financial statements."""
        route = ENDPOINT_DISCLOSURE_PAGE.format(lang=self.config.lang, disclosure_index=disclosure_index)
        resp = await self.base.request_async("GET", route)
        full_url = f"{self.config.base_url.rstrip('/')}{route}"
        return await self.base.run_with_deadline_async(
            lambda: parse_financial_statement_html(
                resp.text,
                disclosure_index=int(disclosure_index),
                source_url=full_url,
                stock_code=stock_code,
                company_title=company_title,
            ),
            deadline_at=self.base.operation_deadline(),
        )

