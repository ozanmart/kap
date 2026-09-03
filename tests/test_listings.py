from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from kap.config import KapConfig
from kap.scrapers.base import KapDeadlineExceeded, KapValidationError
from kap.scrapers.listings import ListingsScraper


FIXTURE = Path(__file__).parent / "fixtures" / "bist_sirketler.html"


class FixtureBase:
    def __init__(self, html: str) -> None:
        self.html = html

    def request_sync(self, method: str, path: str, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(text=self.html)


def make_scraper(html: str) -> ListingsScraper:
    return ListingsScraper(
        base_scraper=FixtureBase(html),
        config=KapConfig(base_url="https://www.kap.org.tr", registry_min_records=1),
    )


def test_live_company_listing_fixture_uses_nested_rsc_payload() -> None:
    scraper = make_scraper(FIXTURE.read_text(encoding="utf-8"))

    companies = scraper.get_companies(online=True)

    assert [company.ticker for company in companies] == ["A1CAP", "ACP", "ACSEL", "ADEL"]
    acsel = next(company for company in companies if company.ticker == "ACSEL")
    assert acsel.company_id == "4028e4a2420327a4014209c55161144d"
    assert acsel.city == "DENİZLİ"
    assert acsel.auditor.startswith("DRT BAĞIMSIZ DENETİM")


def test_live_company_listing_fixture_falls_back_to_server_rendered_table() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    scraper = make_scraper(html)

    companies = scraper._parse_companies_table(html)

    assert len(companies) == 1
    assert companies[0].ticker == "ACSEL"
    assert companies[0].summary_page == (
        "https://www.kap.org.tr/tr/sirket-bilgileri/ozet/"
        "1626-aciselsan-acipayam-seluloz-sanayi-ve-ticaret-a-s"
    )


def test_nested_listing_wrappers_are_supported_for_all_taxonomies() -> None:
    scraper = make_scraper("")

    indices = scraper._parse_indices_rows(
        [{
            "initialData": [{
                "code": "XU100",
                "name": "BIST 100",
                "indicesNo": 100,
                "content": [{"stockCode": "AKBNK", "title": "AKBANK T.A.Ş."}],
            }]
        }]
    )
    sectors = scraper._parse_sectors_rows(
        [{
            "children": {
                "sector-1": {
                    "title": "MALİ KURULUŞLAR",
                    "content": [{
                        "sectorName": "BANKALAR",
                        "sectorNo": "001000.001000.",
                        "sectorOid": "sector-1",
                        "stockCode": "AKBNK",
                    }],
                }
            }
        }]
    )
    markets = scraper._parse_markets_rows(
        [{
            "data": [{
                "marketName": "YILDIZ PAZAR",
                "marketNo": 1,
                "marketDetailContentList": [{"stockCode": "AKBNK"}],
            }]
        }]
    )

    assert indices[0].code == "XU100"
    assert indices[0].companies == ["AKBNK"]
    assert sectors[0].companies == ["AKBNK"]
    assert markets[0].companies == ["AKBNK"]


def test_captured_live_registry_fixture_validates_and_reports_phases() -> None:
    html = (FIXTURE.parent / "kap_registry_live.html").read_text(encoding="utf-8")
    scraper = ListingsScraper(
        base_scraper=FixtureBase(html),
        config=KapConfig(base_url="https://www.kap.org.tr", registry_min_records=5),
    )

    companies = scraper.get_companies(online=True)

    assert len(companies) == 5
    assert all(company.company_id for company in companies)
    assert scraper.last_registry_metrics["stage"] == "ok"
    assert scraper.last_registry_metrics["parse_s"] >= 0
    assert scraper.last_registry_metrics["total_s"] >= scraper.last_registry_metrics["parse_s"]


def test_live_registry_rejects_partial_payload_before_it_can_be_served() -> None:
    html = (FIXTURE.parent / "kap_registry_live.html").read_text(encoding="utf-8")
    scraper = ListingsScraper(
        base_scraper=FixtureBase(html),
        config=KapConfig(base_url="https://www.kap.org.tr", registry_min_records=100),
    )

    with pytest.raises(KapValidationError, match="minimum is 100"):
        scraper.get_companies(online=True)


def test_registry_deadline_includes_parse_phase(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    html = (FIXTURE.parent / "kap_registry_live.html").read_text(encoding="utf-8")
    scraper = ListingsScraper(
        base_scraper=FixtureBase(html),
        config=KapConfig(base_url="https://www.kap.org.tr", registry_min_records=5, request_deadline_s=0.01),
    )
    original = scraper._parse_companies_rows

    def slow_parse(rows):
        time.sleep(0.02)
        return original(rows)

    monkeypatch.setattr(scraper, "_parse_companies_rows", slow_parse)
    with pytest.raises(KapDeadlineExceeded, match="after parsing"):
        scraper.get_companies(online=True)
    assert scraper.last_registry_metrics["stage"] == "parse"


def test_local_search_is_case_and_diacritic_insensitive_for_turkish_names() -> None:
    """`str.upper()` is locale independent, so "Şişe".upper() yields "ŞIŞE"
    (dotless I) while the registry holds "ŞİŞE". Index and query are folded
    through one table, so a caller can also skip the diacritics entirely."""
    scraper = ListingsScraper(config=KapConfig())

    for query in ("Şişe", "şişe", "sise cam", "SISE CAM"):
        assert [c.ticker for c in scraper._local_search(query)] == ["SISE"]

    for query in ("TÜRK HAVA YOLLARI", "turk hava yollari", "Türk Hava Yolları"):
        assert [c.ticker for c in scraper._local_search(query)] == ["THYAO"]

    assert [c.ticker for c in scraper._local_search("koc holding")] == ["KCHOL"]
    assert [c.ticker for c in scraper._local_search("thyao")] == ["THYAO"]
