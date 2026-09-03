from __future__ import annotations

import pytest
from kap.tools.toolkit import KapToolkit
from kap.tools.mcp_server import create_mcp_tool_definitions
from kap.models.disclosure import DisclosureDetail
from kap.models.financials import FinancialStatement
from kap.models.disclosure import Disclosure


def test_toolkit_map_and_schemas():
    toolkit = KapToolkit()
    tool_map = toolkit.get_tool_map()
    assert "kap_search_companies" in tool_map
    assert "kap_get_company_info" in tool_map
    assert "kap_get_today_disclosures" in tool_map
    assert "kap_get_financial_statements" in tool_map
    assert "kap_get_expected_calendar" in tool_map
    assert "kap_extract_disclosure_events" in tool_map

    openai_tools = toolkit.get_openai_tools()
    assert len(openai_tools) == len(tool_map)
    assert all(t["type"] == "function" for t in openai_tools)

    anthropic_tools = toolkit.get_anthropic_tools()
    assert len(anthropic_tools) == len(tool_map)
    assert all("input_schema" in t for t in anthropic_tools)

    mcp_tools = create_mcp_tool_definitions(toolkit)
    assert len(mcp_tools) == len(tool_map)
    assert all("inputSchema" in t for t in mcp_tools)


def test_toolkit_execution_search():
    toolkit = KapToolkit()
    res = toolkit.execute_tool("kap_search_companies", {"query": "THYAO"})
    assert res["total_found"] >= 1
    assert any(c["ticker"] == "THYAO" for c in res["companies"])


def test_toolkit_execution_extracts_multiple_events(monkeypatch):
    toolkit = KapToolkit()
    detail = DisclosureDetail(
        disclosure_index=9876,
        disclosure_id="disc-9876",
        title="Temettü ve Yönetim Kurulu Kararı",
        content_text="",
        url="https://www.kap.org.tr/tr/Bildirim/9876",
        stock_code="BIMAS",
    )
    monkeypatch.setattr(toolkit.client.disclosures, "get_disclosure_detail", lambda index: detail)

    result = toolkit.extract_disclosure_events({
        "disclosure_index": 9876,
        "body_text": "Yönetim Kurulu temettü dağıtımına karar verdi.",
    })

    assert result.company_key == "BIMAS"
    assert len(result.events) == 2
    assert result.evidence_spans
    assert all(item.evidence_spans for item in result.events)


def test_toolkit_exposes_high_level_financials(monkeypatch):
    toolkit = KapToolkit()
    statement = FinancialStatement(disclosure_index=444, stock_code="THYAO")
    monkeypatch.setattr(toolkit.client, "get_financials", lambda **kwargs: statement)

    result = toolkit.get_financials({"ticker": "THYAO", "year": 2024, "period": "annual"})

    assert result.disclosure_index == 444
    assert result.stock_code == "THYAO"


def test_toolkit_detail_supports_metadata_and_body_truncation(monkeypatch):
    toolkit = KapToolkit()
    detail = DisclosureDetail(
        disclosure_index=9877,
        disclosure_id="disc-9877",
        title="Başlık",
        content_text="1234567890",
        url="https://www.kap.org.tr/tr/Bildirim/9877",
        stock_code="THYAO",
        company_title="TÜRK HAVA YOLLARI A.O.",
        publish_date="01.09.2026 10:00:00",
        disclosure_type="ÖDA",
        disclosure_class="ODA",
        attachment_metadata=[{"objId": "file-1"}],
    )
    monkeypatch.setattr(toolkit.client, "get_disclosure_detail", lambda index: detail)

    result = toolkit.get_disclosure_detail({"disclosure_index": 9877, "max_chars": 5})

    assert result.disclosure_id == "disc-9877"
    assert result.stock_code == "THYAO"
    assert result.content_text == "12345"
    assert result.truncated is True
    assert result.attachment_metadata == [{"objId": "file-1"}]
    assert result.disclosure_type == "ÖDA"
    assert result.disclosure_class == "ODA"
    assert result.warnings
