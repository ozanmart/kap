from __future__ import annotations

import asyncio
import contextvars
import email.utils
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any
import httpx

from ..config import KapConfig
from ..exceptions import (
    KapConnectionError,
    KapDeadlineExceeded,
    KapError,
    KapNotFoundError,
    KapValidationError,
)

logger = logging.getLogger("kap.scraper")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}


class BaseScraper:
    """Base scraper providing resilient synchronous and asynchronous HTTP requests."""

    def __init__(self, config: KapConfig | None = None) -> None:
        self.config = config or KapConfig()
        self._sync_client: httpx.Client | None = None
        self._async_client: httpx.AsyncClient | None = None
        self._async_semaphore: asyncio.Semaphore | None = None
        # Context-local deadlines keep concurrent async tasks and worker
        # threads from stealing or extending each other's operation budget.
        self._operation_deadline: contextvars.ContextVar[float | None] = contextvars.ContextVar(
            f"kap_operation_deadline_{id(self)}",
            default=None,
        )
        self.last_request_metrics: dict[str, Any] = {}

    def begin_operation(self, operation: str) -> dict[str, Any]:
        """Start a request operation and clear metrics from the previous operation."""
        self._operation_deadline.set(time.monotonic() + self.config.request_deadline_s)
        self.last_request_metrics = {
            "operation_id": uuid.uuid4().hex[:16],
            "operation": operation,
            "stage": "cache_lookup",
            "attempts": 0,
            "request_s": 0.0,
            "fetch_s": 0.0,
            "parse_s": 0.0,
            "total_s": 0.0,
        }
        return dict(self.last_request_metrics)

    def operation_deadline(self) -> float:
        """Return the active operation deadline, creating one for direct scraper use."""
        now = time.monotonic()
        deadline = self._operation_deadline.get()
        if deadline is None:
            deadline = now + self.config.request_deadline_s
            self._operation_deadline.set(deadline)
        return deadline

    def _timeout_for_remaining(self, remaining: float) -> httpx.Timeout:
        """Cap each granular timeout by the remaining operation budget."""
        budget = max(0.001, min(float(self.config.timeout_s), float(remaining)))
        return httpx.Timeout(
            timeout=budget,
            connect=min(self.config.connect_timeout_s, budget),
            read=min(self.config.read_timeout_s, budget),
            write=min(self.config.write_timeout_s, budget),
            pool=min(self.config.pool_timeout_s, budget),
        )

    @staticmethod
    def _timing_context(
        timing: dict[str, Any] | None,
        previous: dict[str, Any],
    ) -> dict[str, Any]:
        operation_id = (timing or {}).get("operation_id") or previous.get("operation_id") or uuid.uuid4().hex[:16]
        operation = (timing or {}).get("operation") or previous.get("operation") or "http_request"
        if timing is not None:
            timing.clear()
            timing.update({"operation_id": operation_id, "operation": operation, "attempts": 0})
            return timing
        return {"operation_id": operation_id, "operation": operation, "attempts": 0}

    def _publish_metrics(self, metrics: dict[str, Any]) -> None:
        self.last_request_metrics = dict(metrics)

    @staticmethod
    def _finish_http_metrics(
        metrics: dict[str, Any],
        *,
        operation_started: float,
        request_started: float | None = None,
    ) -> None:
        """Populate stable duration fields for both success and failure exits."""
        if request_started is not None:
            metrics["request_s"] = round(time.perf_counter() - request_started, 6)
        else:
            metrics.setdefault("request_s", 0.0)
        metrics["fetch_s"] = round(time.perf_counter() - operation_started, 6)
        metrics.setdefault("parse_s", 0.0)
        metrics["total_s"] = round(float(metrics["fetch_s"]) + float(metrics["parse_s"]), 6)

    def run_with_deadline_sync(self, func: Any, *, deadline_at: float | None) -> Any:
        """Run a parser in a daemon thread so an overlong parse cannot block the caller."""
        if deadline_at is None:
            return func()
        cycle = _ParseCycle(self, deadline_at)
        remaining = cycle.remaining()
        result: dict[str, Any] = {}

        def worker() -> None:
            try:
                result["value"] = func()
            except BaseException as exc:  # propagate parser exceptions to the caller
                result["error"] = exc

        thread = threading.Thread(target=worker, name="kap-parse-deadline", daemon=True)
        thread.start()
        thread.join(remaining)
        if thread.is_alive():
            raise cycle.timed_out()
        if "error" in result:
            raise cycle.failed(result["error"])
        return cycle.succeeded(result.get("value"))

    async def run_with_deadline_async(self, func: Any, *, deadline_at: float | None) -> Any:
        """Run a synchronous parser with a hard caller-visible deadline."""
        if deadline_at is None:
            return func()
        cycle = _ParseCycle(self, deadline_at)
        remaining = cycle.remaining()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()

        def set_result(value: Any) -> None:
            if not future.done():
                future.set_result(value)

        def set_exception(exc: BaseException) -> None:
            if not future.done():
                future.set_exception(exc)

        def worker() -> None:
            try:
                value = func()
            except BaseException as exc:
                try:
                    loop.call_soon_threadsafe(set_exception, exc)
                except RuntimeError:
                    # The caller may have timed out and closed its event loop
                    # while this daemon parser was finishing.
                    return
            else:
                try:
                    loop.call_soon_threadsafe(set_result, value)
                except RuntimeError:
                    return

        threading.Thread(target=worker, name="kap-parse-deadline", daemon=True).start()
        try:
            value = await asyncio.wait_for(future, timeout=remaining)
        except asyncio.TimeoutError as exc:
            raise cycle.timed_out() from exc
        except Exception as exc:
            raise cycle.failed(exc)
        return cycle.succeeded(value)

    def _get_sync_client(self) -> httpx.Client:
        if self._sync_client is None or self._sync_client.is_closed:
            timeout = httpx.Timeout(
                timeout=self.config.timeout_s,
                connect=self.config.connect_timeout_s,
                read=self.config.read_timeout_s,
                write=self.config.write_timeout_s,
                pool=self.config.pool_timeout_s,
            )
            self._sync_client = httpx.Client(
                base_url=self.config.base_url,
                timeout=timeout,
                headers=DEFAULT_HEADERS,
                follow_redirects=True,
                http2=True,
            )
        return self._sync_client

    def _get_async_client(self) -> httpx.AsyncClient:
        if self._async_client is None or self._async_client.is_closed:
            timeout = httpx.Timeout(
                timeout=self.config.timeout_s,
                connect=self.config.connect_timeout_s,
                read=self.config.read_timeout_s,
                write=self.config.write_timeout_s,
                pool=self.config.pool_timeout_s,
            )
            self._async_client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=timeout,
                headers=DEFAULT_HEADERS,
                follow_redirects=True,
                http2=True,
            )
        return self._async_client

    def close(self) -> None:
        if self._sync_client and not self._sync_client.is_closed:
            self._sync_client.close()

    async def aclose(self) -> None:
        if self._async_client and not self._async_client.is_closed:
            await self._async_client.aclose()

    @staticmethod
    def _retryable_status(status_code: int) -> bool:
        return status_code in {408, 425, 429, 500, 502, 503, 504}

    def _max_attempts(self) -> int:
        return max(1, int(self.config.max_retries))

    def _retry_delay(self, response: httpx.Response | None, attempt: int) -> float:
        """Honor server backoff hints, then use bounded exponential backoff."""
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return min(60.0, max(0.0, float(retry_after)))
                except ValueError:
                    try:
                        retry_at = email.utils.parsedate_to_datetime(retry_after)
                        if retry_at.tzinfo is None:
                            retry_at = retry_at.replace(tzinfo=timezone.utc)
                        return min(60.0, max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds()))
                    except (TypeError, ValueError, OverflowError):
                        pass
            reset_at = response.headers.get("X-RateLimit-Reset")
            if reset_at:
                try:
                    return min(60.0, max(0.0, float(reset_at) - time.time()))
                except ValueError:
                    pass
        return min(10.0, float(2 ** max(0, attempt - 1)))

    def _raise_http_error(self, response: httpx.Response, path_or_url: str) -> None:
        if response.status_code == 404:
            raise KapNotFoundError(f"Resource not found: {path_or_url}")
        raise KapError(f"HTTP error {response.status_code} for {path_or_url}")

    def request_sync(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        deadline_at: float | None = None,
        timing: dict[str, Any] | None = None,
    ) -> httpx.Response:
        client = self._get_sync_client()
        cycle = _RequestCycle(self, path_or_url, timing, deadline_at)
        for attempt in range(1, cycle.max_attempts + 1):
            remaining = cycle.begin_attempt(attempt)
            try:
                cycle.start_request()
                if timing is None:
                    resp = client.request(
                        method=method,
                        url=path_or_url,
                        params=params,
                        json=json,
                        headers=headers,
                        timeout=self._timeout_for_remaining(remaining),
                    )
                else:
                    with client.stream(
                        method=method,
                        url=path_or_url,
                        params=params,
                        json=json,
                        headers=headers,
                        timeout=self._timeout_for_remaining(remaining),
                    ) as streamed:
                        cycle.record_ttfb()
                        if not streamed.is_error:
                            streamed.read()
                            cycle.record_download()
                        resp = streamed
                cycle.record_sent()
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                time.sleep(cycle.on_transport_error(exc, attempt))
                continue

            if resp.is_error:
                time.sleep(cycle.on_error_response(resp, attempt))
                continue
            return cycle.finish(resp)

        raise KapConnectionError(f"Request failed for {path_or_url}")

    async def request_async(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        deadline_at: float | None = None,
        timing: dict[str, Any] | None = None,
    ) -> httpx.Response:
        client = self._get_async_client()
        if self._async_semaphore is None:
            self._async_semaphore = asyncio.Semaphore(self.config.max_concurrency)
        cycle = _RequestCycle(self, path_or_url, timing, deadline_at, label="async ")
        for attempt in range(1, cycle.max_attempts + 1):
            remaining = cycle.begin_attempt(attempt)
            try:
                try:
                    await asyncio.wait_for(self._async_semaphore.acquire(), timeout=remaining)
                except asyncio.TimeoutError as exc:
                    raise cycle.slot_deadline() from exc
                try:
                    remaining = cycle.check_budget_before_request()
                    cycle.start_request()
                    if timing is None:
                        resp = await client.request(
                            method=method,
                            url=path_or_url,
                            params=params,
                            json=json,
                            headers=headers,
                            timeout=self._timeout_for_remaining(remaining),
                        )
                    else:
                        async with client.stream(
                            method=method,
                            url=path_or_url,
                            params=params,
                            json=json,
                            headers=headers,
                            timeout=self._timeout_for_remaining(remaining),
                        ) as streamed:
                            cycle.record_ttfb()
                            if not streamed.is_error:
                                await streamed.aread()
                                cycle.record_download()
                            resp = streamed
                    cycle.record_sent()
                finally:
                    self._async_semaphore.release()
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                await asyncio.sleep(cycle.on_transport_error(exc, attempt))
                continue

            if resp.is_error:
                await asyncio.sleep(cycle.on_error_response(resp, attempt))
                continue
            return cycle.finish(resp)

        raise KapConnectionError(f"Request failed for {path_or_url}")


class _RequestCycle:
    """Retry, deadline and metrics policy shared by both HTTP transports.

    ``request_sync`` and ``request_async`` differ only in how they sleep, send
    and (for async) reserve a concurrency slot. Everything else - the attempt
    budget, the deadline checks, the backoff decision and every metrics field
    published on success or failure - lives here so the two loops cannot drift
    apart.
    """

    def __init__(
        self,
        scraper: BaseScraper,
        path_or_url: str,
        timing: dict[str, Any] | None,
        deadline_at: float | None,
        label: str = "",
    ) -> None:
        self.scraper = scraper
        self.path_or_url = path_or_url
        self.label = label
        self.deadline = deadline_at or scraper.operation_deadline()
        self.operation_started = time.perf_counter()
        self.max_attempts = scraper._max_attempts()
        self.metrics = scraper._timing_context(timing, scraper.last_request_metrics)
        self.metrics["stage"] = "request"
        self.request_started: float | None = None

    # ── terminal exits ───────────────────────────────────────────────────────

    def _publish(self, stage: str, error: str, **extra: Any) -> None:
        self.metrics.update(stage=stage, error=error, **extra)
        self.scraper._finish_http_metrics(
            self.metrics,
            operation_started=self.operation_started,
            request_started=self.request_started,
        )
        self.scraper._publish_metrics(self.metrics)

    def _deadline(self, error: str, message: str) -> KapDeadlineExceeded:
        self._publish("deadline", error)
        return KapDeadlineExceeded(message)

    def _expired(self) -> KapDeadlineExceeded:
        return self._deadline(
            "request deadline exceeded",
            f"Request deadline exceeded for {self.path_or_url}",
        )

    def slot_deadline(self) -> KapDeadlineExceeded:
        """Report a deadline reached while waiting for a concurrency slot."""
        return self._deadline(
            "request deadline exceeded waiting for concurrency slot",
            f"Request deadline exceeded waiting for concurrency slot: {self.path_or_url}",
        )

    # ── per-attempt lifecycle ────────────────────────────────────────────────

    def begin_attempt(self, attempt: int) -> float:
        """Record the attempt and return the budget left for this request."""
        self.metrics["attempts"] = attempt
        self.request_started = None
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise self._expired()
        return remaining

    def check_budget_before_request(self) -> float:
        """Re-check the budget after an await that could have consumed it."""
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise self._deadline(
                "request deadline exceeded before HTTP request",
                f"Request deadline exceeded for {self.path_or_url}",
            )
        return remaining

    def start_request(self) -> None:
        self.request_started = time.perf_counter()

    def record_ttfb(self) -> None:
        self.metrics["ttfb_s"] = round(time.perf_counter() - (self.request_started or 0.0), 6)

    def record_download(self) -> None:
        elapsed = time.perf_counter() - (self.request_started or 0.0)
        self.metrics["download_s"] = round(elapsed - float(self.metrics["ttfb_s"]), 6)

    def record_sent(self) -> None:
        self.metrics["request_s"] = round(time.perf_counter() - (self.request_started or 0.0), 6)
        self.metrics["fetch_s"] = round(time.perf_counter() - self.operation_started, 6)

    # ── retry decisions ──────────────────────────────────────────────────────

    def _backoff(self, delay: float) -> float:
        """Clamp the backoff to the deadline, or raise once no room is left."""
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise self._expired()
        return min(delay, remaining)

    def on_transport_error(self, exc: Exception, attempt: int) -> float:
        """Handle a connect/read failure: return the backoff, or raise."""
        if attempt >= self.max_attempts:
            self._publish("error", f"{type(exc).__name__}: {exc}")
            raise KapConnectionError(
                f"Request failed after {attempt} attempts for {self.path_or_url}: {exc}"
            ) from exc
        delay = self.scraper._retry_delay(None, attempt)
        logger.warning(
            "Transient %sHTTP error (%s) for %s; retrying in %.2fs",
            self.label,
            exc,
            self.path_or_url,
            delay,
        )
        try:
            return self._backoff(delay)
        except KapDeadlineExceeded as deadline:
            raise deadline from exc

    def on_error_response(self, response: httpx.Response, attempt: int) -> float:
        """Handle an error status: return the backoff, or raise."""
        if not self.scraper._retryable_status(response.status_code) or attempt >= self.max_attempts:
            self._publish(
                "http_error",
                f"HTTP error {response.status_code} for {self.path_or_url}",
                status_code=response.status_code,
            )
            self.scraper._raise_http_error(response, self.path_or_url)
        delay = self.scraper._retry_delay(response, attempt)
        logger.warning(
            "Retryable %sHTTP status %s for %s; retrying in %.2fs",
            self.label,
            response.status_code,
            self.path_or_url,
            delay,
        )
        return self._backoff(delay)

    # ── success ──────────────────────────────────────────────────────────────

    def finish(self, response: httpx.Response) -> httpx.Response:
        """Publish the terminal success metrics for a usable response."""
        if time.monotonic() >= self.deadline:
            raise self._expired()
        self.metrics["stage"] = "http_success"
        self.scraper._finish_http_metrics(
            self.metrics,
            operation_started=self.operation_started,
            request_started=self.request_started,
        )
        self.scraper._publish_metrics(self.metrics)
        return response


class _ParseCycle:
    """Deadline and metrics bookkeeping shared by both parser runners.

    ``run_with_deadline_sync`` and ``run_with_deadline_async`` differ only in
    how they wait for the worker thread. Keeping the published stages here also
    fixes the async runner never reporting a ``parse_error`` stage.
    """

    def __init__(self, scraper: Any, deadline_at: float) -> None:
        self.scraper = scraper
        self.deadline_at = deadline_at
        self.parse_started = time.perf_counter()
        self.metrics = dict(getattr(scraper, "last_request_metrics", {}))
        self.metrics["stage"] = "parse"
        self.publish()

    def publish(self) -> None:
        # Scrapers may be driven by a lightweight stand-in transport in tests,
        # so fall back to the plain attribute when the hook is absent.
        publish = getattr(self.scraper, "_publish_metrics", None)
        if callable(publish):
            publish(self.metrics)
        else:
            setattr(self.scraper, "last_request_metrics", dict(self.metrics))

    def _elapsed(self) -> float:
        return round(time.perf_counter() - self.parse_started, 6)

    def _record_total(self) -> None:
        self.metrics["total_s"] = round(
            float(self.metrics.get("fetch_s", 0)) + float(self.metrics["parse_s"]), 6
        )

    def remaining(self) -> float:
        """Return the parse budget, or raise when it is already spent."""
        left = self.deadline_at - time.monotonic()
        if left <= 0:
            self.metrics.update(stage="deadline", error="operation deadline exceeded before parsing")
            self.publish()
            raise KapDeadlineExceeded("Operation deadline exceeded before parsing")
        return left

    def timed_out(self) -> KapDeadlineExceeded:
        self.metrics.update(
            stage="deadline",
            parse_s=self._elapsed(),
            error="operation deadline exceeded during parsing",
        )
        self._record_total()
        self.publish()
        return KapDeadlineExceeded("Operation deadline exceeded after parsing started")

    def failed(self, exc: BaseException) -> BaseException:
        self.metrics.update(
            stage="parse_error",
            parse_s=self._elapsed(),
            error=f"{type(exc).__name__}: {exc}",
        )
        self.publish()
        return exc

    def succeeded(self, value: Any) -> Any:
        self.metrics.update(stage="ok", parse_s=self._elapsed())
        self._record_total()
        self.publish()
        return value
