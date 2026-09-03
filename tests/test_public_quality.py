from __future__ import annotations

import asyncio
import datetime

import pytest

from kap.async_client import AsyncKapClient
from kap.client import KapClient
from kap.config import KapConfig
from kap.constants import SUBJECT_OID_FINANCIAL_REPORT
from kap.exceptions import KapValidationError
from kap.scrapers.base import KapValidationError as LegacyKapValidationError
from kap.storage.sqlite import KapDatabase


def test_public_exceptions_keep_legacy_import_compatibility() -> None:
    assert KapValidationError is LegacyKapValidationError


def test_historical_client_uses_financial_report_subject_by_default() -> None:
    captured: dict[str, object] = {}
    with KapClient(KapConfig(enable_cache=False)) as client:
        client._resolve_member_oid = lambda value: "member-oid"  # type: ignore[method-assign]

        def fetch(**kwargs):
            captured.update(kwargs)
            return []

        client.disclosures.get_historical_disclosures_by_criteria = fetch  # type: ignore[method-assign]
        assert client.get_historical_disclosures("THYAO") == []

    assert captured["subject_oid"] == SUBJECT_OID_FINANCIAL_REPORT


def test_async_historical_client_uses_financial_report_subject_by_default() -> None:
    async def run() -> dict[str, object]:
        captured: dict[str, object] = {}
        async with AsyncKapClient(KapConfig(enable_cache=False)) as client:
            async def resolve(_value: str) -> str:
                return "member-oid"

            client._resolve_member_oid = resolve  # type: ignore[method-assign]

            async def fetch(**kwargs):
                captured.update(kwargs)
                return []

            client.disclosures.aget_historical_disclosures_by_criteria = fetch  # type: ignore[method-assign]
            assert await client.get_historical_disclosures("THYAO") == []
        return captured

    captured = asyncio.run(run())
    assert captured["subject_oid"] == SUBJECT_OID_FINANCIAL_REPORT


def test_public_client_rejects_invalid_arguments_before_network() -> None:
    with KapClient(KapConfig(enable_cache=False)) as client:
        with pytest.raises(KapValidationError, match="query must be a non-empty string"):
            client.search_companies("   ")
        with pytest.raises(KapValidationError, match="limit must be greater than zero"):
            client.get_latest_disclosures(limit=0)
        with pytest.raises(KapValidationError, match="from_date cannot be later"):
            client.get_historical_disclosures(
                "THYAO",
                from_date=datetime.date(2026, 1, 2),
                to_date=datetime.date(2026, 1, 1),
            )


def test_sync_and_async_market_ttls_are_explicit() -> None:
    config = KapConfig(cache_expiry_markets=123)
    assert config.cache_expiry_markets == 123

    async def run() -> None:
        async with AsyncKapClient(config) as client:
            assert client.config.cache_expiry_markets == 123

    asyncio.run(run())


def test_config_rejects_non_positive_network_timeout() -> None:
    with pytest.raises(ValueError):
        KapConfig(timeout_s=0)


def test_database_close_is_idempotent() -> None:
    db = KapDatabase(":memory:")
    db.close()
    db.close()
