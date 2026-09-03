from __future__ import annotations

import asyncio
import datetime
from pathlib import Path
from types import SimpleNamespace

from kap.scrapers.disclosures import (
    _extract_rsc_attachment_objects,
    _historical_date_windows,
    _historical_payload,
    _matches_ticker,
    _normalize_raw_disclosure,
    parse_disclosure_detail_html,
)
from kap.models.disclosure import Disclosure
from kap.scrapers.disclosures import DisclosuresScraper


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


def test_disclosure_detail_uses_primary_ticker_from_multi_code_company_link(monkeypatch) -> None:
    monkeypatch.setattr(
        "kap.scrapers.disclosures._extract_rsc_detail_metadata",
        lambda html: {
            "title": "Özel Durum Açıklaması",
            "publish_date": "02.09.2026 18:12:19",
            "disclosure_type": "ÖDA",
        },
    )
    html = """
    <a href="/tr/sirket-bilgileri/ozet/2422">TÜRKİYE GARANTİ BANKASI A.Ş.</a>
    <a href="/tr/sirket-bilgileri/ozet/2422">GARAN, TGB</a>
    <div class="notification-body-scale-42">Açıklama gövdesi</div>
    """

    detail = parse_disclosure_detail_html(
        html,
        disclosure_index=42,
        url="https://www.kap.org.tr/tr/Bildirim/42",
        base_url="https://www.kap.org.tr",
        lang="tr",
    )

    assert detail.stock_code == "GARAN"
    assert detail.company_title == "TÜRKİYE GARANTİ BANKASI A.Ş."
    assert detail.disclosure_type == "ÖDA"
    assert detail.disclosure_class == "ODA"


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


def test_async_disclosure_type_and_subject_endpoints_have_sync_parity() -> None:
    class AsyncJsonBase:
        async def request_async(self, method, path, **kwargs):
            if "/subjects/" in path:
                payload = [{"disclosureClass": "FR", "subject": "Finansal Rapor", "subjectOid": "oid"}]
            else:
                payload = [{"disclosureBasic": {"disclosureIndex": 42, "title": "Faaliyet Raporu"}}]
            return SimpleNamespace(json=lambda: payload)

        def operation_deadline(self):
            return None

        async def run_with_deadline_async(self, func, *, deadline_at):
            return func()

    async def run() -> None:
        scraper = DisclosuresScraper(base_scraper=AsyncJsonBase())
        rows = await scraper.aget_company_disclosures_by_type("member", "FAR")
        subjects = await scraper.aget_disclosure_subjects("FR")
        assert rows == [{"disclosureIndex": 42, "title": "Faaliyet Raporu"}]
        assert subjects[0].subject == "Finansal Rapor"

    asyncio.run(run())


def test_historical_query_uses_current_form_payload_and_bounded_windows() -> None:
    windows = _historical_date_windows(
        datetime.date(2024, 1, 1),
        datetime.date(2025, 12, 31),
    )
    assert len(windows) == 2
    assert windows[0] == (datetime.date(2024, 1, 1), datetime.date(2024, 12, 31))
    assert windows[1][0] == datetime.date(2025, 1, 1)

    payload = _historical_payload("member", windows[0][0], windows[0][1], "FR", "subject")
    assert payload["memberType"] == "IGS"
    assert payload["marketOid"] == ""
    assert payload["subjectList"] == ["subject"]
    assert _historical_payload("member", windows[0][0], windows[0][1], "FR", "")["subjectList"] == []


def test_historical_flat_payload_is_normalized_using_current_kap_fields() -> None:
    row = _normalize_raw_disclosure({
        "disclosureIndex": 1657216,
        "publishDate": "02.09.2026 11:23:45",
        "stockCodes": "THYAO, THYAO",
        "kapTitle": "TÜRK HAVA YOLLARI A.O.",
        "subject": "Finansal Rapor",
        "disclosureClass": "FR",
        "relatedStocks": "PGSUS",
        "year": 2025,
        "ruleType": 4,
    })

    assert row.disclosure_index == 1657216
    assert row.stock_code == "THYAO"
    assert row.related_stocks == "PGSUS"
    assert row.company_title == "TÜRK HAVA YOLLARI A.O."
    assert row.title == "Finansal Rapor"
    assert row.disclosure_type == "FR"
    assert row.disclosure_class == "FR"


def test_async_historical_windows_are_fetched_concurrently() -> None:
    """KAP only accepts one-year windows, so a multi-year query is several
    requests. They must overlap instead of costing one round trip each."""
    in_flight = 0
    peak = 0

    class ConcurrentBase:
        async def request_async(self, method, path, **kwargs):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            try:
                await asyncio.sleep(0.01)
            finally:
                in_flight -= 1
            window = kwargs["json"]["fromDate"]
            return SimpleNamespace(json=lambda window=window: [{
                "disclosureIndex": int(window[:4]),
                "publishDate": f"01.01.{window[:4]} 09:00:00",
                "stockCodes": "THYAO",
                "subject": "Finansal Rapor",
            }])

        def operation_deadline(self):
            return None

        async def run_with_deadline_async(self, func, *, deadline_at):
            return func()

    scraper = DisclosuresScraper(base_scraper=ConcurrentBase())

    rows = asyncio.run(
        scraper.aget_historical_disclosures_by_criteria(
            member_oid="oid",
            from_date=datetime.date(2021, 1, 1),
            to_date=datetime.date(2025, 1, 1),
        )
    )

    assert len(_historical_date_windows(datetime.date(2021, 1, 1), datetime.date(2025, 1, 1))) > 1
    assert peak > 1
    assert [row.disclosure_index for row in rows] == sorted(
        (row.disclosure_index for row in rows), reverse=True
    )


def _subject_probe_base(captured: list[dict]) -> object:
    class SubjectBase:
        def request_sync(self, method, path, **kwargs):
            captured.append(kwargs["json"])
            return SimpleNamespace(json=lambda: [
                {"disclosureIndex": 3, "subject": "Finansal Rapor", "disclosureClass": "FR"},
                {"disclosureIndex": 2, "subject": "Sorumluluk Beyanı (Konsolide)", "disclosureClass": "FR"},
                {"disclosureIndex": 1, "subject": "Faaliyet Raporu (Konsolide)", "disclosureClass": "FR"},
            ])

        def operation_deadline(self):
            return None

        def run_with_deadline_sync(self, func, *, deadline_at):
            return func()

    return SubjectBase()


def test_historical_subject_filter_is_applied_to_rows_not_to_the_payload(monkeypatch) -> None:
    """KAP answers any non-empty subjectList with zero rows whatever OID it is
    given, so the query must stay unfiltered on the wire and narrow the result
    by the subject each row reports. The qualifier KAP appends to a subject
    ("... (Konsolide)") means the match has to be a prefix, not equality."""
    from kap.models.disclosure import DisclosureSubject

    captured: list[dict] = []
    scraper = DisclosuresScraper(base_scraper=_subject_probe_base(captured))
    monkeypatch.setattr(
        scraper,
        "get_disclosure_subjects",
        lambda disclosure_class="FR": [
            DisclosureSubject(disclosure_class="FR", subject="Finansal Rapor", subject_oid="fr-oid"),
            DisclosureSubject(disclosure_class="FR", subject="Sorumluluk Beyanı", subject_oid="sb-oid"),
        ],
    )

    rows = scraper.get_historical_disclosures_by_criteria(
        member_oid="oid",
        from_date=datetime.date(2025, 1, 1),
        to_date=datetime.date(2025, 6, 1),
        subject_oid="fr-oid",
    )

    assert captured[0]["subjectList"] == []
    assert [row.disclosure_index for row in rows] == [3]

    consolidated = scraper.get_historical_disclosures_by_criteria(
        member_oid="oid",
        from_date=datetime.date(2025, 1, 1),
        to_date=datetime.date(2025, 6, 1),
        subject_oid="sb-oid",
    )
    assert [row.disclosure_index for row in consolidated] == [2]


def test_historical_unknown_subject_oid_is_rejected(monkeypatch) -> None:
    """Silently ignoring a filter the caller asked for would hand back every
    row as if it had matched."""
    import pytest
    from kap.exceptions import KapValidationError
    from kap.models.disclosure import DisclosureSubject

    scraper = DisclosuresScraper(base_scraper=_subject_probe_base([]))
    monkeypatch.setattr(
        scraper,
        "get_disclosure_subjects",
        lambda disclosure_class="FR": [
            DisclosureSubject(disclosure_class="FR", subject="Finansal Rapor", subject_oid="fr-oid"),
        ],
    )

    with pytest.raises(KapValidationError, match="Unknown subject_oid"):
        scraper.get_historical_disclosures_by_criteria(
            member_oid="oid",
            from_date=datetime.date(2025, 1, 1),
            to_date=datetime.date(2025, 6, 1),
            subject_oid="nope",
        )
