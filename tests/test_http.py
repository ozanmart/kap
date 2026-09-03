from __future__ import annotations

import asyncio
import datetime
import time

import httpx
import pytest

from kap.config import KapConfig
from kap.scrapers.base import (
    BaseScraper,
    KapDeadlineExceeded,
    KapError,
    KapNotFoundError,
    KapValidationError,
)
from kap.scrapers.calendar import CalendarScraper
from kap.scrapers.disclosures import DisclosuresScraper


def _scraper_with_responses(responses: list[httpx.Response], max_retries: int = 4) -> tuple[BaseScraper, list[str]]:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        response = responses[min(len(calls) - 1, len(responses) - 1)]
        response.request = request
        return response

    scraper = BaseScraper(KapConfig(base_url="https://example.test", max_retries=max_retries))
    scraper._sync_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://example.test",
    )
    return scraper, calls


def test_latest_disclosures_sends_current_member_and_type_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = DisclosuresScraper(config=KapConfig(enable_cache=False))
    payloads: list[dict[str, object]] = []

    def fake_feed(payload: dict[str, object] | None = None) -> list[object]:
        payloads.append(payload or {})
        return []

    monkeypatch.setattr(scraper, "fetch_main_feed", fake_feed)

    assert scraper.get_latest_disclosures(limit=10) == []
    assert payloads == [{"memberTypes": ["IGS", "DDK"], "disclosureTypes": []}]


def test_today_company_query_uses_complete_detailed_search_instead_of_active_feed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = DisclosuresScraper(config=KapConfig(enable_cache=False))
    payloads: list[dict[str, object]] = []

    def request(_method, path, **kwargs):
        payloads.append(kwargs["json"])
        return type("Response", (), {"json": lambda self: [{
            "disclosureIndex": 2,
            "publishDate": "02.09.2026 10:00:00",
            "stockCodes": "THYAO",
            "kapTitle": "TÜRK HAVA YOLLARI A.O.",
            "subject": "Özel Durum Açıklaması",
            "disclosureClass": "ODA",
        }]})()

    monkeypatch.setattr("kap.scrapers.disclosures.dt_cls", type("Clock", (), {
        "now": staticmethod(lambda _tz: datetime.datetime(2026, 9, 2, 12, 0, 0)),
    }))
    monkeypatch.setattr(scraper.base, "request_sync", request)

    result = scraper.get_today_disclosures(member_type="bist_sirketleri")

    assert [item.disclosure_index for item in result] == [2]
    assert payloads[0]["mkkMemberOidList"] == []
    assert payloads[0]["fromDate"] == "2026-09-02"


def test_http_503_and_429_are_retried_with_server_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        httpx.Response(503, headers={"Retry-After": "0"}),
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"ok": True}),
    ]
    scraper, calls = _scraper_with_responses(responses)
    sleeps: list[float] = []
    monkeypatch.setattr("kap.scrapers.base.time.sleep", sleeps.append)

    response = scraper.request_sync("GET", "/health")

    assert response.json() == {"ok": True}
    assert calls == ["/health", "/health", "/health"]
    assert sleeps == [0.0, 0.0]


def test_timed_http_request_reports_ttfb_and_download_phases() -> None:
    scraper, _ = _scraper_with_responses([httpx.Response(200, content=b"payload")], max_retries=1)
    timing: dict[str, float | int | str] = {}

    response = scraper.request_sync("GET", "/timed", timing=timing)

    assert response.content == b"payload"
    assert timing["attempts"] == 1
    assert float(timing["ttfb_s"]) >= 0
    assert float(timing["download_s"]) >= 0
    assert float(timing["fetch_s"]) >= float(timing["request_s"])


def test_http_404_is_not_retried() -> None:
    scraper, calls = _scraper_with_responses([httpx.Response(404)], max_retries=4)

    with pytest.raises(KapNotFoundError):
        scraper.request_sync("GET", "/missing")

    assert calls == ["/missing"]
    assert scraper.last_request_metrics["stage"] == "http_error"
    assert scraper.last_request_metrics["attempts"] == 1
    assert scraper.last_request_metrics["error"] == "HTTP error 404 for /missing"


def test_http_timeout_retries_then_raises_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timed out", request=request)

    scraper = BaseScraper(KapConfig(base_url="https://example.test", max_retries=2))
    scraper._sync_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://example.test",
    )
    monkeypatch.setattr("kap.scrapers.base.time.sleep", lambda _delay: None)

    with pytest.raises(Exception) as exc_info:
        scraper.request_sync("GET", "/slow")

    assert calls == 2
    assert exc_info.type.__name__ == "KapConnectionError"
    assert scraper.last_request_metrics["stage"] == "error"
    assert scraper.last_request_metrics["attempts"] == 2
    for field in ("request_s", "fetch_s", "parse_s", "total_s"):
        assert field in scraper.last_request_metrics
        assert float(scraper.last_request_metrics[field]) >= 0


def test_sync_http_client_pool_is_reusable_after_timeout() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectTimeout("cold TLS timeout", request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    scraper = BaseScraper(KapConfig(base_url="https://example.test", max_retries=1))
    scraper._sync_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://example.test",
    )
    original_client = scraper._sync_client
    try:
        with pytest.raises(Exception) as exc_info:
            scraper.request_sync("GET", "/cold")
        assert exc_info.type.__name__ == "KapConnectionError"

        response = scraper.request_sync("GET", "/warm")
        assert response.json() == {"ok": True}
        assert scraper._sync_client is original_client
        assert calls == 2
    finally:
        scraper.close()


def test_async_http_status_retry() -> None:
    responses = [httpx.Response(503, headers={"Retry-After": "0"}), httpx.Response(200, json={"ok": True})]

    def handler(request: httpx.Request) -> httpx.Response:
        response = responses.pop(0)
        response.request = request
        return response

    async def run() -> dict[str, bool]:
        scraper = BaseScraper(KapConfig(base_url="https://example.test", max_retries=2))
        scraper._async_client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://example.test",
        )
        try:
            response = await scraper.request_async("GET", "/health")
            return response.json()
        finally:
            await scraper.aclose()

    assert asyncio.run(run()) == {"ok": True}


def test_async_http_client_pool_is_reusable_after_timeout() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectTimeout("cold TLS timeout", request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    async def run() -> None:
        scraper = BaseScraper(KapConfig(base_url="https://example.test", max_retries=1))
        scraper._async_client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://example.test",
        )
        original_client = scraper._async_client
        try:
            with pytest.raises(Exception) as exc_info:
                await scraper.request_async("GET", "/cold")
            assert exc_info.type.__name__ == "KapConnectionError"

            response = await scraper.request_async("GET", "/warm")
            assert response.json() == {"ok": True}
            assert scraper._async_client is original_client
            assert calls == 2
        finally:
            await scraper.aclose()

    asyncio.run(run())


def test_async_http_429_honors_retry_after() -> None:
    responses = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"ok": True}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        response = responses.pop(0)
        response.request = request
        return response

    async def run() -> dict[str, bool]:
        scraper = BaseScraper(KapConfig(base_url="https://example.test", max_retries=2))
        scraper._async_client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://example.test",
        )
        try:
            response = await scraper.request_async("GET", "/rate-limited")
            return response.json()
        finally:
            await scraper.aclose()

    assert asyncio.run(run()) == {"ok": True}


def test_async_http_respects_concurrency_limit_and_survives_soak() -> None:
    active = 0
    max_active = 0
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, max_active, calls
        calls += 1
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.005)
        active -= 1
        response = httpx.Response(200, json={"ok": True}, request=request)
        return response

    async def run() -> None:
        scraper = BaseScraper(KapConfig(base_url="https://example.test", max_retries=1, max_concurrency=3))
        scraper._async_client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://example.test",
        )
        try:
            responses = await asyncio.gather(*[
                scraper.request_async("GET", f"/soak/{index}")
                for index in range(25)
            ])
            assert all(response.status_code == 200 for response in responses)
        finally:
            await scraper.aclose()

    asyncio.run(run())
    assert calls == 25
    assert max_active <= 3


def test_async_concurrency_queue_wait_is_inside_operation_deadline() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.06)
        return httpx.Response(200, json={"ok": True}, request=request)

    async def run() -> None:
        scraper = BaseScraper(KapConfig(
            base_url="https://example.test",
            max_retries=1,
            max_concurrency=1,
            request_deadline_s=1.0,
        ))
        scraper._async_client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://example.test",
        )
        first = asyncio.create_task(
            scraper.request_async("GET", "/first", deadline_at=time.monotonic() + 0.2)
        )
        await asyncio.sleep(0.005)
        started = time.monotonic()
        try:
            with pytest.raises(KapDeadlineExceeded, match="concurrency slot"):
                await scraper.request_async("GET", "/queued", deadline_at=time.monotonic() + 0.02)
            assert time.monotonic() - started < 0.05
            assert (await first).status_code == 200
        finally:
            await scraper.aclose()

    asyncio.run(run())


def test_sync_parse_work_is_bounded_by_operation_deadline() -> None:
    scraper = BaseScraper(KapConfig(base_url="https://example.test", request_deadline_s=0.02))
    scraper.begin_operation("slow_parse")

    with pytest.raises(KapDeadlineExceeded):
        scraper.run_with_deadline_sync(
            lambda: time.sleep(0.1),
            deadline_at=scraper.operation_deadline(),
        )

    assert scraper.last_request_metrics["stage"] == "deadline"
    assert float(scraper.last_request_metrics["parse_s"]) < 0.08


def test_async_parse_work_is_bounded_by_operation_deadline() -> None:
    async def run() -> None:
        scraper = BaseScraper(KapConfig(base_url="https://example.test", request_deadline_s=0.02))
        scraper.begin_operation("slow_parse")
        with pytest.raises(KapDeadlineExceeded):
            await scraper.run_with_deadline_async(
                lambda: time.sleep(0.1),
                deadline_at=scraper.operation_deadline(),
            )
        assert scraper.last_request_metrics["stage"] == "deadline"

    asyncio.run(run())


def test_timed_out_parser_thread_cannot_overwrite_new_operation_metrics() -> None:
    scraper = BaseScraper(KapConfig(base_url="https://example.test", request_deadline_s=0.01))
    scraper.begin_operation("slow_parse")

    with pytest.raises(KapDeadlineExceeded):
        scraper.run_with_deadline_sync(
            lambda: time.sleep(0.04),
            deadline_at=scraper.operation_deadline(),
        )

    replacement = scraper.begin_operation("replacement")
    time.sleep(0.05)
    assert scraper.last_request_metrics == replacement


def test_async_request_preserves_cancellation_and_closes_client() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json={"ok": True}, request=request)

    async def run() -> None:
        scraper = BaseScraper(KapConfig(base_url="https://example.test", max_retries=1))
        scraper._async_client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://example.test",
        )
        task = asyncio.create_task(scraper.request_async("GET", "/cancel"))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await scraper.aclose()
        assert scraper._async_client.is_closed


def test_disclosure_feed_rejects_error_object_instead_of_silent_empty_list() -> None:
    base, _ = _scraper_with_responses([httpx.Response(200, json={"error": "upstream changed"})], max_retries=1)
    base.begin_operation("feed")

    with pytest.raises(KapValidationError, match="Unexpected main disclosure feed"):
        DisclosuresScraper(base_scraper=base).fetch_main_feed()


def test_calendar_rejects_error_object_instead_of_silent_empty_list() -> None:
    base, _ = _scraper_with_responses([httpx.Response(200, json={"error": "upstream changed"})], max_retries=1)
    base.begin_operation("calendar")

    with pytest.raises(KapValidationError, match="expected-disclosures"):
        CalendarScraper(base_scraper=base).get_expected_disclosures(days_ahead=30)


def test_calendar_accepts_current_kap_title_only_rows_and_sorts_real_dates() -> None:
    scraper = CalendarScraper(config=KapConfig(enable_cache=False))
    scraper.set_company_title_lookup(lambda title: "THYAO" if title == "TÜRK HAVA YOLLARI A.O." else None)
    rows = scraper._parse_expected_rows([
        {
            "kapTitle": "TÜRK HAVA YOLLARI A.O.",
            "ruleTypeTerm": "9 Aylık",
            "startDate": "01.10.2026",
            "endDate": "09.11.2026",
            "subject": "Finansal Rapor",
            "year": 2026,
        },
        {
            "kapTitle": "BAŞKA ŞİRKET A.Ş.",
            "ruleTypeTerm": "6 Aylık",
            "startDate": "15.09.2026",
            "endDate": "30.09.2026",
            "subject": "Finansal Rapor",
            "year": 2026,
        },
    ])

    assert [row.company_title for row in rows] == ["BAŞKA ŞİRKET A.Ş.", "TÜRK HAVA YOLLARI A.O."]
    assert rows[1].stock_code == "THYAO"


def test_parser_failure_publishes_the_same_stage_for_both_runners() -> None:
    """The async parser runner used to let a parser exception propagate without
    ever publishing a stage, so a failed async parse looked like a still-running
    one in request metrics."""

    def boom() -> None:
        raise ValueError("bad payload")

    sync_scraper = BaseScraper(KapConfig())
    sync_scraper.begin_operation("parse_probe")
    with pytest.raises(ValueError):
        sync_scraper.run_with_deadline_sync(boom, deadline_at=time.monotonic() + 5)

    async def run() -> dict[str, object]:
        scraper = BaseScraper(KapConfig())
        scraper.begin_operation("parse_probe")
        with pytest.raises(ValueError):
            await scraper.run_with_deadline_async(boom, deadline_at=time.monotonic() + 5)
        return scraper.last_request_metrics

    async_metrics = asyncio.run(run())

    assert sync_scraper.last_request_metrics["stage"] == "parse_error"
    assert async_metrics["stage"] == "parse_error"
    assert async_metrics["error"] == sync_scraper.last_request_metrics["error"] == "ValueError: bad payload"


def test_http2_is_disabled_when_h2_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """httpx raises ImportError from its constructor when http2=True and h2 is
    absent, which would turn every network call into a hard failure rather than
    the HTTP/1.1 fallback the dependency is supposed to allow."""
    from kap.scrapers import base

    base._http2_available.cache_clear()
    monkeypatch.setattr(base.importlib.util, "find_spec", lambda name: None if name == "h2" else object())
    try:
        assert base._http2_available() is False
        scraper = base.BaseScraper(KapConfig(base_url="https://example.test"))
        try:
            assert scraper._get_sync_client() is not None
        finally:
            scraper.close()
    finally:
        base._http2_available.cache_clear()
