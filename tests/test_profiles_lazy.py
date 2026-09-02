from __future__ import annotations

import asyncio
import subprocess
import sys
import threading
import time

from kap.cache import CacheManager
from kap.config import KapConfig


def test_agent_profiles_have_explicit_retry_and_deadline_contracts() -> None:
    fast = KapConfig(profile="fast")
    balanced = KapConfig(profile="balanced")
    resilient = KapConfig(profile="resilient")

    assert fast.max_retries == 1
    assert fast.request_deadline_s < balanced.request_deadline_s < resilient.request_deadline_s
    assert fast.stale_if_error is True
    assert fast.stale_while_revalidate is False
    assert resilient.max_retries > balanced.max_retries


def test_stale_while_revalidate_returns_old_value_and_refreshes(tmp_path) -> None:
    cache = CacheManager(cache_dir=tmp_path, enabled=True, use_disk=False, stale_retention_s=30)
    try:
        cache.set("item", "old", expire=60)
        cache._memory._store["item"] = (time.time() - 1, "old")
        refreshed = []
        done = threading.Event()

        def refresh() -> str:
            refreshed.append(True)
            done.set()
            return "new"

        assert cache.cached_call("item", refresh, expire=60) == "old"
        assert done.wait(2)
        assert refreshed == [True]
        assert cache._memory.get("item") == "new"
    finally:
        cache.close()


def test_force_refresh_bypasses_fresh_and_stale_values(tmp_path) -> None:
    cache = CacheManager(cache_dir=tmp_path, enabled=True, use_disk=False, stale_retention_s=30)
    try:
        cache.set("item", "old", expire=60)
        cache._memory._store["item"] = (time.time() - 1, "old")
        assert cache.cached_call("item", lambda: "new", expire=60, force_refresh=True) == "new"
        assert cache._memory.get("item") == "new"
    finally:
        cache.close()


def test_async_stale_while_revalidate_returns_old_value_and_refreshes(tmp_path) -> None:
    async def run() -> None:
        cache = CacheManager(cache_dir=tmp_path, enabled=True, use_disk=False, stale_retention_s=30)
        try:
            cache.set("item", "old", expire=60)
            cache._memory._store["item"] = (time.time() - 1, "old")
            done = asyncio.Event()

            async def refresh() -> str:
                done.set()
                return "new"

            assert await cache.cached_call_async("item", refresh, expire=60) == "old"
            await asyncio.wait_for(done.wait(), timeout=1)
            assert cache._memory.get("item") == "new"
        finally:
            cache.close()

    asyncio.run(run())


def test_daemon_swr_refresh_does_not_hold_short_lived_process_open() -> None:
    code = """
import time
from kap.cache import CacheManager
cache = CacheManager(enabled=True, use_disk=False, stale_retention_s=60)
cache.set('item', 'old', expire=60)
cache._memory._store['item'] = (time.time() - 1, 'old')
def refresh():
    time.sleep(1.5)
    return 'new'
assert cache.cached_call('item', refresh, expire=60) == 'old'
cache.close()
"""
    started = time.monotonic()
    subprocess.check_call([sys.executable, "-c", code])
    assert time.monotonic() - started < 1.0


def test_importing_kap_and_constructing_client_stays_on_lightweight_path() -> None:
    source_root = str(__file__).replace("/tests/test_profiles_lazy.py", "") + "/src"
    code = (
        "import sys; import kap; from kap.client import KapClient; from kap.async_client import AsyncKapClient; "
        "c=KapClient(); a=AsyncKapClient(); "
        "print([x for x in ('kap.storage.sqlite','kap.tools.mcp_server','kap.models.financials','kap.scrapers.financials') if x in sys.modules]); c.close(); a.cache.close()"
    )
    output = subprocess.check_output(
        [sys.executable, "-c", code],
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": source_root},
    ).strip()
    assert output == "[]"
