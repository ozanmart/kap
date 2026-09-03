from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class Disclosure(BaseModel):
    """Represents a public disclosure / announcement from KAP."""

    disclosure_id: str | None = Field(default=None, description="Unique disclosure UUID")
    disclosure_index: int = Field(description="Sequential KAP announcement index number")
    publish_date: str | None = Field(default=None, description="Publication timestamp string (DD.MM.YYYY HH:MM:SS)")
    company_title: str | None = Field(default=None, description="Publishing company title")
    stock_code: str | None = Field(default=None, description="Primary BIST stock ticker")
    related_stocks: str | None = Field(default=None, description="Related stock tickers (comma separated)")
    title: str | None = Field(default=None, description="Disclosure headline / subject title")
    disclosure_type: str | None = Field(default=None, description="Disclosure type code (e.g. ODA, FR, DUY)")
    disclosure_class: str | None = Field(default=None, description="Disclosure class code (e.g. FR, ODA, DG)")
    disclosure_category: str | None = Field(default=None, description="Disclosure category name")
    url: str | None = Field(default=None, description="Permanent KAP URL for this disclosure")
    raw: dict[str, Any] = Field(default_factory=dict, description="Raw KAP API JSON payload")


class ExpectedDisclosure(BaseModel):
    """Represents a scheduled / expected financial disclosure event (Earnings calendar)."""

    expected_id: str = Field(description="Generated unique identifier for expected disclosure")
    company_id: str | None = Field(default=None, description="MKK Member OID or ticker")
    stock_code: str | None = Field(default=None, description="Stock ticker code")
    company_title: str | None = Field(default=None, description="Company name")
    subject: str | None = Field(default=None, description="Disclosure subject (e.g. Finansal Rapor)")
    period: str | None = Field(default=None, description="Reporting period (e.g. 2024 4. Çeyrek / Yıllık)")
    year: int | None = Field(default=None, description="Financial year")
    start_date: str | None = Field(default=None, description="First date of expected publication window")
    end_date: str | None = Field(default=None, description="Deadline date of expected publication window")


class DisclosureSubject(BaseModel):
    """Represents a KAP disclosure subject definition."""

    disclosure_class: str = Field(description="Disclosure class (e.g. 'FR', 'ODA', 'DG')")
    subject: str = Field(description="Human-readable subject name (e.g. 'Finansal Rapor')")
    subject_oid: str = Field(description="KAP subject UUID")


class DisclosureDetail(BaseModel):
    """Represents the complete parsed content and attachments of a disclosure."""

    disclosure_index: int = Field(description="Disclosure index number")
    disclosure_id: str | None = Field(default=None, description="Disclosure UUID")
    title: str | None = Field(default=None, description="Disclosure headline")
    content_text: str = Field(description="Clean plain-text body extracted from HTML")
    url: str = Field(description="Public web URL on KAP")
    stock_code: str | None = Field(default=None, description="Stock ticker code")
    company_title: str | None = Field(default=None, description="Company title")
    publish_date: str | None = Field(default=None, description="Publish date")
    disclosure_type: str | None = Field(default=None, description="Disclosure type code shown by KAP")
    disclosure_class: str | None = Field(default=None, description="Normalized disclosure class code")
    attachment_urls: list[str] = Field(default_factory=list, description="URLs to attached PDF or XLSX files")
    attachment_metadata: list[dict[str, Any]] = Field(default_factory=list, description="Structured attachment metadata from KAP")
    raw: dict[str, Any] = Field(default_factory=dict, description="Normalized metadata recovered from KAP")
