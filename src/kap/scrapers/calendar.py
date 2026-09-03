from __future__ import annotations

from datetime import datetime as dt_cls, timedelta
import logging
from typing import Any

from ..config import KapConfig
from ..constants import ENDPOINT_EXPECTED_DISCLOSURES, ISTANBUL_TZ
from ..exceptions import KapValidationError
from ..models.disclosure import ExpectedDisclosure
from .base import BaseScraper

logger = logging.getLogger("kap.scrapers.calendar")


class CalendarScraper:
    """Scrapes scheduled and expected financial reporting disclosure calendar from KAP."""

    def __init__(self, base_scraper: BaseScraper | None = None, config: KapConfig | None = None) -> None:
        self.config = config or KapConfig()
        self.base = base_scraper or BaseScraper(self.config)
        self._ticker_lookup = None
        self._company_title_lookup = None

    def set_ticker_lookup(self, lookup) -> None:
        """Attach a local member_oid -> ticker lookup without coupling scrapers."""
        self._ticker_lookup = lookup

    def set_company_title_lookup(self, lookup) -> None:
        """Attach a local exact company-title -> ticker lookup."""
        self._company_title_lookup = lookup

    def get_expected_disclosures(
        self,
        days_ahead: int = 180,
        member_oid: str | None = None,
    ) -> list[ExpectedDisclosure]:
        """Fetch upcoming earnings and reporting deadlines from KAP."""
        now = dt_cls.now(ISTANBUL_TZ)
        start_date = now.strftime("%Y-%m-%d")
        end_date = (now + timedelta(days=max(1, int(days_ahead)))).strftime("%Y-%m-%d")

        payload: dict[str, Any] = {
            "startDate": start_date,
            "endDate": end_date,
            "memberTypes": ["IGS"],
            "mkkMemberOidList": [member_oid] if member_oid else [],
            "disclosureClass": "",
            "subjects": [],
            "mainSector": "",
            "sector": "",
            "subSector": "",
            "market": "",
            "index": "",
            "year": "",
            "term": "",
            "ruleType": "",
        }

        route = ENDPOINT_EXPECTED_DISCLOSURES.format(lang=self.config.lang)
        resp = self.base.request_sync("POST", route, json=payload)
        def parse() -> list[ExpectedDisclosure]:
            data = resp.json()
            if isinstance(data, dict):
                for key in ("data", "items", "content", "result", "disclosures"):
                    if isinstance(data.get(key), list):
                        data = data[key]
                        break
            if not isinstance(data, list):
                raise KapValidationError(
                    f"Unexpected expected-disclosures response schema: {type(data).__name__}"
                )
            return self._parse_expected_rows(data)

        return self.base.run_with_deadline_sync(parse, deadline_at=self.base.operation_deadline())

    async def aget_expected_disclosures(
        self,
        days_ahead: int = 180,
        member_oid: str | None = None,
    ) -> list[ExpectedDisclosure]:
        """Async fetch upcoming earnings calendar."""
        now = dt_cls.now(ISTANBUL_TZ)
        start_date = now.strftime("%Y-%m-%d")
        end_date = (now + timedelta(days=max(1, int(days_ahead)))).strftime("%Y-%m-%d")

        payload: dict[str, Any] = {
            "startDate": start_date,
            "endDate": end_date,
            "memberTypes": ["IGS"],
            "mkkMemberOidList": [member_oid] if member_oid else [],
            "disclosureClass": "",
            "subjects": [],
            "mainSector": "",
            "sector": "",
            "subSector": "",
            "market": "",
            "index": "",
            "year": "",
            "term": "",
            "ruleType": "",
        }

        route = ENDPOINT_EXPECTED_DISCLOSURES.format(lang=self.config.lang)
        resp = await self.base.request_async("POST", route, json=payload)
        def parse() -> list[ExpectedDisclosure]:
            data = resp.json()
            if isinstance(data, dict):
                for key in ("data", "items", "content", "result", "disclosures"):
                    if isinstance(data.get(key), list):
                        data = data[key]
                        break
            if not isinstance(data, list):
                raise KapValidationError(
                    f"Unexpected expected-disclosures response schema: {type(data).__name__}"
                )
            return self._parse_expected_rows(data)

        return await self.base.run_with_deadline_async(parse, deadline_at=self.base.operation_deadline())

    def _parse_expected_rows(self, rows: list[dict[str, Any]]) -> list[ExpectedDisclosure]:
        expected: list[ExpectedDisclosure] = []
        seen: set[tuple[str, str, str, str, str, str]] = set()
        for r in rows:
            member = str(r.get("mkkMemberOid") or "").strip() or None
            stock_code = r.get("stockCode") or r.get("stock_code")
            if not stock_code and member and self._ticker_lookup:
                stock_code = self._ticker_lookup(member)
            title = r.get("kapMemberTitle") or r.get("companyTitle") or r.get("kapTitle")
            if not stock_code and title and self._company_title_lookup:
                stock_code = self._company_title_lookup(str(title))
            subject = r.get("subject") or r.get("subjectName") or r.get("disclosureSubject")
            period = r.get("ruleTypeTerm") or r.get("period") or r.get("term")
            year = r.get("year")
            start = r.get("startDate")
            end = r.get("endDate")

            # Rows without a member, ticker, subject, or date are UI/rule
            # placeholders (often rendered as ``[MEMBER] -``), not calendar
            # events.  Never expose them as if they were company deadlines.
            if not (member or stock_code or title) or not (subject or period or start or end):
                continue
            year_value: int | None = None
            try:
                if year is not None and str(year).strip():
                    year_value = int(float(str(year).strip()))
            except (TypeError, ValueError):
                year_value = None

            company_key = str(member or stock_code or title).upper()
            canonical = (
                company_key,
                str(subject or "").strip().casefold(),
                str(year_value or ""),
                str(period or "").strip().casefold(),
                str(start or "").strip(),
                str(end or "").strip(),
            )
            if canonical in seen:
                continue
            seen.add(canonical)

            expected.append(
                ExpectedDisclosure(
                    expected_id="exp-" + "-".join(part or "unknown" for part in canonical),
                    company_id=member or (str(stock_code).upper() if stock_code else None),
                    stock_code=str(stock_code).upper() if stock_code else None,
                    company_title=str(title) if title else None,
                    subject=str(subject) if subject else None,
                    period=str(period) if period else None,
                    year=year_value,
                    start_date=str(start) if start else None,
                    end_date=str(end) if end else None,
                )
            )
        def date_key(value: str | None) -> tuple[int, int, int]:
            if not value:
                return (9999, 12, 31)
            for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
                try:
                    parsed = dt_cls.strptime(value, fmt)
                    return (parsed.year, parsed.month, parsed.day)
                except ValueError:
                    continue
            return (9999, 12, 31)

        expected.sort(key=lambda item: (date_key(item.start_date), item.stock_code or item.company_title or item.company_id or ""))
        return expected
