from __future__ import annotations

from decimal import Decimal
from typing import Any
from pydantic import BaseModel, Field


class FinancialLineItem(BaseModel):
    """Represents a single parsed financial line item from a statement table."""

    disclosure_index: int = Field(description="Parent disclosure index")
    statement_role_code: str = Field(description="Role code e.g. '210015' (Balance Sheet), '310003' (Income)")
    statement_name: str = Field(description="Statement category name (e.g. balance_sheet, income_statement)")
    taxonomy_code: str = Field(description="Standard KAP / XBRL taxonomy tag code")
    metric_name_tr: str | None = Field(default=None, description="Line item name in Turkish")
    metric_name_en: str | None = Field(default=None, description="Line item name in English")
    period_label: str = Field(description="Period column header label (e.g. '31.12.2024')")
    period_index: int = Field(default=0, description="Column index representing reporting period")
    value_text: str | None = Field(default=None, description="Original formatted text representation")
    value_numeric: Decimal | None = Field(default=None, description="Backwards-compatible reported numeric value")
    reported_value: Decimal | None = Field(default=None, description="Value exactly as reported in the presentation unit")
    currency: str | None = Field(default=None, description="Presentation currency, such as TRY or USD")
    scale: int | None = Field(default=None, description="Presentation multiplier, such as 1 or 1000000")
    normalized_value: Decimal | None = Field(default=None, description="Reported value multiplied by presentation scale")


class FinancialStatement(BaseModel):
    """Represents complete financial statements parsed from an announcement."""

    disclosure_index: int = Field(description="KAP announcement index number")
    disclosure_id: str | None = Field(default=None, description="Disclosure UUID")
    stock_code: str | None = Field(default=None, description="Company stock code")
    company_title: str | None = Field(default=None, description="Company name")
    publish_date: str | None = Field(default=None, description="Publication timestamp")
    period_labels: list[str] = Field(default_factory=list, description="All period column labels")
    statement_counts: dict[str, int] = Field(default_factory=dict, description="Count of extracted items by statement")
    items: list[FinancialLineItem] = Field(default_factory=list, description="All individual financial items")
    source_url: str | None = Field(default=None, description="Announcement URL")
    currency: str | None = Field(default=None, description="Statement presentation currency")
    scale: int | None = Field(default=None, description="Statement presentation multiplier")

    def get_items_by_statement(self, statement_name: str) -> list[FinancialLineItem]:
        """Filter line items for a specific statement (e.g. 'balance_sheet', 'income_statement')."""
        return [item for item in self.items if item.statement_name == statement_name]

    def to_dict(self) -> dict[str, dict[str, Any]]:
        """Convert items to a compact dict while retaining duplicate-period values.

        A metric that occurs once keeps the historical scalar representation.
        When the same metric exists for multiple periods, its value becomes a
        ``{period_label: value}`` mapping instead of silently being overwritten.
        """
        out: dict[str, dict[str, Any]] = {}
        first_period: dict[tuple[str, str], str] = {}
        for item in self.items:
            stmt = item.statement_name
            if stmt not in out:
                out[stmt] = {}
            key = item.metric_name_tr or item.taxonomy_code
            if item.value_numeric is not None:
                value: Any = item.value_numeric
            elif item.value_text:
                value = item.value_text
            else:
                continue

            slot = (stmt, key)
            if key not in out[stmt]:
                out[stmt][key] = value
                first_period[slot] = item.period_label
            elif isinstance(out[stmt][key], dict):
                out[stmt][key][item.period_label] = value
            else:
                previous_period = first_period.get(slot, "Period 1")
                out[stmt][key] = {
                    previous_period: out[stmt][key],
                    item.period_label: value,
                }
        return out

    def to_period_dict(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Convert every statement metric to an explicit period-value mapping."""
        out: dict[str, dict[str, dict[str, Any]]] = {}
        for item in self.items:
            if item.value_numeric is not None:
                value: Any = item.value_numeric
            elif item.value_text:
                value = item.value_text
            else:
                continue
            statement = out.setdefault(item.statement_name, {})
            metric = item.metric_name_tr or item.taxonomy_code
            statement.setdefault(metric, {})[item.period_label] = value
        return out
