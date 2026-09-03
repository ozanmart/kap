from __future__ import annotations

from kap.cache import CacheManager
from kap.client import _cache_key
from kap.config import KapConfig


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


def test_cache_hit_does_not_call_live_loader(tmp_path):
    cache = CacheManager(cache_dir=tmp_path / "no-network", enabled=True)
    try:
        cache.set("payload", {"value": 42}, expire=60)

        def unexpected_live_call():
            raise AssertionError("cache hit attempted a network refresh")

        assert cache.cached_call("payload", unexpected_live_call, expire=60) == {"value": 42}
    finally:
        cache.close()


def test_corrupt_disk_cache_falls_back_and_recovers_in_memory(tmp_path):
    class BrokenDisk:
        def get(self, *_args, **_kwargs):
            raise OSError("corrupt cache")

        def set(self, *_args, **_kwargs):
            raise OSError("corrupt cache")

        def close(self):
            pass

    cache = CacheManager(cache_dir=tmp_path / "corrupt", enabled=True)
    cache._disk = BrokenDisk()
    try:
        assert cache.cached_call("payload", lambda: "fresh", expire=60) == "fresh"
        assert cache.get("payload") == "fresh"
    finally:
        cache.close()


def test_parser_schema_version_invalidates_cache_keys():
    old = KapConfig(parser_schema_version="1")
    new = KapConfig(parser_schema_version="2")

    assert _cache_key(old, "detail", disclosure_index=1) != _cache_key(
        new,
        "detail",
        disclosure_index=1,
    )
