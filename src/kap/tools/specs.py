from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, Field


class ToolInput(BaseModel):
    """Common output-shaping flags shared by agent tools."""
    compact: bool = Field(default=True, description="Return the compact backwards-compatible representation")
    raw: bool = Field(default=False, description="Include normalized raw records in the response")


class PaginationInfo(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int | None = Field(default=None, ge=1)
    total: int | None = Field(default=None, ge=0)
    has_more: bool = False
    next_page: int | None = Field(default=None, ge=1)


class ToolOutput(BaseModel):
    """Common provenance and freshness metadata for agent responses."""
    fetched_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_url: str | None = None
    stale: bool = False
    warnings: list[str] = Field(default_factory=list)
    request_metrics: dict[str, Any] = Field(default_factory=dict, description="Optional phase timings for the live request")
    pagination: PaginationInfo = Field(default_factory=PaginationInfo)
    raw: Any | None = None

# ── 1. Search Companies ───────────────────────────────────────────────────────

class SearchCompaniesInput(ToolInput):
    """Input for searching Borsa Istanbul (BIST) companies."""
    query: str = Field(description="Search keyword: stock ticker symbol (e.g. 'THYAO', 'GARAN') or company name fragment (e.g. 'Hava Yolları', 'Tüpraş')")
    online: bool = Field(default=False, description="Whether to query KAP live search endpoint (True) or use fast bundled index (False)")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=500)


class CompanySummary(BaseModel):
    ticker: str
    name: str
    city: str | None = None
    auditor: str | None = None
    company_id: str | None = None


class SearchCompaniesOutput(ToolOutput):
    query: str
    total_found: int
    companies: list[CompanySummary]


# ── 2. Company Info ───────────────────────────────────────────────────────────

class GetCompanyInfoInput(ToolInput):
    """Input for retrieving comprehensive company profile, corporate governance, and ownership structure."""
    ticker: str = Field(description="BIST stock ticker code (e.g. 'BIMAS', 'THYAO', 'ASELS')")


class GetCompanyInfoOutput(ToolOutput):
    ticker: str
    company_title: str | None = None
    member_oid: str
    website: str | None = None
    activity_field: str | None = None
    auditor: str | None = None
    sector: str | None = None
    market: str | None = None
    indices: str | None = None
    major_shareholders_count: int
    major_shareholders: list[dict[str, Any]]
    free_float_ratio: float | None = None
    subsidiaries_count: int
    subsidiaries: list[dict[str, Any]]


# ── 3. Today's Disclosures ───────────────────────────────────────────────────

class GetTodayDisclosuresInput(ToolInput):
    """Input for fetching today's live stream of KAP announcements."""
    member_type: str = Field(
        default="bist_sirketleri",
        description="Filter by member type: 'bist_sirketleri' (BIST companies), 'yatirim_kuruluslari', 'portfoy_yonetim_sirketleri', or 'all'",
    )
    disclosure_types: list[str] = Field(
        default_factory=list,
        description="Optional list of disclosure types to filter (e.g. ['ODA'] for material events, ['FR'] for financials)",
    )
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class DisclosureItem(BaseModel):
    disclosure_index: int
    disclosure_id: str | None = None
    publish_date: str | None = None
    stock_code: str | None = None
    company_title: str | None = None
    title: str | None = None
    disclosure_type: str | None = None
    url: str | None = None


class GetTodayDisclosuresOutput(ToolOutput):
    count: int
    disclosures: list[DisclosureItem]


# ── 4. Company Disclosures ────────────────────────────────────────────────────

class GetCompanyDisclosuresInput(ToolInput):
    """Input for retrieving historical disclosures of a specific company."""
    ticker: str = Field(description="BIST stock ticker symbol (e.g. 'KCHOL', 'THYAO')")
    notification_type: str = Field(
        default="ALL",
        description="Type filter: 'ALL' (all announcements), 'FR' (financial reports), 'ODA' (material event disclosures), 'DUY' (regulatory)",
    )
    range_days: int = Field(
        default=365,
        ge=1,
        description=(
            "Lookback window: 1-365 days, or a four-digit calendar year such as 2024. "
            "KAP serves no other value."
        ),
    )
    limit: int = Field(default=30, ge=1, le=100, description="Max disclosures to return")
    page: int = Field(default=1, ge=1)
    page_size: int | None = Field(default=None, ge=1, le=100)


class GetCompanyDisclosuresOutput(ToolOutput):
    ticker: str
    notification_type: str
    count: int
    disclosures: list[DisclosureItem]


# ── 5. Disclosure Detail ──────────────────────────────────────────────────────

class GetDisclosureDetailInput(ToolInput):
    """Input for reading the full text content and attachments of a single KAP announcement."""
    disclosure_index: int = Field(description="Sequential KAP announcement index number (from search or listing)")
    max_chars: int | None = Field(default=None, ge=1, description="Optional maximum body length; use pagination.next_page with raw detail retrieval for full text")


class GetDisclosureDetailOutput(ToolOutput):
    disclosure_index: int
    disclosure_id: str | None = None
    title: str | None = None
    url: str
    content_text: str
    stock_code: str | None = None
    company_title: str | None = None
    publish_date: str | None = None
    disclosure_type: str | None = None
    disclosure_class: str | None = None
    attachment_urls: list[str] = Field(default_factory=list)
    attachment_metadata: list[dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False


# ── 6. Financial Statements ───────────────────────────────────────────────────

class GetFinancialStatementsInput(ToolInput):
    """Input for retrieving structured financial statements (Balance Sheet, Income Statement, Cash Flow)."""
    disclosure_index: int = Field(description="KAP announcement index number of a financial report disclosure")
    ticker: str | None = Field(default=None, description="Optional stock ticker symbol for context")
    statement_names: list[str] = Field(default_factory=list, description="Optional statement filters such as balance_sheet or income_statement")
    metrics: list[str] = Field(default_factory=list, description="Optional exact/substring metric-name filters")


class FinancialStatementSummary(ToolOutput):
    disclosure_index: int
    stock_code: str | None = None
    company_title: str | None = None
    period_labels: list[str]
    currency: str | None = None
    scale: int | None = None
    statement_counts: dict[str, int]
    statements: dict[str, dict[str, Any]]


class GetFinancialsInput(ToolInput):
    """Input for finding a company's financial report by ticker, year, and optional period."""
    ticker: str = Field(description="BIST ticker symbol (e.g. 'THYAO')")
    year: int = Field(ge=1990, le=2100, description="Financial reporting year")
    period: str | None = Field(default=None, description="Optional period such as 'Q1', 'Q2', 'Q3', 'Q4', or 'annual'")


# ── 7. Expected Calendar ──────────────────────────────────────────────────────

class GetExpectedCalendarInput(ToolInput):
    """Input for querying upcoming scheduled earnings announcements and financial reporting deadlines."""
    days_ahead: int = Field(default=90, ge=1, le=365, description="Number of days to look ahead (default: 90)")
    ticker: str | None = Field(default=None, description="Optional ticker filter (e.g. 'THYAO')")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class ExpectedCalendarItem(BaseModel):
    stock_code: str | None = None
    company_title: str | None = None
    subject: str | None = None
    period: str | None = None
    year: int | None = None
    start_date: str | None = None
    end_date: str | None = None


class GetExpectedCalendarOutput(ToolOutput):
    days_ahead: int
    total_found: int
    calendar: list[ExpectedCalendarItem]


# ── 8. Extract Corporate Events ───────────────────────────────────────────────

class ExtractDisclosureEventsInput(ToolInput):
    """Input for analyzing an announcement using rule-based NLP to detect corporate actions (buybacks, dividends, capital increases, guidance)."""
    disclosure_index: int = Field(description="KAP announcement index number")
    ticker: str | None = Field(default=None, description="Optional BIST ticker; used when body_text is supplied directly")
    body_text: str | None = Field(default=None, description="Optional text content to parse directly without re-fetching")
    max_chars: int | None = Field(default=None, ge=1, description="Optional maximum body length to analyze")


class ExtractedEventItem(BaseModel):
    event_type: str
    title: str | None = None
    effective_dates: list[str] = Field(default_factory=list)
    amounts: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float
    evidence: list[str] = Field(default_factory=list)
    evidence_spans: list[dict[str, Any]] = Field(default_factory=list)
    event_score: float | None = None


class ExtractDisclosureEventsOutput(ToolOutput):
    disclosure_index: int
    company_key: str
    event_type: str
    title: str | None = None
    effective_dates: list[str]
    amounts: list[dict[str, Any]]
    confidence: float
    evidence: list[str]
    evidence_spans: list[dict[str, Any]] = Field(default_factory=list)
    event_score: float | None = None
    events: list[ExtractedEventItem] = Field(default_factory=list)


# ── 9. Market Taxonomy ────────────────────────────────────────────────────────

class GetMarketTaxonomyInput(ToolInput):
    """Input for retrieving market indices (BIST 100, BIST 30), sectors, or trading markets."""
    category: str = Field(
        default="indices",
        description="Taxonomy category: 'indices' (BIST stock indices), 'sectors' (industry sectors), or 'markets' (trading markets)",
    )
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=500)


class GetMarketTaxonomyOutput(ToolOutput):
    category: str
    count: int
    items: list[dict[str, Any]]
