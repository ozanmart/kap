# Quickstart

## Install

KAP supports Python 3.10–3.14. For an application, install the runtime wheel:

```bash
python -m pip install kap
```

For a checkout with tests, packaging tools and MCP support:

```bash
python -m pip install "-e .[dev,mcp]"
```

The package has no browser or system-service requirement.

## First synchronous request

Use a context manager so the HTTP client, cache and SQLite handle are closed
even when a request raises:

```python
from kap import KapClient

with KapClient() as client:
    matches = client.search_companies("THYAO")
    if matches:
        print(matches[0].ticker, matches[0].name)

    latest = client.get_latest_disclosures(limit=10, ticker="THYAO")
    for disclosure in latest:
        print(disclosure.disclosure_index, disclosure.title)
```

`search_companies` uses the bundled registry unless `online=True` is passed.
The disclosure methods use the live KAP service and are cache-aware.

## Async usage

```python
import asyncio
from kap import AsyncKapClient

async def main() -> None:
    async with AsyncKapClient() as client:
        today = await client.get_today_disclosures()
        print(f"received {len(today[:20])} disclosures")

asyncio.run(main())
```

The async client uses true async HTTP and shares validation, cache keys and
models with `KapClient`. Do not call blocking sync methods from an event loop.

## Select an operating profile

```python
from kap import KapClient, KapConfig

config = KapConfig.for_profile("fast")
with KapClient(config) as client:
    data = client.get_today_disclosures()[:25]
```

Profiles are described in [configuration.md](configuration.md). In short,
`fast` makes one bounded attempt, `balanced` is the default for applications,
and `resilient` allows a larger bounded retry/deadline budget.

## Common workflows

### Company profile and taxonomy

```python
with KapClient() as client:
    company = client.get_company_general_info("BIMAS")
    indices = client.get_indices()
    sectors = client.get_sectors()
    markets = client.get_markets()
```

### Historical disclosure and event extraction

```python
with KapClient() as client:
    history = client.get_company_disclosures("KCHOL", days=180)
    detail = client.get_disclosure_detail(history[0].disclosure_index)
    event = client.extract_events(detail)
    print(event.event_type, event.confidence)
```

### Financial report selection

```python
with KapClient() as client:
    report = client.get_financials("THYAO", year=2025, period="annual")
    statement = client.get_financial_statement(report.disclosure_index)
```

The selector resolves the company member OID and chooses the matching KAP
financial disclosure. Treat the returned disclosure index as the stable link to
the source announcement.

## Cleanup and errors

`KapClient.close()` and `AsyncKapClient.aclose()` are idempotent, so they are
safe in `finally` blocks. Catch the typed exceptions from `kap.exceptions`:

```python
from kap.exceptions import KapConnectionError, KapDeadlineExceeded, KapValidationError

try:
    ...
except KapValidationError:
    ...  # fix caller input
except (KapConnectionError, KapDeadlineExceeded):
    ...  # retry at the application boundary or use cached data
```

When stale-if-error is enabled, a successful older response may be returned
with stale metadata instead of raising. Inspect `client.last_request_metrics`
and cache metadata when an audit trail needs to distinguish fresh from stale.
