from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class Company(BaseModel):
    """Represents a Borsa Istanbul (BIST) listed company."""

    ticker: str = Field(description="BIST stock ticker code (e.g. 'THYAO', 'BIMAS')")
    name: str = Field(description="Official company name / commercial title")
    city: str | None = Field(default=None, description="Headquarters city")
    auditor: str | None = Field(default=None, description="Independent auditing firm")
    company_id: str | None = Field(default=None, description="KAP MKK member OID")
    summary_page: str | None = Field(default=None, description="Link to KAP company summary page")

    @property
    def code(self) -> str:
        return self.ticker


class Shareholder(BaseModel):
    """Represents a major shareholder owning 5% or more capital/voting rights."""

    name_or_title: str = Field(description="Shareholder name or entity title")
    nominal_value: float | None = Field(default=None, description="Nominal value of shares held in TRY")
    share_ratio: float | None = Field(default=None, description="Percentage share in capital (%)")
    voting_ratio: float | None = Field(default=None, description="Percentage of voting rights (%)")


class FreeFloatInfo(BaseModel):
    """Represents public float details (Fiili Dolaşımdaki Paylar)."""

    stock_code: str | None = Field(default=None, description="Stock ticker code")
    nominal_value: float | None = Field(default=None, description="Nominal value of free-floating shares in TRY")
    float_ratio: float | None = Field(default=None, description="Free-float percentage ratio (%)")


class Subsidiary(BaseModel):
    """Represents a subsidiary, financial fixed asset, or investment (Bağlı Ortaklıklar)."""

    company_title: str = Field(description="Subsidiary / affiliated company title")
    activity_field: str | None = Field(default=None, description="Field of business / operation")
    paid_capital: float | None = Field(default=None, description="Paid-in capital of the affiliate")
    share_amount: float | None = Field(default=None, description="Share amount owned by parent")
    share_ratio: float | None = Field(default=None, description="Ownership stake percentage (%)")
    currency: str | None = Field(default="TRY", description="Currency unit")


class CompanyGeneralInfo(BaseModel):
    """Comprehensive company profile parsed from KAP Genel Bilgiler page."""

    member_oid: str = Field(description="KAP MKK Member OID")
    ticker: str | None = Field(default=None, description="Stock ticker code")
    company_title: str | None = Field(default=None, description="Official company title")
    website: str | None = Field(default=None, description="Primary corporate website")
    websites: list[str] = Field(default_factory=list, description="All recognized corporate website URLs")
    activity_field: str | None = Field(default=None, description="Company's field of operation")
    auditor: str | None = Field(default=None, description="Independent auditing firm")
    sector: str | None = Field(default=None, description="Primary sector classification")
    market: str | None = Field(default=None, description="Trading market (e.g. Yıldız Pazar, Ana Pazar)")
    indices: str | None = Field(default=None, description="Indices company belongs to (e.g. BIST 100, BIST 30)")
    other_exchanges: list[dict[str, Any]] = Field(default_factory=list, description="Other exchanges traded on")
    major_shareholders: list[Shareholder] = Field(default_factory=list, description="Shareholders owning >= 5%")
    free_float: list[FreeFloatInfo] = Field(default_factory=list, description="Free-float shares information")
    subsidiaries: list[Subsidiary] = Field(default_factory=list, description="Subsidiaries and financial assets")
    source_url: str | None = Field(default=None, description="Source KAP general info URL")
