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
        publish = getattr(self, "_publish_metrics", None)

        def publish_metrics(value: dict[str, Any]) -> None:
            if callable(publish):
                publish(value)
            else:
                setattr(self, "last_request_metrics", dict(value))

        parse_started = time.perf_counter()
        metrics = dict(getattr(self, "last_request_metrics", {}))
        metrics["stage"] = "parse"
        publish_metrics(metrics)
        remaining = deadline_at - time.monotonic()
        if remaining <= 0:
            metrics.update(stage="deadline", error="operation deadline exceeded before parsing")
            publish_metrics(metrics)
            raise KapDeadlineExceeded("Operation deadline exceeded before parsing")
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
            metrics.update(
                stage="deadline",
                parse_s=round(time.perf_counter() - parse_started, 6),
                error="operation deadline exceeded during parsing",
            )
            metrics["total_s"] = round(float(metrics.get("fetch_s", 0)) + float(metrics["parse_s"]), 6)
            publish_metrics(metrics)
            raise KapDeadlineExceeded("Operation deadline exceeded after parsing started")
        if "error" in result:
            metrics.update(
                stage="parse_error",
                parse_s=round(time.perf_counter() - parse_started, 6),
                error=f"{type(result['error']).__name__}: {result['error']}",
            )
            publish_metrics(metrics)
            raise result["error"]
        metrics.update(stage="ok", parse_s=round(time.perf_counter() - parse_started, 6))
        metrics["total_s"] = round(float(metrics.get("fetch_s", 0)) + float(metrics["parse_s"]), 6)
        publish_metrics(metrics)
        return result.get("value")

    async def run_with_deadline_async(self, func: Any, *, deadline_at: float | None) -> Any:
        """Run a synchronous parser with a hard caller-visible deadline."""
        if deadline_at is None:
            return func()
        publish = getattr(self, "_publish_metrics", None)

        def publish_metrics(value: dict[str, Any]) -> None:
            if callable(publish):
                publish(value)
            else:
                setattr(self, "last_request_metrics", dict(value))

        parse_started = time.perf_counter()
        metrics = dict(getattr(self, "last_request_metrics", {}))
        metrics["stage"] = "parse"
        publish_metrics(metrics)
        remaining = deadline_at - time.monotonic()
        if remaining <= 0:
            metrics.update(stage="deadline", error="operation deadline exceeded before parsing")
            publish_metrics(metrics)
            raise KapDeadlineExceeded("Operation deadline exceeded before parsing")
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
            metrics.update(stage="ok", parse_s=round(time.perf_counter() - parse_started, 6))
            metrics["total_s"] = round(float(metrics.get("fetch_s", 0)) + float(metrics["parse_s"]), 6)
            publish_metrics(metrics)
            return value
        except asyncio.TimeoutError as exc:
            metrics.update(
                stage="deadline",
                parse_s=round(time.perf_counter() - parse_started, 6),
                error="operation deadline exceeded during parsing",
            )
            metrics["total_s"] = round(float(metrics.get("fetch_s", 0)) + float(metrics["parse_s"]), 6)
            publish_metrics(metrics)
            raise KapDeadlineExceeded("Operation deadline exceeded after parsing started") from exc

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
        max_attempts = self._max_attempts()
        deadline = deadline_at or self.operation_deadline()
        operation_started = time.perf_counter()
        metrics = self._timing_context(timing, self.last_request_metrics)
        metrics["stage"] = "request"
        for attempt in range(1, max_attempts + 1):
            metrics["attempts"] = attempt
            request_started: float | None = None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                metrics.update(stage="deadline", error="request deadline exceeded")
                self._finish_http_metrics(metrics, operation_started=operation_started)
                self._publish_metrics(metrics)
                raise KapDeadlineExceeded(f"Request deadline exceeded for {path_or_url}")
            try:
                request_started = time.perf_counter()
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
                        metrics["ttfb_s"] = round(time.perf_counter() - request_started, 6)
                        if streamed.is_error:
                            resp = streamed
                        else:
                            streamed.read()
                            metrics["download_s"] = round(time.perf_counter() - request_started - float(metrics["ttfb_s"]), 6)
                            resp = streamed
                metrics["request_s"] = round(time.perf_counter() - request_started, 6)
                metrics["fetch_s"] = round(time.perf_counter() - operation_started, 6)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= max_attempts:
                    metrics.update(stage="error", error=f"{type(exc).__name__}: {exc}")
                    self._finish_http_metrics(
                        metrics,
                        operation_started=operation_started,
                        request_started=request_started,
                    )
                    self._publish_metrics(metrics)
                    raise KapConnectionError(
                        f"Request failed after {attempt} attempts for {path_or_url}: {exc}"
                    ) from exc
                delay = self._retry_delay(None, attempt)
                logger.warning("Transient HTTP error (%s) for %s; retrying in %.2fs", exc, path_or_url, delay)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    metrics.update(stage="deadline", error="request deadline exceeded")
                    self._finish_http_metrics(
                        metrics,
                        operation_started=operation_started,
                        request_started=request_started,
                    )
                    self._publish_metrics(metrics)
                    raise KapDeadlineExceeded(f"Request deadline exceeded for {path_or_url}") from exc
                time.sleep(min(delay, remaining))
                continue

            if resp.is_error:
                if not self._retryable_status(resp.status_code) or attempt >= max_attempts:
                    metrics.update(
                        stage="http_error",
                        status_code=resp.status_code,
                        error=f"HTTP error {resp.status_code} for {path_or_url}",
                    )
                    self._finish_http_metrics(
                        metrics,
                        operation_started=operation_started,
                        request_started=request_started,
                    )
                    self._publish_metrics(metrics)
                    self._raise_http_error(resp, path_or_url)
                delay = self._retry_delay(resp, attempt)
                logger.warning(
                    "Retryable HTTP status %s for %s; retrying in %.2fs",
                    resp.status_code,
                    path_or_url,
                    delay,
                )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    metrics.update(stage="deadline", error="request deadline exceeded")
                    self._finish_http_metrics(
                        metrics,
                        operation_started=operation_started,
                        request_started=request_started,
                    )
                    self._publish_metrics(metrics)
                    raise KapDeadlineExceeded(f"Request deadline exceeded for {path_or_url}")
                time.sleep(min(delay, remaining))
                continue
            if time.monotonic() >= deadline:
                metrics.update(stage="deadline", error="request deadline exceeded")
                self._finish_http_metrics(
                    metrics,
                    operation_started=operation_started,
                    request_started=request_started,
                )
                self._publish_metrics(metrics)
                raise KapDeadlineExceeded(f"Request deadline exceeded for {path_or_url}")
            metrics["stage"] = "http_success"
            self._finish_http_metrics(
                metrics,
                operation_started=operation_started,
                request_started=request_started,
            )
            self._publish_metrics(metrics)
            return resp

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
        max_attempts = self._max_attempts()
        deadline = deadline_at or self.operation_deadline()
        operation_started = time.perf_counter()
        metrics = self._timing_context(timing, self.last_request_metrics)
        metrics["stage"] = "request"
        for attempt in range(1, max_attempts + 1):
            metrics["attempts"] = attempt
            request_started: float | None = None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                metrics.update(stage="deadline", error="request deadline exceeded")
                self._finish_http_metrics(metrics, operation_started=operation_started)
                self._publish_metrics(metrics)
                raise KapDeadlineExceeded(f"Request deadline exceeded for {path_or_url}")
            try:
                try:
                    await asyncio.wait_for(self._async_semaphore.acquire(), timeout=remaining)
                except asyncio.TimeoutError as exc:
                    metrics.update(stage="deadline", error="request deadline exceeded waiting for concurrency slot")
                    self._finish_http_metrics(metrics, operation_started=operation_started)
                    self._publish_metrics(metrics)
                    raise KapDeadlineExceeded(
                        f"Request deadline exceeded waiting for concurrency slot: {path_or_url}"
                    ) from exc
                try:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        metrics.update(stage="deadline", error="request deadline exceeded before HTTP request")
                        self._finish_http_metrics(metrics, operation_started=operation_started)
                        self._publish_metrics(metrics)
                        raise KapDeadlineExceeded(f"Request deadline exceeded for {path_or_url}")
                    request_started = time.perf_counter()
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
                            metrics["ttfb_s"] = round(time.perf_counter() - request_started, 6)
                            if streamed.is_error:
                                resp = streamed
                            else:
                                await streamed.aread()
                                metrics["download_s"] = round(time.perf_counter() - request_started - float(metrics["ttfb_s"]), 6)
                                resp = streamed
                    metrics["request_s"] = round(time.perf_counter() - request_started, 6)
                    metrics["fetch_s"] = round(time.perf_counter() - operation_started, 6)
                finally:
                    self._async_semaphore.release()
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= max_attempts:
                    metrics.update(stage="error", error=f"{type(exc).__name__}: {exc}")
                    self._finish_http_metrics(
                        metrics,
                        operation_started=operation_started,
                        request_started=request_started,
                    )
                    self._publish_metrics(metrics)
                    raise KapConnectionError(
                        f"Request failed after {attempt} attempts for {path_or_url}: {exc}"
                    ) from exc
                delay = self._retry_delay(None, attempt)
                logger.warning("Transient async HTTP error (%s) for %s; retrying in %.2fs", exc, path_or_url, delay)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    metrics.update(stage="deadline", error="request deadline exceeded")
                    self._finish_http_metrics(
                        metrics,
                        operation_started=operation_started,
                        request_started=request_started,
                    )
                    self._publish_metrics(metrics)
                    raise KapDeadlineExceeded(f"Request deadline exceeded for {path_or_url}") from exc
                await asyncio.sleep(min(delay, remaining))
                continue

            if resp.is_error:
                if not self._retryable_status(resp.status_code) or attempt >= max_attempts:
                    metrics.update(
                        stage="http_error",
                        status_code=resp.status_code,
                        error=f"HTTP error {resp.status_code} for {path_or_url}",
                    )
                    self._finish_http_metrics(
                        metrics,
                        operation_started=operation_started,
                        request_started=request_started,
                    )
                    self._publish_metrics(metrics)
                    self._raise_http_error(resp, path_or_url)
                delay = self._retry_delay(resp, attempt)
                logger.warning(
                    "Retryable async HTTP status %s for %s; retrying in %.2fs",
                    resp.status_code,
                    path_or_url,
                    delay,
                )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    metrics.update(stage="deadline", error="request deadline exceeded")
                    self._finish_http_metrics(
                        metrics,
                        operation_started=operation_started,
                        request_started=request_started,
                    )
                    self._publish_metrics(metrics)
                    raise KapDeadlineExceeded(f"Request deadline exceeded for {path_or_url}")
                await asyncio.sleep(min(delay, remaining))
                continue
            if time.monotonic() >= deadline:
                metrics.update(stage="deadline", error="request deadline exceeded")
                self._finish_http_metrics(
                    metrics,
                    operation_started=operation_started,
                    request_started=request_started,
                )
                self._publish_metrics(metrics)
                raise KapDeadlineExceeded(f"Request deadline exceeded for {path_or_url}")
            metrics["stage"] = "http_success"
            self._finish_http_metrics(
                metrics,
                operation_started=operation_started,
                request_started=request_started,
            )
            self._publish_metrics(metrics)
            return resp

        raise KapConnectionError(f"Request failed for {path_or_url}")
