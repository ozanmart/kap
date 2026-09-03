from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .constants import KAP_BASE_URL


_PROFILE_DEFAULTS = {
    "fast": {
        "timeout_s": 3.0,
        "connect_timeout_s": 0.8,
        "read_timeout_s": 2.0,
        "write_timeout_s": 2.0,
        "pool_timeout_s": 0.5,
        "request_deadline_s": 3.0,
        "max_retries": 1,
        "stale_if_error": True,
        # A short-lived agent/CLI must not leave refresh work behind.
        "stale_while_revalidate": False,
    },
    "balanced": {
        # KAP occasionally needs a longer TLS handshake on a cold connection,
        # while keeping the retry budget bounded for normal requests.
        "connect_timeout_s": 3.0,
        "max_retries": 3,
    },
    "resilient": {
        "timeout_s": 30.0,
        "connect_timeout_s": 5.0,
        "read_timeout_s": 25.0,
        "write_timeout_s": 10.0,
        "pool_timeout_s": 3.0,
        "request_deadline_s": 30.0,
        "max_retries": 4,
        "stale_if_error": True,
        "stale_while_revalidate": True,
    },
}


def _default_cache_dir() -> Path:
    """Use an OS cache directory so Desktop/iCloud projects do not hydrate DB files."""
    configured = os.environ.get("XDG_CACHE_HOME")
    if configured:
        return Path(configured) / "kap"
    return Path.home() / ".cache" / "kap"


class KapConfig(BaseModel):
    """Configuration options for the KAP SDK."""

    profile: Literal["fast", "balanced", "resilient"] = Field(
        default="balanced",
        description="Agent/network profile controlling retries, deadlines and stale-cache behavior",
    )

    base_url: str = Field(default=KAP_BASE_URL, description="Root URL of KAP website")
    lang: str = Field(default="tr", description="Language code for requests (e.g. 'tr' or 'en')")
    timeout_s: float = Field(default=20.0, gt=0, description="Per-attempt ceiling; operation deadlines remain authoritative")
    connect_timeout_s: float = Field(default=1.5, gt=0, description="HTTP connection timeout in seconds")
    read_timeout_s: float = Field(default=18.0, gt=0, description="HTTP response read timeout in seconds")
    write_timeout_s: float = Field(default=5.0, gt=0, description="HTTP request write timeout in seconds")
    pool_timeout_s: float = Field(default=1.5, gt=0, description="HTTP connection-pool wait timeout in seconds")
    request_deadline_s: float = Field(default=20.0, gt=0, description="Total deadline including fetch, retries, backoff and parsing")
    max_retries: int = Field(default=2, ge=1, le=8, description="Maximum total attempts on transient network errors")
    max_concurrency: int = Field(default=8, ge=1, le=128, description="Maximum concurrent async HTTP requests")
    enable_cache: bool = Field(default=True, description="Enable local response caching")
    cache_dir: Path = Field(
        default_factory=_default_cache_dir,
        description="Directory for persistent disk cache (outside iCloud by default)",
    )
    cache_expiry_default: int = Field(default=3600, ge=0, description="Default cache TTL in seconds (1 hour)")
    cache_expiry_companies: int = Field(default=86400 * 3, ge=0, description="Company list cache TTL (3 days)")
    cache_expiry_indices: int = Field(default=86400, ge=0, description="Indices cache TTL (1 day)")
    cache_expiry_sectors: int = Field(default=86400, ge=0, description="Sectors cache TTL (1 day)")
    cache_expiry_markets: int = Field(default=86400, ge=0, description="Trading market taxonomy cache TTL (1 day)")
    cache_expiry_financials: int = Field(default=86400 * 7, ge=0, description="Financial statements cache TTL (7 days)")
    cache_expiry_latest: int = Field(default=20, ge=0, description="Latest disclosure cache TTL (seconds)")
    cache_expiry_today: int = Field(default=30, ge=0, description="Today disclosure cache TTL (seconds)")
    cache_expiry_calendar: int = Field(default=3600, ge=0, description="Expected disclosure calendar cache TTL (1 hour)")
    cache_expiry_company_general: int = Field(default=86400 * 2, ge=0, description="Company profile cache TTL (2 days)")
    cache_expiry_disclosure_detail: int = Field(default=86400 * 30, ge=0, description="Immutable disclosure detail cache TTL (30 days)")
    parser_schema_version: str = Field(default="2", description="Cache namespace version for parser/model changes")
    stale_if_error: bool = Field(default=True, description="Return the last successful response when refresh fails")
    stale_while_revalidate: bool = Field(default=True, description="Refresh stale responses in a bounded background worker")
    stale_max_age_s: int = Field(default=86400 * 30, ge=0, description="How long an old successful value may be used as stale fallback")
    registry_min_records: int = Field(default=800, ge=1, description="Minimum ticker records required before accepting a live company registry")
    registry_require_company_ids: bool = Field(default=True, description="Require MKK member OIDs in accepted live registry rows")

    def __init__(self, **data: object) -> None:
        profile = str(data.get("profile", "balanced"))
        if profile not in _PROFILE_DEFAULTS:
            raise ValueError(f"Unknown KAP profile: {profile}")
        for key, value in _PROFILE_DEFAULTS[profile].items():
            data.setdefault(key, value)
        super().__init__(**data)

    @classmethod
    def for_profile(cls, profile: Literal["fast", "balanced", "resilient"], **overrides: object) -> "KapConfig":
        """Create a config with an explicit agent/network profile."""
        return cls(profile=profile, **overrides)
