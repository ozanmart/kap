from __future__ import annotations

from .specs import (
    ExtractDisclosureEventsInput,
    ExtractDisclosureEventsOutput,
    FinancialStatementSummary,
    GetCompanyDisclosuresInput,
    GetCompanyDisclosuresOutput,
    GetCompanyInfoInput,
    GetCompanyInfoOutput,
    GetDisclosureDetailInput,
    GetDisclosureDetailOutput,
    GetExpectedCalendarInput,
    GetExpectedCalendarOutput,
    GetFinancialStatementsInput,
    GetMarketTaxonomyInput,
    GetMarketTaxonomyOutput,
    GetTodayDisclosuresInput,
    GetTodayDisclosuresOutput,
    SearchCompaniesInput,
    SearchCompaniesOutput,
)
from .toolkit import KapToolkit


def create_mcp_tool_definitions(toolkit: KapToolkit):
    """Build MCP schemas lazily so normal SDK imports do not load the server module."""
    from .mcp_server import create_mcp_tool_definitions as _create_mcp_tool_definitions

    return _create_mcp_tool_definitions(toolkit)


async def run_mcp_stdio_server() -> None:
    """Start the optional stdio MCP adapter, importing it only when invoked."""
    from .mcp_server import run_mcp_stdio_server as _run_mcp_stdio_server

    await _run_mcp_stdio_server()

__all__ = [
    "KapToolkit",
    "create_mcp_tool_definitions",
    "run_mcp_stdio_server",
    "SearchCompaniesInput",
    "SearchCompaniesOutput",
    "GetCompanyInfoInput",
    "GetCompanyInfoOutput",
    "GetTodayDisclosuresInput",
    "GetTodayDisclosuresOutput",
    "GetCompanyDisclosuresInput",
    "GetCompanyDisclosuresOutput",
    "GetDisclosureDetailInput",
    "GetDisclosureDetailOutput",
    "GetFinancialStatementsInput",
    "FinancialStatementSummary",
    "GetExpectedCalendarInput",
    "GetExpectedCalendarOutput",
    "ExtractDisclosureEventsInput",
    "ExtractDisclosureEventsOutput",
    "GetMarketTaxonomyInput",
    "GetMarketTaxonomyOutput",
]
