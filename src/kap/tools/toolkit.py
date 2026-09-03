from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from pydantic import BaseModel

from ..client import KapClient
from ..config import KapConfig
from ..models.events import EventType
from .specs import (
    CompanySummary,
    DisclosureItem,
    ExpectedCalendarItem,
    ExtractDisclosureEventsInput,
    ExtractDisclosureEventsOutput,
    ExtractedEventItem,
    FinancialStatementSummary,
    GetCompanyDisclosuresInput,
    GetCompanyDisclosuresOutput,
    GetCompanyInfoInput,
    GetCompanyInfoOutput,
    GetDisclosureDetailInput,
    GetDisclosureDetailOutput,
    GetExpectedCalendarInput,
    GetExpectedCalendarOutput,
    GetFinancialsInput,
    GetFinancialStatementsInput,
    GetMarketTaxonomyInput,
    GetMarketTaxonomyOutput,
    PaginationInfo,
    GetTodayDisclosuresInput,
    GetTodayDisclosuresOutput,
    SearchCompaniesInput,
    SearchCompaniesOutput,
)


def _paginate(items: list[Any], page: int, page_size: int) -> tuple[list[Any], PaginationInfo]:
    start = (page - 1) * page_size
    page_items = items[start:start + page_size]
    has_more = start + page_size < len(items)
    return page_items, PaginationInfo(
        page=page,
        page_size=page_size,
        total=len(items),
        has_more=has_more,
        next_page=page + 1 if has_more else None,
    )


def _metadata(client: KapClient, source_url: str | None = None, warnings: list[str] | None = None) -> dict[str, Any]:
    """Attach cache provenance without exposing cache implementation details."""
    cached = getattr(client.cache, "last_metadata", {}) or {}
    return {
        "fetched_at": cached.get("fetched_at") or datetime.now(timezone.utc).isoformat(),
        "source_url": source_url,
        "stale": bool(cached.get("stale", False)),
        "warnings": list(cached.get("warnings", [])) + list(warnings or []),
        "request_metrics": dict(getattr(client, "last_request_metrics", {}) or {}),
    }


class KapToolkit:
    """Unified Agent Toolkit exposing KAP capabilities for AI agents and LLM tool calling."""

    def __init__(
        self,
        client: KapClient | None = None,
        profile: Literal["fast", "balanced", "resilient"] = "balanced",
    ) -> None:
        """Create the toolkit with an explicit latency/reliability profile."""
        self.client = client or KapClient(KapConfig.for_profile(profile))

    def close(self) -> None:
        """Release HTTP, cache, and optional database resources."""
        self.client.close()

    # ── Tool 1: Search Companies ──────────────────────────────────────────────

    def search_companies(self, payload: SearchCompaniesInput | dict[str, Any]) -> SearchCompaniesOutput:
        """Search Borsa Istanbul (BIST) companies by ticker or name keyword."""
        inp = SearchCompaniesInput(**payload) if isinstance(payload, dict) else payload
        companies = self.client.search_companies(inp.query, online=inp.online)
        all_summaries = [
            CompanySummary(
                ticker=c.ticker,
                name=c.name,
                city=c.city,
                auditor=c.auditor,
                company_id=c.company_id,
            )
            for c in companies
        ]
        summaries, pagination = _paginate(all_summaries, inp.page, inp.page_size)
        return SearchCompaniesOutput(
            query=inp.query,
            total_found=len(all_summaries),
            companies=summaries,
            **_metadata(self.client, self.client.config.base_url),
            pagination=pagination,
            raw=[c.model_dump() for c in companies] if inp.raw else None,
        )

    # ── Tool 2: Company Info ──────────────────────────────────────────────────

    def get_company_info(self, payload: GetCompanyInfoInput | dict[str, Any]) -> GetCompanyInfoOutput:
        """Retrieve detailed company profile: ownership structure, free float, subsidiaries, auditor."""
        inp = GetCompanyInfoInput(**payload) if isinstance(payload, dict) else payload
        info = self.client.get_company_general_info(inp.ticker)

        float_ratio = None
        if info.free_float and info.free_float[0].float_ratio is not None:
            float_ratio = info.free_float[0].float_ratio

        return GetCompanyInfoOutput(
            ticker=inp.ticker.upper(),
            company_title=info.company_title,
            member_oid=info.member_oid,
            website=info.website,
            activity_field=info.activity_field,
            auditor=info.auditor,
            sector=info.sector,
            market=info.market,
            indices=info.indices,
            major_shareholders_count=len(info.major_shareholders),
            major_shareholders=[s.model_dump() for s in info.major_shareholders],
            free_float_ratio=float_ratio,
            subsidiaries_count=len(info.subsidiaries),
            subsidiaries=[sub.model_dump() for sub in info.subsidiaries],
            **_metadata(self.client, info.source_url),
            raw=info.model_dump() if inp.raw else None,
        )

    # ── Tool 3: Today's Disclosures ───────────────────────────────────────────

    def get_today_disclosures(self, payload: GetTodayDisclosuresInput | dict[str, Any]) -> GetTodayDisclosuresOutput:
        """Fetch today's active stream of KAP disclosures."""
        inp = GetTodayDisclosuresInput(**payload) if isinstance(payload, dict) else payload
        items = self.client.get_today_disclosures(
            member_type=inp.member_type,
            disclosure_types=inp.disclosure_types or None,
        )
        page_items, pagination = _paginate(items, inp.page, inp.page_size)
        return GetTodayDisclosuresOutput(
            count=len(page_items),
            disclosures=[
                DisclosureItem(
                    disclosure_index=d.disclosure_index,
                    disclosure_id=d.disclosure_id,
                    publish_date=d.publish_date,
                    stock_code=d.stock_code,
                    company_title=d.company_title,
                    title=d.title,
                    disclosure_type=d.disclosure_type,
                    url=d.url,
                )
                for d in page_items
            ],
            **_metadata(self.client, self.client.config.base_url),
            pagination=pagination,
            raw=[d.model_dump() for d in page_items] if inp.raw else None,
        )

    # ── Tool 4: Company Disclosures ───────────────────────────────────────────

    def get_company_disclosures(self, payload: GetCompanyDisclosuresInput | dict[str, Any]) -> GetCompanyDisclosuresOutput:
        """Get historical announcements for a specific company."""
        inp = GetCompanyDisclosuresInput(**payload) if isinstance(payload, dict) else payload
        page_size = inp.page_size or inp.limit
        fetch_limit = inp.page * page_size
        items = self.client.get_company_disclosures(
            ticker_or_oid=inp.ticker,
            notification_type=inp.notification_type,
            range_days=inp.range_days,
            limit=fetch_limit,
        )
        page_items, pagination = _paginate(items, inp.page, page_size)
        return GetCompanyDisclosuresOutput(
            ticker=inp.ticker.upper(),
            notification_type=inp.notification_type,
            count=len(page_items),
            disclosures=[
                DisclosureItem(
                    disclosure_index=d.disclosure_index,
                    disclosure_id=d.disclosure_id,
                    publish_date=d.publish_date,
                    stock_code=d.stock_code,
                    company_title=d.company_title,
                    title=d.title,
                    disclosure_type=d.disclosure_type,
                    url=d.url,
                )
                for d in page_items
            ],
            **_metadata(self.client, self.client.config.base_url),
            pagination=pagination,
            raw=[d.model_dump() for d in page_items] if inp.raw else None,
        )

    # ── Tool 5: Disclosure Detail ─────────────────────────────────────────────

    def get_disclosure_detail(self, payload: GetDisclosureDetailInput | dict[str, Any]) -> GetDisclosureDetailOutput:
        """Read the full text content and attachments of a specific KAP announcement."""
        inp = GetDisclosureDetailInput(**payload) if isinstance(payload, dict) else payload
        detail = self.client.get_disclosure_detail(inp.disclosure_index)
        body = detail.content_text
        truncated = inp.max_chars is not None and len(body) > inp.max_chars
        warnings = ["content_text truncated by max_chars"] if truncated else []
        if inp.max_chars is not None:
            body = body[: inp.max_chars]
        return GetDisclosureDetailOutput(
            disclosure_index=detail.disclosure_index,
            disclosure_id=detail.disclosure_id,
            title=detail.title,
            url=detail.url,
            content_text=body,
            stock_code=detail.stock_code,
            company_title=detail.company_title,
            publish_date=detail.publish_date,
            disclosure_type=detail.disclosure_type,
            disclosure_class=detail.disclosure_class,
            attachment_urls=detail.attachment_urls,
            attachment_metadata=detail.attachment_metadata,
            truncated=truncated,
            **_metadata(self.client, detail.url, warnings),
            pagination=PaginationInfo(
                page=1,
                page_size=inp.max_chars,
                total=len(detail.content_text) if inp.max_chars is not None else None,
                has_more=truncated,
                next_page=2 if truncated else None,
            ),
            raw=detail.model_dump() if inp.raw else None,
        )

    # ── Tool 6: Financial Statements ──────────────────────────────────────────

    def get_financial_statements(self, payload: GetFinancialStatementsInput | dict[str, Any]) -> FinancialStatementSummary:
        """Retrieve structured financial statements (Balance Sheet, Income Statement, Cash Flows)."""
        inp = GetFinancialStatementsInput(**payload) if isinstance(payload, dict) else payload
        stmt = self.client.get_financial_statement(inp.disclosure_index, ticker=inp.ticker)
        selected_items = stmt.items
        if inp.statement_names:
            allowed = {name.casefold() for name in inp.statement_names}
            selected_items = [item for item in selected_items if item.statement_name.casefold() in allowed]
        if inp.metrics:
            wanted = [metric.casefold() for metric in inp.metrics]
            selected_items = [
                item for item in selected_items
                if any(term in (item.metric_name_tr or "").casefold() or term in (item.metric_name_en or "").casefold() for term in wanted)
            ]
        filtered_stmt = stmt.model_copy(update={"items": selected_items}) if selected_items is not stmt.items else stmt
        filtered_counts: dict[str, int] = {}
        for item in selected_items:
            filtered_counts[item.statement_name] = filtered_counts.get(item.statement_name, 0) + 1
        return FinancialStatementSummary(
            disclosure_index=stmt.disclosure_index,
            stock_code=stmt.stock_code,
            company_title=stmt.company_title,
            period_labels=stmt.period_labels,
            statement_counts=filtered_counts if selected_items is not stmt.items else stmt.statement_counts,
            currency=stmt.currency,
            scale=stmt.scale,
            statements=filtered_stmt.to_dict() if inp.compact else filtered_stmt.to_period_dict(),
            **_metadata(self.client, stmt.source_url),
            raw=stmt.model_dump() if inp.raw else None,
        )

    def get_financials(self, payload: GetFinancialsInput | dict[str, Any]) -> FinancialStatementSummary:
        """Find and parse the financial report matching ticker, year, and optional period."""
        inp = GetFinancialsInput(**payload) if isinstance(payload, dict) else payload
        stmt = self.client.get_financials(
            ticker=inp.ticker,
            year=inp.year,
            period=inp.period,
        )
        return FinancialStatementSummary(
            disclosure_index=stmt.disclosure_index,
            stock_code=stmt.stock_code or inp.ticker.upper(),
            company_title=stmt.company_title,
            period_labels=stmt.period_labels,
            statement_counts=stmt.statement_counts,
            currency=stmt.currency,
            scale=stmt.scale,
            statements=stmt.to_dict() if inp.compact else stmt.to_period_dict(),
            **_metadata(self.client, stmt.source_url),
            raw=stmt.model_dump() if inp.raw else None,
        )

    # ── Tool 7: Expected Calendar ─────────────────────────────────────────────

    def get_expected_calendar(self, payload: GetExpectedCalendarInput | dict[str, Any]) -> GetExpectedCalendarOutput:
        """Query upcoming scheduled earnings announcements and filing deadlines."""
        inp = GetExpectedCalendarInput(**payload) if isinstance(payload, dict) else payload
        rows = self.client.get_expected_disclosures(days_ahead=inp.days_ahead, ticker_or_oid=inp.ticker)
        page_rows, pagination = _paginate(rows, inp.page, inp.page_size)
        return GetExpectedCalendarOutput(
            days_ahead=inp.days_ahead,
            total_found=len(rows),
            calendar=[
                ExpectedCalendarItem(
                    stock_code=r.stock_code,
                    company_title=r.company_title,
                    subject=r.subject,
                    period=r.period,
                    year=r.year,
                    start_date=r.start_date,
                    end_date=r.end_date,
                )
                for r in page_rows
            ],
            **_metadata(self.client, self.client.config.base_url),
            pagination=pagination,
            raw=[r.model_dump() for r in page_rows] if inp.raw else None,
        )

    # ── Tool 8: Extract Events ────────────────────────────────────────────────

    def extract_disclosure_events(self, payload: ExtractDisclosureEventsInput | dict[str, Any]) -> ExtractDisclosureEventsOutput:
        """Analyze a disclosure with NLP rules to classify Buybacks, Dividends, Capital Increases, etc."""
        inp = ExtractDisclosureEventsInput(**payload) if isinstance(payload, dict) else payload
        events = self.client.extract_events_many(
            disclosure_index=inp.disclosure_index,
            body_text=inp.body_text[: inp.max_chars] if inp.body_text is not None and inp.max_chars else inp.body_text,
            stock_code=inp.ticker,
        )
        event = events[0]
        return ExtractDisclosureEventsOutput(
            disclosure_index=event.disclosure_index,
            company_key=event.company_key,
            event_type=event.event_type.value,
            title=event.title,
            effective_dates=event.effective_dates,
            amounts=event.amounts,
            confidence=event.confidence,
            evidence=event.evidence,
            evidence_spans=[span.model_dump() for span in event.evidence_spans],
            event_score=event.score,
            events=[
                ExtractedEventItem(
                    event_type=item.event_type.value,
                    title=item.title,
                    effective_dates=item.effective_dates,
                    amounts=item.amounts,
                    confidence=item.confidence,
                    evidence=item.evidence,
                    evidence_spans=[span.model_dump() for span in item.evidence_spans],
                    event_score=item.score,
                )
                for item in events
            ],
            **_metadata(
                self.client,
                f"{self.client.config.base_url.rstrip('/')}/{self.client.config.lang}/Bildirim/{event.disclosure_index}",
                ["body_text truncated by max_chars"] if inp.body_text is not None and inp.max_chars and len(inp.body_text) > inp.max_chars else None,
            ),
            raw=[item.model_dump() for item in events] if inp.raw else None,
        )

    # ── Tool 9: Market Taxonomy ───────────────────────────────────────────────

    def get_market_taxonomy(self, payload: GetMarketTaxonomyInput | dict[str, Any]) -> GetMarketTaxonomyOutput:
        """Retrieve indices (e.g. BIST 100, BIST 30), sectors, or trading markets."""
        inp = GetMarketTaxonomyInput(**payload) if isinstance(payload, dict) else payload
        cat = inp.category.lower().strip()
        if cat in {"indices", "index", "endeksler"}:
            items = [i.model_dump() for i in self.client.get_indices()]
        elif cat in {"sectors", "sector", "sektorler"}:
            items = [s.model_dump() for s in self.client.get_sectors()]
        elif cat in {"markets", "market", "pazarlar"}:
            items = [m.model_dump() for m in self.client.get_markets()]
        else:
            raise ValueError(f"Unknown taxonomy category: {cat}")

        page_items, pagination = _paginate(items, inp.page, inp.page_size)
        return GetMarketTaxonomyOutput(
            category=cat,
            count=len(page_items),
            items=page_items,
            **_metadata(self.client, self.client.config.base_url),
            pagination=pagination,
            raw=items if inp.raw else None,
        )

    # ── Dynamic Tool Dispatch & Schemas ───────────────────────────────────────

    def get_tool_map(self) -> dict[str, tuple[type[BaseModel], Callable[[Any], BaseModel]]]:
        return {
            "kap_search_companies": (SearchCompaniesInput, self.search_companies),
            "kap_get_company_info": (GetCompanyInfoInput, self.get_company_info),
            "kap_get_today_disclosures": (GetTodayDisclosuresInput, self.get_today_disclosures),
            "kap_get_company_disclosures": (GetCompanyDisclosuresInput, self.get_company_disclosures),
            "kap_get_disclosure_detail": (GetDisclosureDetailInput, self.get_disclosure_detail),
            "kap_get_financial_statements": (GetFinancialStatementsInput, self.get_financial_statements),
            "kap_get_financials": (GetFinancialsInput, self.get_financials),
            "kap_get_expected_calendar": (GetExpectedCalendarInput, self.get_expected_calendar),
            "kap_extract_disclosure_events": (ExtractDisclosureEventsInput, self.extract_disclosure_events),
            "kap_get_market_taxonomy": (GetMarketTaxonomyInput, self.get_market_taxonomy),
        }

    def execute_tool(self, tool_name: str, arguments: dict[str, Any] | str) -> dict[str, Any]:
        """Execute a tool dynamically by name with JSON or dict arguments."""
        tool_map = self.get_tool_map()
        if tool_name not in tool_map:
            raise ValueError(f"Tool '{tool_name}' not found. Available tools: {list(tool_map.keys())}")

        input_cls, handler = tool_map[tool_name]
        args_dict = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
        parsed_input = input_cls(**args_dict)
        result = handler(parsed_input)
        # Return JSON-compatible values (notably Decimal financial values) for
        # MCP and function-calling transports.
        return json.loads(result.model_dump_json())

    def get_openai_tools(self) -> list[dict[str, Any]]:
        """Return OpenAI / function calling tool definitions."""
        tools = []
        for name, (input_cls, handler) in self.get_tool_map().items():
            schema = input_cls.model_json_schema()
            tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": handler.__doc__ or input_cls.__doc__ or name,
                    "parameters": schema,
                },
            })
        return tools

    def get_anthropic_tools(self) -> list[dict[str, Any]]:
        """Return Anthropic / Claude tool definitions."""
        tools = []
        for name, (input_cls, handler) in self.get_tool_map().items():
            schema = input_cls.model_json_schema()
            tools.append({
                "name": name,
                "description": handler.__doc__ or input_cls.__doc__ or name,
                "input_schema": schema,
            })
        return tools
