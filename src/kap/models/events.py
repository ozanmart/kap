from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Categorization of corporate events derived from KAP announcements."""

    BUYBACK = "BUYBACK"
    CAPITAL_INCREASE = "CAPITAL_INCREASE"
    DIVIDEND = "DIVIDEND"
    GUIDANCE = "GUIDANCE"
    BOARD_DECISION = "BOARD_DECISION"
    TRAFFIC_RESULTS = "TRAFFIC_RESULTS"
    FINANCIAL_REPORT = "FINANCIAL_REPORT"
    GENERAL_ASSEMBLY = "GENERAL_ASSEMBLY"
    VALUATION_REPORT = "VALUATION_REPORT"
    OTHER = "OTHER"


class EvidenceSpan(BaseModel):
    """A source-text span that supports an extracted event classification."""

    text: str = Field(description="Matched evidence text")
    start: int = Field(ge=0, description="Start offset in the combined title/body text")
    end: int = Field(ge=0, description="Exclusive end offset in the combined title/body text")
    source: str = Field(description="Evidence source: title, body, or metadata")


class DerivedEvent(BaseModel):
    """Represents a structured corporate event extracted from unstructured disclosure text."""

    event_id: str = Field(description="Unique derived event ID")
    disclosure_id: str = Field(description="Parent KAP disclosure UUID")
    disclosure_index: int = Field(description="Parent KAP announcement index")
    company_key: str = Field(description="Company ticker or identifier (e.g. 'THYAO')")
    event_type: EventType = Field(description="Classified event type")
    title: str | None = Field(default=None, description="Disclosure headline")
    publish_date: str | None = Field(default=None, description="Publish date timestamp")
    effective_dates: list[str] = Field(default_factory=list, description="Extracted dates mentioned in text (DD.MM.YYYY)")
    amounts: list[dict[str, Any]] = Field(default_factory=list, description="Extracted monetary values and currencies")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Heuristic classification confidence")
    evidence: list[str] = Field(default_factory=list, description="Trigger keywords/phrases matched in text")
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list, description="Exact supporting text spans")
    score: float | None = Field(default=None, description="Calculated impact score with time decay")


class ScoredCompany(BaseModel):
    """Aggregated event score for a company over recent disclosures."""

    company_key: str = Field(description="Company ticker symbol")
    score: float = Field(description="Total composite score")
    event_count: int = Field(description="Number of analyzed events")
    reasons: list[dict[str, Any]] = Field(default_factory=list, description="Per-event score breakdown")
