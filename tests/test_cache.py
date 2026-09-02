from __future__ import annotations

from kap.cache import CacheManager


def test_disk_cache_persists_between_managers(tmp_path):
    cache_dir = tmp_path / "kap-cache"
    first = CacheManager(cache_dir=cache_dir, enabled=True)
    assert first._disk is not None
    first.set("payload", {"value": 42}, expire=60)
    first.close()

    second = CacheManager(cache_dir=cache_dir, enabled=True)
    try:
        assert second.get("payload") == {"value": 42}
        assert second._memory.get("payload") == {"value": 42}
    finally:
        second.close()


def test_disk_cache_honors_expiry_when_promoted_to_memory(tmp_path):
    cache_dir = tmp_path / "kap-cache-expiry"
    first = CacheManager(cache_dir=cache_dir, enabled=True)
    first.set("expired", "old", expire=1)
    first.close()

    second = CacheManager(cache_dir=cache_dir, enabled=True)
    try:
        assert second.get("expired") == "old"
        assert second._memory.get("expired") == "old"
    finally:
        second.close()


def test_cache_records_fetch_metadata(tmp_path):
    cache = CacheManager(cache_dir=tmp_path / "metadata", enabled=True)
    try:
        cache.set("payload", {"ok": True}, expire=60)
        assert cache.last_metadata["fetched_at"]
        assert cache.last_metadata["stale"] is False
        assert cache.get("payload") == {"ok": True}
        assert cache.last_metadata["fetched_at"]
    finally:
        cache.close()
