# KAP

Production-grade Python SDK and agent toolkit for the public [Kamuyu Aydınlatma Platformu (KAP)](https://www.kap.org.tr/) and Borsa Istanbul (BIST).

KAP gives applications and AI agents a typed, testable way to discover BIST companies, read public disclosures, select financial reports, inspect market taxonomy, and extract structured corporate events—without a headless browser or an MKK dependency.

## Capabilities

| Area | What you can do |
| --- | --- |
| Company discovery | Search 800+ BIST companies by ticker or name; retrieve ownership, free-float, subsidiaries, auditor, market and sector data. |
| Disclosures | Browse today’s complete Europe/Istanbul calendar-day feed, latest announcements, historical company disclosures, normalized type/class metadata and attachments. |
| Financials | Select the correct KAP financial disclosure by ticker, year and period; parse balance sheet, income statement and cash-flow statements. |
| Market data | List BIST indices and constituents, sectors, trading markets and the expected earnings/disclosure calendar. |
| Corporate events | Extract buybacks, dividends, capital increases, guidance and other events from disclosure text. |
| Agents and MCP | Export OpenAI and Anthropic tool schemas, or run the built-in MCP server over stdio for Claude Desktop, Cursor and compatible clients. |
| Reliability | Sync and async clients, bounded retries/deadlines, typed exceptions, stale-if-error caching, SQLite persistence and request metrics. |
| Offline-first | Use the bundled BIST registry instantly; live registry refreshes are validated before replacing the snapshot. |

## Why KAP

- Pure Python over public KAP endpoints; no browser automation and no MKK REST calls.
- A small public surface (`KapClient`, `AsyncKapClient`, `KapToolkit`) backed by focused scraper components and stable Pydantic models.
- Fast local lookups with optional live refresh, while stale data remains available during transient outages.
- The same client methods power the Python API, CLI, agent tools and MCP adapter, keeping behavior consistent.

## Installation

Runtime:

```bash
python -m pip install kap
```

From a checkout, including development and MCP dependencies:

```bash
python -m pip install "-e .[dev,mcp]"
```

The package supports Python 3.10–3.14. See [docs/quickstart.md](docs/quickstart.md) for environment setup and the first request.

## 30-second example

```python
from kap import KapClient

with KapClient() as client:
    companies = client.search_companies("THYAO")
    print(companies[0].name)

    disclosures = client.get_latest_disclosures(limit=10, ticker="THYAO")
    for item in disclosures:
        print(item.publish_date, item.title)
```

Async code uses the equivalent `AsyncKapClient` methods:

```python
import asyncio
from kap import AsyncKapClient

async def main():
    async with AsyncKapClient() as client:
        today = await client.get_today_disclosures()
        print(len(today[:20]))

asyncio.run(main())
```

## Agent and MCP usage

```python
from kap.tools import KapToolkit

toolkit = KapToolkit(profile="balanced")
tools = toolkit.get_openai_tools()
result = toolkit.execute_tool("kap_search_companies", {"query": "ASELS"})
```

Start the stdio MCP server; it speaks JSON-RPC over stdio with no extra
dependency:

```bash
kap mcp
```

See [docs/agents-and-mcp.md](docs/agents-and-mcp.md) for Claude Desktop configuration, schemas, pagination and output semantics.

## CLI

The `kap` command exposes the same operations for scripts and shell workflows:

```bash
kap --help
kap --version
kap search THYAO
kap search THYAO --online
kap info BIMAS
kap today
kap today --member-type bist_sirketleri --json-out
kap latest --limit 20 --ticker GARAN
kap disclosures KCHOL --type FR --days 180
kap disclosures KCHOL --type FR --days 180 --limit 20
kap detail 1657514 --max-chars 4000
kap detail 1657514 --max-chars 4000 --json-out
kap financials THYAO --year 2025 --period annual
kap financials THYAO --year 2025 --period annual --json-out
kap statement 1657514
kap calendar --days 90
kap calendar --days 90 --ticker THYAO
kap taxonomy indices
kap taxonomy indices --json-out
kap taxonomy sectors
kap taxonomy markets
kap events 1657514
kap mcp
```

`--json-out` is available on `today`, `detail`, `financials` and `taxonomy`.
Use `kap --help` and [docs/cli.md](docs/cli.md) for the complete option matrix.

## Reliability and data semantics

`KapConfig.for_profile("fast" | "balanced" | "resilient")` selects the retry and deadline contract. The default is `balanced`. Cache entries can be fresh or stale; `force_refresh=True` bypasses both, while `refresh_async=True` requests stale-while-revalidate. Public failures are raised through `kap.exceptions` (`KapConnectionError`, `KapDeadlineExceeded`, `KapValidationError`, `KapNotFoundError`).

For configuration details, cache behavior, persistence and environment variables, read [docs/configuration.md](docs/configuration.md). For data-model and API coverage, read [docs/data-and-api.md](docs/data-and-api.md).

## Architecture

The repository is organized into clients, scraper components, models, cache/storage, and thin CLI/agent/MCP adapters. Components are loaded lazily so offline registry lookups do not initialize unrelated network or parser modules. Sync and async clients share validation, caching semantics and data contracts.

The full request lifecycle, extension points and design decisions are documented in [docs/architecture.md](docs/architecture.md).

## Development and release checks

```bash
python -m compileall -q src tests
python -m pytest -q
python -m build --no-isolation --wheel --sdist
```

CI tests both the source tree and the installed wheel on Python 3.10–3.14. The release gate and benchmark methodology are described in [docs/testing-and-release.md](docs/testing-and-release.md); generated benchmark output is intentionally kept out of version control.

## Documentation map

- [Quickstart](docs/quickstart.md) — installation, sync/async examples and first workflows.
- [Architecture](docs/architecture.md) — layers, request flow, caching and extension points.
- [Data and API](docs/data-and-api.md) — clients, models, operations and exceptions.
- [Configuration](docs/configuration.md) — profiles, timeouts, retries, cache and persistence.
- [CLI](docs/cli.md) — command reference and scripting patterns.
- [Agents and MCP](docs/agents-and-mcp.md) — tool schemas, MCP stdio and agent-safe outputs.
- [Testing and release](docs/testing-and-release.md) — tests, live gate, packaging and release checklist.
- [Contributing](CONTRIBUTING.md) and [Security](SECURITY.md).

## License

KAP is distributed under the [MIT License](LICENSE). Review [PROVENANCE_AUDIT.md](PROVENANCE_AUDIT.md) before redistributing adapted or reused material; the audit records scope and evidence, but does not replace legal provenance confirmation.
