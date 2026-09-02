from __future__ import annotations

import asyncio

import httpx
import pytest

from kap.config import KapConfig
from kap.scrapers.base import BaseScraper, KapError, KapNotFoundError
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
