from __future__ import annotations

import asyncio
import email.utils
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any
import httpx

from ..config import KapConfig

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


class KapError(Exception):
    """Base exception for KAP SDK errors."""
    pass


class KapConnectionError(KapError):
    """Raised when KAP server cannot be reached."""
    pass


class KapDeadlineExceeded(KapConnectionError):
    """Raised when an operation-wide deadline expires, including parsing time."""
    pass


class KapValidationError(KapError):
    """Raised when a live response is structurally incomplete or unsafe to accept."""
    pass


class KapNotFoundError(KapError):
    """Raised when a requested company or announcement is not found."""
    pass


class BaseScraper:
    """Base scraper providing resilient synchronous and asynchronous HTTP requests."""

    def __init__(self, config: KapConfig | None = None) -> None:
        self.config = config or KapConfig()
        self._sync_client: httpx.Client | None = None
        self._async_client: httpx.AsyncClient | None = None
        self._async_semaphore: asyncio.Semaphore | None = None
        self.last_request_metrics: dict[str, Any] = {}

    def begin_operation(self, operation: str) -> dict[str, Any]:
        """Start a request operation and clear metrics from the previous operation."""
        self.last_request_metrics = {
            "operation_id": uuid.uuid4().hex[:16],
            "operation": operation,
            "stage": "cache_lookup",
            "attempts": 0,
        }
        return dict(self.last_request_metrics)

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

    def run_with_deadline_sync(self, func: Any, *, deadline_at: float | None) -> Any:
        """Run a parser in a daemon thread so an overlong parse cannot block the caller."""
        if deadline_at is None:
            return func()
        remaining = deadline_at - time.monotonic()
        if remaining <= 0:
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
            raise KapDeadlineExceeded("Operation deadline exceeded after parsing started")
        if "error" in result:
            raise result["error"]
        return result.get("value")

    async def run_with_deadline_async(self, func: Any, *, deadline_at: float | None) -> Any:
        """Run a synchronous parser with a hard caller-visible deadline."""
        if deadline_at is None:
            return func()
        remaining = deadline_at - time.monotonic()
        if remaining <= 0:
            raise KapDeadlineExceeded("Operation deadline exceeded before parsing")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()

        def worker() -> None:
            try:
                value = func()
                loop.call_soon_threadsafe(lambda: not future.done() and future.set_result(value))
            except BaseException as exc:
                loop.call_soon_threadsafe(lambda: not future.done() and future.set_exception(exc))

        threading.Thread(target=worker, name="kap-parse-deadline", daemon=True).start()
        try:
            return await asyncio.wait_for(future, timeout=remaining)
        except asyncio.TimeoutError as exc:
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
        deadline = deadline_at or (time.monotonic() + self.config.request_deadline_s)
        operation_started = time.perf_counter()
        metrics = self._timing_context(timing, self.last_request_metrics)
        metrics["stage"] = "request"
        for attempt in range(1, max_attempts + 1):
            metrics["attempts"] = attempt
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                metrics.update(stage="deadline", error="request deadline exceeded")
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
                    self._publish_metrics(metrics)
                    raise KapConnectionError(
                        f"Request failed after {attempt} attempts for {path_or_url}: {exc}"
                    ) from exc
                delay = self._retry_delay(None, attempt)
                logger.warning("Transient HTTP error (%s) for %s; retrying in %.2fs", exc, path_or_url, delay)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    metrics.update(stage="deadline", error="request deadline exceeded")
                    self._publish_metrics(metrics)
                    raise KapDeadlineExceeded(f"Request deadline exceeded for {path_or_url}") from exc
                time.sleep(min(delay, remaining))
                continue

            if resp.is_error:
                if not self._retryable_status(resp.status_code) or attempt >= max_attempts:
                    metrics.update(stage="http_error", status_code=resp.status_code)
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
                    self._publish_metrics(metrics)
                    raise KapDeadlineExceeded(f"Request deadline exceeded for {path_or_url}")
                time.sleep(min(delay, remaining))
                continue
            if time.monotonic() >= deadline:
                metrics.update(stage="deadline", error="request deadline exceeded")
                self._publish_metrics(metrics)
                raise KapDeadlineExceeded(f"Request deadline exceeded for {path_or_url}")
            metrics["stage"] = "http_success"
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
        deadline = deadline_at or (time.monotonic() + self.config.request_deadline_s)
        operation_started = time.perf_counter()
        metrics = self._timing_context(timing, self.last_request_metrics)
        metrics["stage"] = "request"
        for attempt in range(1, max_attempts + 1):
            metrics["attempts"] = attempt
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                metrics.update(stage="deadline", error="request deadline exceeded")
                self._publish_metrics(metrics)
                raise KapDeadlineExceeded(f"Request deadline exceeded for {path_or_url}")
            try:
                async with self._async_semaphore:
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
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= max_attempts:
                    metrics.update(stage="error", error=f"{type(exc).__name__}: {exc}")
                    self._publish_metrics(metrics)
                    raise KapConnectionError(
                        f"Request failed after {attempt} attempts for {path_or_url}: {exc}"
                    ) from exc
                delay = self._retry_delay(None, attempt)
                logger.warning("Transient async HTTP error (%s) for %s; retrying in %.2fs", exc, path_or_url, delay)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    metrics.update(stage="deadline", error="request deadline exceeded")
                    self._publish_metrics(metrics)
                    raise KapDeadlineExceeded(f"Request deadline exceeded for {path_or_url}") from exc
                await asyncio.sleep(min(delay, remaining))
                continue

            if resp.is_error:
                if not self._retryable_status(resp.status_code) or attempt >= max_attempts:
                    metrics.update(stage="http_error", status_code=resp.status_code)
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
                    self._publish_metrics(metrics)
                    raise KapDeadlineExceeded(f"Request deadline exceeded for {path_or_url}")
                await asyncio.sleep(min(delay, remaining))
                continue
            if time.monotonic() >= deadline:
                metrics.update(stage="deadline", error="request deadline exceeded")
                self._publish_metrics(metrics)
                raise KapDeadlineExceeded(f"Request deadline exceeded for {path_or_url}")
            metrics["stage"] = "http_success"
            self._publish_metrics(metrics)
            return resp

        raise KapConnectionError(f"Request failed for {path_or_url}")
