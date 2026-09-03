# Configuration

`KapConfig` is the single place for network, cache, persistence and parser
policy. Pass one instance to either client:

```python
from kap import KapClient, KapConfig

config = KapConfig.for_profile(
    "balanced",
    cache_dir="/var/tmp/my-kap-cache",
    cache_expiry_today=30,
)
with KapClient(config) as client:
    ...
```

## Profiles

| Profile | Intended use | Total attempts | Stale-while-revalidate |
| --- | --- | ---: | --- |
| `fast` | Short-lived CLI/agent calls | 1 | No |
| `balanced` | Default application behavior | 3 | Yes |
| `resilient` | Background jobs and slower networks | 4 | Yes |

`max_retries` is the maximum total attempt count, including the first attempt.
Every profile has bounded per-attempt timeouts and an overall
`request_deadline_s`; backoff cannot extend that deadline.

## Timeouts and concurrency

The timeout fields are `timeout_s`, `connect_timeout_s`, `read_timeout_s`,
`write_timeout_s` and `pool_timeout_s`. `max_concurrency` (default `8`) bounds
simultaneous async HTTP requests via an internal semaphore. Keep the deadline
larger than the expected connect/read budget when overriding profile defaults.

KAP is a free public service with no API key and no published rate limit.
`max_concurrency` is the SDK's only built-in politeness control; both HTTP
clients also reuse one pooled connection (HTTP/1.1, upgrading to HTTP/2 when
the origin offers it) instead of opening one per request. Raise
`max_concurrency` only for jobs that genuinely need the throughput, and prefer
caching (below) over repeated live requests for anything read more than once.

## Cache semantics

Caching is enabled by default and uses an in-memory layer backed by `diskcache`
when installed. `cache_dir` defaults to the OS cache directory (for example
`~/.cache/kap` on macOS/Linux); `XDG_CACHE_HOME` can override its parent.

- Fresh entries are returned without a network request.
- Stale entries are retained for `stale_max_age_s` and may be returned when a
  refresh fails (`stale_if_error=True`).
- `stale_while_revalidate=True` schedules one bounded background refresh for a
  stale key; use `fast` when the process must exit immediately.
- `force_refresh=True` bypasses fresh and stale entries and waits for live data.
- `refresh_async=True` explicitly requests stale-while-revalidate on supported
  methods.
- Set `enable_cache=False` for deterministic no-cache calls.

Per-resource TTL fields include `cache_expiry_companies`, `cache_expiry_indices`,
`cache_expiry_sectors`, `cache_expiry_markets`, `cache_expiry_financials`,
`cache_expiry_latest`, `cache_expiry_today`, `cache_expiry_calendar`,
`cache_expiry_company_general` and `cache_expiry_disclosure_detail`.

## Persistence

The embedded SQLite database is available through `client.db` for local query
and history use. It is closed with the client and `close()` is idempotent.

## Registry safety

Live registry refresh is accepted only when it passes minimum row count, ticker
format/uniqueness and valid 32-character MKK member OID checks. Configure
`registry_min_records` and `registry_require_company_ids` only when you own the
operational consequences of changing these safety gates.
