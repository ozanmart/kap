from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from kap.async_client import AsyncKapClient
from kap.client import KapClient
from kap.config import KapConfig
from kap.storage.sqlite import KapDatabase
from kap.models.company import Company
from kap.models.disclosure import Disclosure
from kap.models.disclosure import DisclosureDetail
from kap.models.financials import FinancialLineItem, FinancialStatement
from kap.scrapers.company_general import parse_company_general_html
from kap.scrapers.base import KapConnectionError, KapDeadlineExceeded


def test_sync_client_propagates_failed_http_metrics_from_cached_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("TLS handshake timed out", request=request)

    config = KapConfig(
        base_url="https://example.test",
        enable_cache=False,
        max_retries=1,
        request_deadline_s=5.0,
    )
    with KapClient(config) as client:
        client.base_scraper._sync_client = httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url=config.base_url,
        )
        with pytest.raises(KapConnectionError):
            client.get_today_disclosures()

        assert client.last_request_metrics["stage"] == "error"
        assert client.last_request_metrics["attempts"] == 1
        assert "ReadTimeout" in client.last_request_metrics["error"]
        assert client.last_request_metrics["operation"] == "today_disclosures"
        assert client.last_request_metrics["operation_id"]
        for field in ("request_s", "fetch_s", "parse_s", "total_s"):
            assert isinstance(client.last_request_metrics[field], float)
            assert client.last_request_metrics[field] >= 0


def test_async_client_propagates_failed_http_metrics_from_cached_call() -> None:
    async def run() -> dict[str, object]:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("TLS handshake timed out", request=request)

        config = KapConfig(
            base_url="https://example.test",
            enable_cache=False,
            max_retries=1,
            request_deadline_s=5.0,
        )
        async with AsyncKapClient(config) as client:
            client.base_scraper._async_client = httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url=config.base_url,
            )
            with pytest.raises(KapConnectionError):
                await client.get_today_disclosures()
            return dict(client.last_request_metrics)

    metrics = asyncio.run(run())
    assert metrics["stage"] == "error"
    assert metrics["attempts"] == 1
    assert "ReadTimeout" in metrics["error"]
    assert metrics["operation"] == "today_disclosures"
    assert metrics["operation_id"]
    for field in ("request_s", "fetch_s", "parse_s", "total_s"):
        assert isinstance(metrics[field], float)
        assert metrics[field] >= 0


def test_client_deadline_covers_cached_operation_end_to_end() -> None:
    with KapClient(KapConfig(enable_cache=False, request_deadline_s=0.01)) as client:
        client._begin_operation("composite")
        with pytest.raises(KapDeadlineExceeded, match="Client operation"):
            client._cached_call("slow", lambda: time.sleep(0.02))


def test_sync_client_deadline_metric_is_not_overwritten_by_cached_call() -> None:
    with KapClient(KapConfig(enable_cache=False, request_deadline_s=0.01)) as client:
        client._begin_operation("nested_deadline")
        operation_id = client.last_request_metrics["operation_id"]

        def expire_inside_fetch() -> None:
            time.sleep(0.02)
            client._ensure_operation_budget()

        with pytest.raises(KapDeadlineExceeded, match="Client operation"):
            client._cached_call("nested-deadline", expire_inside_fetch)

        assert client.last_request_metrics["operation_id"] == operation_id
        assert client.last_request_metrics["operation"] == "nested_deadline"
        assert client.last_request_metrics["stage"] == "deadline"
        assert client.last_request_metrics["attempts"] == 0
        assert client.last_request_metrics["error"] == "client operation deadline exceeded"


def test_async_client_deadline_metric_is_not_overwritten_by_cached_call() -> None:
    async def run() -> dict[str, object]:
        async with AsyncKapClient(KapConfig(enable_cache=False, request_deadline_s=0.01)) as client:
            client._begin_operation("nested_async_deadline")

            async def expire_inside_fetch() -> None:
                await asyncio.sleep(0.02)
                client._ensure_operation_budget()

            with pytest.raises(KapDeadlineExceeded, match="Client operation"):
                await client._cached_async(
                    "nested-async-deadline",
                    expire_inside_fetch,
                    expire=None,
                )
            return dict(client.last_request_metrics)

    metrics = asyncio.run(run())
    assert metrics["operation"] == "nested_async_deadline"
    assert metrics["stage"] == "deadline"
    assert metrics["attempts"] == 0
    assert metrics["error"] == "client operation deadline exceeded"


def test_client_bundled_companies():
    with KapClient() as client:
        companies = client.get_companies(online=False)
        assert len(companies) > 500

        thyao = client.get_company("THYAO")
        assert thyao is not None
        assert "TÜRK HAVA YOLLARI" in thyao.name.upper()

        bimas = client.get_company("BIMAS")
        assert bimas is not None
        assert "BİM" in bimas.name.upper()


def test_client_search():
    with KapClient() as client:
        results = client.search_companies("THYAO")
        assert len(results) >= 1
        assert any(c.ticker == "THYAO" for c in results)


def test_sqlite_storage():
    db = KapDatabase(":memory:")
    comp = Company(
        ticker="KCHOL",
        name="KOÇ HOLDİNG A.Ş.",
        city="İSTANBUL",
        auditor="PwC",
        company_id="4028e4a240e8d16e0140e90c62950001",
    )
    db.save_companies([comp])

    disc = Disclosure(
        disclosure_id="disc-1",
        disclosure_index=999999,
        publish_date="01.09.2024 12:00:00",
        stock_code="KCHOL",
        company_title="KOÇ HOLDİNG A.Ş.",
        title="Özel Durum Açıklaması",
        disclosure_type="ODA",
    )
    db.save_disclosures([disc])

    rows = db.query_disclosures(stock_code="KCHOL")
    assert len(rows) == 1
    assert rows[0]["disclosure_index"] == 999999

    db.close()


def test_company_general_live_fixture_uses_current_headers():
    from pathlib import Path

    html = (Path(__file__).parent / "fixtures" / "company_general.html").read_text(encoding="utf-8")
    info = parse_company_general_html(
        html,
        member_oid="4028e4a2420327a4014209c55161144d",
        url="https://www.kap.org.tr/tr/sirket-bilgileri/genel/4028e4a2420327a4014209c55161144d",
    )

    assert info.company_title == "ACISELSAN ACIPAYAM SELÜLOZ SANAYİ VE TİCARET A.Ş."
    assert info.website == "www.aciselsan.com.tr"
    assert info.auditor.startswith("DRT BAĞIMSIZ DENETİM")
    assert info.market == "ANA PAZAR"
    assert info.major_shareholders[0].nominal_value == 5439432.65
    assert info.major_shareholders[0].share_ratio == 50.73
    assert info.major_shareholders[0].voting_ratio == 50.73
    assert info.free_float[0].nominal_value == 5182365.67
    assert info.free_float[0].float_ratio == 48.34
    assert info.subsidiaries[0].paid_capital == 300000000
    assert info.subsidiaries[0].share_amount == 1260


def test_company_general_parses_current_rsc_profile_tables(monkeypatch):
    import kap.scrapers.company_general as module

    records = [
        {
            "item_key": "kpy41_acc5_sermayede_dogrudan",
            "item_name": "Sermayede Doğrudan %5 veya Daha Fazla Paya Sahip Kişiler",
            "value": [
                {"shareholder": "ORTAK A", "shareInCapital": "184.900.000", "ratioInCapital": "15,41", "votingRightRatio": "15,41"},
                {"shareholder": "DİĞER", "shareInCapital": "1", "ratioInCapital": "1", "votingRightRatio": "1"},
                {"shareholder": "TOPLAM", "shareInCapital": "2", "ratioInCapital": "100", "votingRightRatio": "100"},
            ],
        },
        {
            "item_key": "kpy41_acc5_fiili_dolasimdaki_pay",
            "item_name": "Fiili Dolaşımdaki Paylar",
            "value": [{"isin": "BIMAS", "actualSharesOutstanding": "825.360.294,58", "actualOutstandingSharesRatio": "68,78"}],
        },
        {
            "item_key": "kpy41_acc7_bagli_ortakliklar",
            "item_name": "Bağlı Ortaklıklar",
            "value": [{"companyTitle": "FİLE Market", "scopeOfActivitiesOfCompany": "Perakende", "paidInOrIssuedCapital": "13500000000", "capitalShareOfCompany": "13365000000", "monetaryUnit": {"key": "TRY"}, "ratioOfCapitalShareOfCompany": "99"}],
        },
    ]
    monkeypatch.setattr(module, "iter_rsc_items", lambda html: iter(records))
    info = parse_company_general_html(
        '<div class="company__sgfb-wrapper" companyname="BİM BİRLEŞİK MAĞAZALAR A.Ş."></div>',
        "oid",
        "https://www.kap.org.tr/tr/sirket-bilgileri/genel/oid",
    )

    assert info.ticker == "BIMAS"
    assert [row.name_or_title for row in info.major_shareholders] == ["ORTAK A"]
    assert info.major_shareholders[0].nominal_value == 184_900_000
    assert info.free_float[0].float_ratio == 68.78
    assert info.subsidiaries[0].currency == "TRY"
    assert info.subsidiaries[0].share_ratio == 99


def test_client_event_extraction_recovers_ticker_for_inline_body(monkeypatch):
    detail = DisclosureDetail(
        disclosure_index=1234,
        disclosure_id="disc-1234",
        title="Temettü ve Yönetim Kurulu Kararı",
        content_text="",
        url="https://www.kap.org.tr/tr/Bildirim/1234",
        stock_code="THYAO",
    )
    with KapClient() as client:
        monkeypatch.setattr(client.disclosures, "get_disclosure_detail", lambda index: detail)
        events = client.extract_events_many(
            disclosure_index=1234,
            body_text="Yönetim Kurulu temettü dağıtımına karar verdi.",
        )

    assert len(events) == 2
    assert {event.event_type.value for event in events} == {"DIVIDEND", "BOARD_DECISION"}
    assert all(event.company_key == "THYAO" for event in events)


def test_client_get_financials_selects_report_by_year_and_period(monkeypatch):
    selectors: list[int] = []
    candidates = [
        Disclosure(
            disclosure_id="annual",
            disclosure_index=900,
            title="2024 Yıllık Finansal Rapor",
            disclosure_type="FR",
        ),
        Disclosure(
            disclosure_id="q1",
            disclosure_index=901,
            title="2024 1. Çeyrek Finansal Rapor",
            disclosure_type="FR",
        ),
    ]
    statement = FinancialStatement(
        disclosure_index=901,
        stock_code="THYAO",
        period_labels=["31.03.2024"],
        items=[
            FinancialLineItem(
                disclosure_index=901,
                statement_role_code="210015",
                statement_name="balance_sheet",
                taxonomy_code="cash",
                period_label="31.03.2024",
                value_text="1",
            )
        ],
    )
    with KapClient() as client:
        monkeypatch.setattr(client, "_resolve_member_oid", lambda ticker: "oid")
        monkeypatch.setattr(
            client.disclosures,
            "get_company_disclosures",
            lambda **kwargs: selectors.append(kwargs["range_value"]) or candidates,
        )
        monkeypatch.setattr(
            client.financials,
            "get_financial_statement",
            lambda *args, **kwargs: statement,
        )
        result = client.get_financials("THYAO", 2024, "Q1")

    assert result.disclosure_index == 901
    assert result.stock_code == "THYAO"
    assert selectors == [2024]


def test_client_get_financials_rejects_responsibility_statement_from_publish_year(monkeypatch):
    selectors: list[int] = []
    candidates = [
        Disclosure(
            disclosure_index=1396942,
            publish_date="28.02.2025 08:00:39",
            title="Sorumluluk Beyanı (Konsolide)",
            disclosure_type="FR",
            raw={"disclosureBasic": {"year": 2024, "ruleType": "Yıllık"}},
        ),
        Disclosure(
            disclosure_index=1600000,
            publish_date="01.03.2026 08:00:00",
            title="Finansal Rapor",
            disclosure_type="FR",
            raw={"disclosureBasic": {"year": 2025, "ruleType": "Yıllık", "summary": "31.12.2025"}},
        ),
    ]
    statement = FinancialStatement(
        disclosure_index=1600000,
        stock_code="THYAO",
        period_labels=["Cari Dönem 31.12.2025"],
        items=[
            FinancialLineItem(
                disclosure_index=1600000,
                statement_role_code="210015",
                statement_name="balance_sheet",
                taxonomy_code="cash",
                period_label="Cari Dönem 31.12.2025",
                value_text="1",
            )
        ],
    )
    selected: list[int] = []
    with KapClient() as client:
        monkeypatch.setattr(client, "_resolve_member_oid", lambda ticker: "oid")
        monkeypatch.setattr(
            client.disclosures,
            "get_company_disclosures",
            lambda **kwargs: selectors.append(kwargs["range_value"]) or candidates,
        )
        monkeypatch.setattr(
            client.financials,
            "get_financial_statement",
            lambda index, **kwargs: selected.append(index) or statement,
        )
        result = client.get_financials("THYAO", 2025, "annual")

    assert result.disclosure_index == 1600000
    assert selected == [1600000]
    assert selectors == [2026]


def test_financial_period_matches_live_donem_code_for_annual_report(monkeypatch):
    candidate = Disclosure(
        disclosure_index=1565996,
        publish_date="04.03.2026 18:55:17",
        title="Finansal Rapor",
        disclosure_type="FR",
        raw={"disclosureBasic": {"year": 2025, "donem": 4, "period": "3AB"}},
    )
    statement = FinancialStatement(
        disclosure_index=1565996,
        stock_code="THYAO",
        period_labels=["Cari Dönem 31.12.2025"],
        items=[
            FinancialLineItem(
                disclosure_index=1565996,
                statement_role_code="210015",
                statement_name="balance_sheet",
                taxonomy_code="cash",
                period_label="Cari Dönem 31.12.2025",
                value_text="1",
            )
        ],
    )
    with KapClient() as client:
        monkeypatch.setattr(client, "_resolve_member_oid", lambda ticker: "oid")
        monkeypatch.setattr(client.disclosures, "get_company_disclosures", lambda **kwargs: [candidate])
        monkeypatch.setattr(client.financials, "get_financial_statement", lambda *args, **kwargs: statement)
        result = client.get_financials("THYAO", 2025, "annual")

    assert result.disclosure_index == 1565996


def test_latest_ticker_query_uses_company_history_not_active_home_feed(monkeypatch):
    expected = [Disclosure(disclosure_index=42, stock_code="GARAN", title="Latest")]
    with KapClient() as client:
        monkeypatch.setattr(client, "_resolve_member_oid", lambda ticker: "oid")
        monkeypatch.setattr(
            client.disclosures,
            "get_company_disclosures",
            lambda **kwargs: expected,
        )
        monkeypatch.setattr(
            client.disclosures,
            "get_latest_disclosures",
            lambda **kwargs: (_ for _ in ()).throw(AssertionError("home feed must not be used")),
        )
        rows = client.get_latest_disclosures(limit=10, ticker="GARAN")

    assert rows == expected
