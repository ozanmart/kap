from __future__ import annotations

import asyncio
import logging
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

try:
    import diskcache
except ImportError:
    diskcache = None

logger = logging.getLogger("kap.cache")
T = TypeVar("T")


class InMemoryCache:
    """Fallback in-memory cache with TTL support when diskcache is not present."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.RLock()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key not in self._store:
                return default
            expiry, val = self._store[key]
            if expiry > 0 and time.time() > expiry:
                del self._store[key]
                return default
            return val

    def set(self, key: str, value: Any, expire: int | None = None) -> None:
        with self._lock:
            expiry = (time.time() + expire) if expire else 0.0
            self._store[key] = (expiry, value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


class CacheManager:
    """Manages high-speed in-memory and disk caching."""

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        enabled: bool = True,
        use_disk: bool = True,
        stale_retention_s: int = 86400 * 30,
        stale_if_error: bool = True,
        stale_while_revalidate: bool = True,
    ) -> None:
        self.enabled = enabled
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.stale_retention_s = max(0, int(stale_retention_s))
        self.stale_if_error = stale_if_error
        self.stale_while_revalidate = stale_while_revalidate
        self._memory = InMemoryCache()
        self._disk: Any = None
        self.last_metadata: dict[str, Any] = {}
        self._refresh_lock = threading.Lock()
        self._refreshing: set[str] = set()
        self._async_refreshes: set[asyncio.Task[None]] = set()
        self._closed = False

        if self.enabled and use_disk and self.cache_dir and diskcache is not None:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                self._disk = diskcache.Cache(str(self.cache_dir))
            except Exception as exc:
                logger.debug("Could not initialize disk cache at %s: %s", self.cache_dir, exc)
                self._disk = None

    def get(self, key: str, default: Any = None) -> Any:
        if not self.enabled:
            self.last_metadata = {}
            return default
        val = self._memory.get(key)
        if val is not None:
            self.last_metadata = self._memory.get(self._metadata_key(key), {}) or {}
            return val
        if self._disk is not None:
            try:
                disk_val, expires_at = self._disk.get(key, default, expire_time=True)
                if disk_val is not None:
                    ttl = None
                    if expires_at:
                        ttl = max(1, int(expires_at - time.time()))
                    self._memory.set(key, disk_val, expire=ttl)
                    metadata = self._disk.get(self._metadata_key(key), {}) or {}
                    self._memory.set(self._metadata_key(key), metadata, expire=ttl)
                    self.last_metadata = metadata
                else:
                    self.last_metadata = {}
                return disk_val
            except Exception as exc:
                logger.debug("Could not read disk cache entry %s: %s", key, exc)
                self.last_metadata = {}
                return default
        self.last_metadata = {}
        return default

    def set(self, key: str, value: Any, expire: int | None = None) -> None:
        if not self.enabled:
            return
        metadata = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "stale": False,
            "warnings": [],
        }
        self.last_metadata = metadata
        self._memory.set(key, value, expire=expire)
        self._memory.set(self._metadata_key(key), metadata, expire=expire)
        if self.stale_retention_s:
            stale_expire = max(self.stale_retention_s, int(expire or 0))
            self._memory.set(self._stale_key(key), value, expire=stale_expire)
            self._memory.set(self._stale_metadata_key(key), metadata, expire=stale_expire)
        if self._disk is not None:
            try:
                self._disk.set(key, value, expire=expire)
                self._disk.set(self._metadata_key(key), metadata, expire=expire)
                if self.stale_retention_s:
                    self._disk.set(self._stale_key(key), value, expire=stale_expire)
                    self._disk.set(self._stale_metadata_key(key), metadata, expire=stale_expire)
            except Exception as exc:
                logger.debug("Could not write disk cache entry %s: %s", key, exc)

    @staticmethod
    def _metadata_key(key: str) -> str:
        return f"__kap_metadata__:{key}"

    @staticmethod
    def _stale_key(key: str) -> str:
        return f"__kap_stale__:{key}"

    @classmethod
    def _stale_metadata_key(cls, key: str) -> str:
        return cls._metadata_key(cls._stale_key(key))

    def get_stale(self, key: str, default: Any = None) -> Any:
        """Return the last successful value retained after its fresh TTL expired."""
        if not self.enabled:
            return default
        stale_key = self._stale_key(key)
        val = self._memory.get(stale_key)
        if val is not None:
            metadata = self._memory.get(self._stale_metadata_key(key), {}) or {}
            self.last_metadata = {**metadata, "stale": True}
            return val
        if self._disk is not None:
            try:
                disk_val, expires_at = self._disk.get(stale_key, default, expire_time=True)
                if disk_val is not None:
                    ttl = max(1, int(expires_at - time.time())) if expires_at else None
                    self._memory.set(stale_key, disk_val, expire=ttl)
                    metadata = self._disk.get(self._stale_metadata_key(key), {}) or {}
                    self._memory.set(self._stale_metadata_key(key), metadata, expire=ttl)
                    self.last_metadata = {**metadata, "stale": True}
                return disk_val
            except Exception as exc:
                logger.debug("Could not read stale disk cache entry %s: %s", key, exc)
                return default
        return default

    def _schedule_revalidation(
        self,
        key: str,
        func: Callable[[], T],
        expire: int | None,
    ) -> None:
        with self._refresh_lock:
            if self._closed or key in self._refreshing:
                return
            self._refreshing.add(key)

        def refresh() -> None:
            try:
                if self._closed:
                    return
                result = func()
                if self.enabled and not self._closed and result is not None:
                    self.set(key, result, expire=expire)
            except Exception as exc:
                logger.debug("Stale cache revalidation failed for %s: %s", key, exc)
            finally:
                with self._refresh_lock:
                    self._refreshing.discard(key)

        # ThreadPoolExecutor uses non-daemon workers and consequently makes a
        # short-lived CLI wait for a slow refresh during interpreter shutdown.
        # A stale response is specifically allowed to outlive its caller.
        threading.Thread(
            target=refresh,
            name=f"kap-cache-refresh-{len(self._refreshing)}",
            daemon=True,
        ).start()

    def _mark_stale(self, warning: str) -> None:
        metadata = dict(self.last_metadata)
        metadata["stale"] = True
        warnings = list(metadata.get("warnings", []))
        if warning not in warnings:
            warnings.append(warning)
        metadata["warnings"] = warnings
        self.last_metadata = metadata

    def clear(self) -> None:
        self._memory.clear()
        self.last_metadata = {}
        if self._disk is not None:
            try:
                self._disk.clear()
            except Exception as exc:
                logger.debug("Could not clear disk cache: %s", exc)

    def close(self) -> None:
        """Close the persistent cache handle, if one is open."""
        with self._refresh_lock:
            self._closed = True
        if self._disk is not None:
            try:
                self._disk.close()
            except Exception as exc:
                logger.debug("Could not close disk cache: %s", exc)
            self._disk = None

    def cached_call(
        self,
        key: str,
        func: Callable[[], T],
        expire: int | None = None,
        force_refresh: bool = False,
        stale_if_error: bool | None = None,
        stale_while_revalidate: bool | None = None,
        refresh_async: bool = False,
    ) -> T:
        """Fetch a value with explicit force-refresh and stale-cache semantics."""
        use_stale_if_error = self.stale_if_error if stale_if_error is None else stale_if_error
        use_swr = self.stale_while_revalidate if stale_while_revalidate is None else stale_while_revalidate
        if not force_refresh and self.enabled:
            val = self.get(key)
            if val is not None:
                return val

        stale = self.get_stale(key) if self.enabled else None
        if stale is not None and not force_refresh and (refresh_async or use_swr):
            self._schedule_revalidation(key, func, expire)
            self._mark_stale("stale_cache_served; refresh scheduled")
            return stale

        try:
            result = func()
        except Exception as exc:
            if stale is not None and not force_refresh and use_stale_if_error:
                self._mark_stale(f"live_refresh_failed: {type(exc).__name__}")
                return stale
            raise
        if self.enabled and result is not None:
            self.set(key, result, expire=expire)
        return result

    async def cached_call_async(
        self,
        key: str,
        func: Callable[[], Any],
        expire: int | None = None,
        force_refresh: bool = False,
        stale_if_error: bool | None = None,
        stale_while_revalidate: bool | None = None,
        refresh_async: bool = False,
    ) -> Any:
        """Async equivalent of cached_call with stale fallback and SWR."""
        use_stale_if_error = self.stale_if_error if stale_if_error is None else stale_if_error
        use_swr = self.stale_while_revalidate if stale_while_revalidate is None else stale_while_revalidate
        if not force_refresh and self.enabled:
            value = self.get(key)
            if value is not None:
                return value

        stale = self.get_stale(key) if self.enabled else None
        if stale is not None and not force_refresh and (refresh_async or use_swr):
            async def refresh() -> None:
                try:
                    result = await func()
                    if self.enabled and not self._closed and result is not None:
                        self.set(key, result, expire=expire)
                except Exception as exc:
                    logger.debug("Async stale cache revalidation failed for %s: %s", key, exc)

            # A bare create_task is only weakly referenced by the loop, so the
            # revalidation can be garbage collected mid-flight. Hold it until it
            # finishes, mirroring the daemon thread the sync path owns.
            task = asyncio.create_task(refresh())
            self._async_refreshes.add(task)
            task.add_done_callback(self._async_refreshes.discard)
            self._mark_stale("stale_cache_served; refresh scheduled")
            return stale

        try:
            result = await func()
        except Exception as exc:
            if stale is not None and not force_refresh and use_stale_if_error:
                self._mark_stale(f"live_refresh_failed: {type(exc).__name__}")
                return stale
            raise
        if self.enabled and result is not None:
            self.set(key, result, expire=expire)
        return result
