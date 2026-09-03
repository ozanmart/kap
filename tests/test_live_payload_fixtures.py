from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from kap.config import KapConfig
from kap.scrapers.company_general import parse_company_general_html
from kap.scrapers.disclosures import DisclosuresScraper, parse_disclosure_detail_html
from kap.scrapers.financials import parse_financial_statement_html


FIXTURES = Path(__file__).parent / "fixtures"


class JsonFixtureBase:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def request_sync(self, method: str, path: str, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(json=lambda: self.payload)

    def operation_deadline(self):
        return None

    def run_with_deadline_sync(self, func, *, deadline_at=None):
        return func()


def test_captured_live_feed_payload_uses_current_disclosure_basic_schema() -> None:
    payload = json.loads((FIXTURES / "kap_feed_live.json").read_text(encoding="utf-8"))
    scraper = DisclosuresScraper(
        base_scraper=JsonFixtureBase(payload),
        config=KapConfig(base_url="https://www.kap.org.tr", enable_cache=False),
    )

    rows = scraper.fetch_main_feed({"memberTypes": ["IGS"], "disclosureTypes": []})

    assert [row.disclosure_index for row in rows] == [1656995, 1656994, 1656993]
    assert rows[0].stock_code == "KATVK"
    assert rows[0].disclosure_id == "4028328c9f52dc4001a05d2b62865938"


def test_captured_live_detail_fixture_recovers_identity_and_attachment() -> None:
    html = (FIXTURES / "kap_detail_live.html").read_text(encoding="utf-8")

    detail = parse_disclosure_detail_html(
        html,
        1656913,
        "https://www.kap.org.tr/tr/Bildirim/1656913",
        "https://www.kap.org.tr",
        "tr",
    )

    assert detail.stock_code == "KUVVA"
    assert detail.disclosure_id == "4028328c9f52dc4001a047bd95f17f98"
    assert detail.title == "Finansal Rapor"
    assert detail.publish_date == "01.09.2026 18:22:00"
    assert detail.disclosure_type == "FR"
    assert detail.disclosure_class == "FR"
    assert detail.attachment_urls == [
        "https://www.kap.org.tr/tr/api/file/download/4028328c9f52dc4001a047bd95f17f99"
    ]
    assert detail.attachment_metadata[0]["fileExtension"] == "pdf"


def test_captured_live_financial_fixture_preserves_periods_and_currency() -> None:
    html = (FIXTURES / "kap_financial_live.html").read_text(encoding="utf-8")

    statement = parse_financial_statement_html(
        html,
        1656913,
        "https://www.kap.org.tr/tr/Bildirim/1656913",
        stock_code="KUVVA",
    )

    assert statement.currency == "TRY"
    assert statement.scale == 1_000_000
    assert statement.period_labels == ["Cari Dönem 30.06.2026", "Önceki Dönem 31.12.2025"]
    assert len(statement.items) == 2
    assert {item.value_numeric for item in statement.items} == {2501445, 3940041}
    assert {item.normalized_value for item in statement.items} == {
        2_501_445_000_000,
        3_940_041_000_000,
    }


def test_captured_live_company_general_fixture_uses_current_sections() -> None:
    html = (FIXTURES / "kap_company_general_live.html").read_text(encoding="utf-8")

    info = parse_company_general_html(
        html,
        "4028e4a2420327a4014209c55161144d",
        "https://www.kap.org.tr/tr/sirket-bilgileri/genel/4028e4a2420327a4014209c55161144d",
    )

    assert info.company_title == "ACISELSAN ACIPAYAM SELÜLOZ SANAYİ VE TİCARET A.Ş."
    assert info.website == "www.aciselsan.com.tr"
    assert info.activity_field == "Selüloz ve Selüloz Türevlerinin Üretimi ve Ticareti"
    assert info.market == "ANA PAZAR"
