from __future__ import annotations

from pathlib import Path

from kap.scrapers.disclosures import (
    _extract_rsc_attachment_objects,
    _matches_ticker,
    parse_disclosure_detail_html,
)
from kap.models.disclosure import Disclosure


FIXTURE = Path(__file__).parent / "fixtures" / "disclosure_detail.html"


def test_disclosure_detail_live_fixture_parses_title_body_and_file_download() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    detail = parse_disclosure_detail_html(
        html,
        disclosure_index=1645958,
        url="https://www.kap.org.tr/tr/Bildirim/1645958",
        base_url="https://www.kap.org.tr",
        lang="tr",
    )

    assert detail.title == "Finansal Rapor"
    assert detail.stock_code == "KTLEV"
    assert detail.company_title == "KATILIMEVİM TASARRUF FİNANSMAN A.Ş."
    assert detail.content_text == "Finansal Tablolara İlişkin Genel Açıklama\nBu metin bildirim gövdesidir."
    assert detail.attachment_urls == [
        "https://www.kap.org.tr/tr/api/file/download/4028328c9f52dc3f019fe89234be03c1"
    ]


def test_disclosure_detail_live_fixture_reads_rsc_attachment_metadata() -> None:
    html = FIXTURE.read_text(encoding="utf-8")

    attachments = _extract_rsc_attachment_objects(html)

    assert attachments == [{
        "objId": "4028328c9f52dc3f019fe89234be03c1",
        "fileName": "30.06.2026 Tarihli Finansal Rapor.pdf",
        "fileExtension": "pdf",
    }]


def test_ticker_filter_uses_exact_tokens() -> None:
    disclosure = Disclosure(
        disclosure_index=1,
        stock_code="THYAO",
        related_stocks="THYAO, AEFES",
    )
    assert _matches_ticker(disclosure, "THYAO")
    assert _matches_ticker(disclosure, "AEFES")
    assert not _matches_ticker(disclosure, "H")
    assert not _matches_ticker(disclosure, "THY")
