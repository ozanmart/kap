from __future__ import annotations

import pytest
from kap.client import KapClient
from kap.storage.sqlite import KapDatabase
from kap.models.company import Company
from kap.models.disclosure import Disclosure
from kap.models.disclosure import DisclosureDetail
from kap.models.financials import FinancialStatement
from kap.scrapers.company_general import parse_company_general_html


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
        monkeypatch.setattr(client, "get_disclosure_detail", lambda index: detail)
        events = client.extract_events_many(
            disclosure_index=1234,
            body_text="Yönetim Kurulu temettü dağıtımına karar verdi.",
        )

    assert len(events) == 2
    assert {event.event_type.value for event in events} == {"DIVIDEND", "BOARD_DECISION"}
    assert all(event.company_key == "THYAO" for event in events)


def test_client_get_financials_selects_report_by_year_and_period(monkeypatch):
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
    statement = FinancialStatement(disclosure_index=901, stock_code="THYAO")
    with KapClient() as client:
        monkeypatch.setattr(client, "get_company_disclosures", lambda **kwargs: candidates)
        monkeypatch.setattr(client, "get_financial_statement", lambda *args, **kwargs: statement)
        result = client.get_financials("THYAO", 2024, "Q1")

    assert result.disclosure_index == 901
    assert result.stock_code == "THYAO"
