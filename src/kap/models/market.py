from __future__ import annotations

from pydantic import BaseModel, Field


class Indice(BaseModel):
    """Represents a Borsa Istanbul stock index (e.g. BIST 100 / XU100, BIST 30 / XU030)."""

    code: str = Field(description="Index code (e.g. 'XU100', 'XU030', 'XUTUM')")
    name: str | None = Field(default=None, description="Descriptive index name")
    indices_no: str | None = Field(default=None, description="Index internal number")
    explanation: str | None = Field(default=None, description="Index summary description")
    companies: list[str] = Field(default_factory=list, description="Constituent company stock codes")


class SubSector(BaseModel):
    """Represents an industry sub-sector."""

    name: str = Field(description="Sub-sector name")
    companies: list[str] = Field(default_factory=list, description="Stock tickers in this sub-sector")


class Sector(BaseModel):
    """Represents an economic main sector or sector group."""

    name: str = Field(description="Sector name")
    sector_no: str | None = Field(default=None, description="Sector identification number")
    sector_oid: str | None = Field(default=None, description="KAP sector OID")
    main_sector_name: str | None = Field(default=None, description="Parent main sector name")
    sub_sectors: list[SubSector] = Field(
        default_factory=list,
        description=(
            "Subordinate sub-sectors. KAP's public taxonomy page exposes a single "
            "sector level whose parent is `main_sector_name`, so this stays empty "
            "unless a caller builds a deeper hierarchy itself."
        ),
    )
    companies: list[str] = Field(default_factory=list, description="Directly mapped stock tickers")


class Market(BaseModel):
    """Represents a trading market segment (e.g. Yıldız Pazar, Ana Pazar, Alt Pazar)."""

    market_no: str | None = Field(default=None, description="Market identifier number")
    market_name: str | None = Field(default=None, description="Market segment name")
    market_oid: str | None = Field(default=None, description="KAP market OID")
    financial_market_name: str | None = Field(default=None, description="Financial market group title")
    companies: list[str] = Field(default_factory=list, description="Stock tickers trading on this market")
