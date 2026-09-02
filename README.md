# KAP: Agent-Native Python SDK & Toolkit

A fast, resilient, and agent-native Python toolkit for **KAP (Kamuyu Aydınlatma Platformu)** and **Borsa Istanbul (BIST)**.

Synthesizes the best capabilities across existing implementations with:
- **Zero Headless Browsers**: 100% pure Python using `httpx` + Next.js SSR stream decoders + fast HTML table/JSON parsing.
- **Agent-Native First**: Built-in **Model Context Protocol (MCP)** server, Pydantic tool schemas for OpenAI, Anthropic Claude, Gemini, LangChain, and CrewAI.
- **Dual Sync & Async Interfaces**: Complete support for both `KapClient` and `AsyncKapClient`.
- **Comprehensive Coverage**: Companies, indices, sectors, markets, corporate governance & ownership structure (shareholders >=5%, free float, subsidiaries), real-time & historical disclosures, financial statements, earnings calendars, and NLP corporate event extraction.
- **Multi-Tier Caching & Persistence**: Bundled offline snapshot of 750+ BIST companies for sub-millisecond lookups + persistent disk cache + embedded SQLite database.

---

## 📦 Installation

This project is developed and run through the repository-local `.venv` path.
On macOS, keep the real environment outside Desktop/iCloud and expose it at
`.venv` so imports and package metadata are not subject to iCloud file
hydration:

```bash
# macOS / Linux
python3.13 -m venv ~/.cache/kap/venv   # only needed once
ln -s ~/.cache/kap/venv .venv          # only needed once
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install ".[dev,mcp]"
```

After activation, verify that the shell is using the project environment:

```bash
which python
python --version
python -m pip show kap
```

The first path should resolve to the project’s `.venv/bin/python` (or its
iCloud-safe target). In a shell where activation is not persistent, use the
explicit `.venv/bin/` executables instead, for example `.venv/bin/python -m
pytest -q` and `.venv/bin/kap --help`.

The `.venv` entry may be a symlink; its target should be a Python 3.13
environment outside iCloud. The current checked workspace uses
`/Users/omerozanmart/.cache/kap/venv`.

Do not install project dependencies into the system Python. The `.venv/` directory is intentionally ignored by Git.

### Runtime-only installation

For an environment without test tooling or the optional MCP package:

```bash
python -m pip install .
```

For development and MCP support:

```bash
python -m pip install ".[dev,mcp]"
```

The normal install builds/installs a wheel, so runtime imports do not depend on
an editable-install `.pth` file. Use `python -m pip install -e ".[dev,mcp]"`
only when actively modifying source files.

### Agent/network profiles and stale data

Use `fast`, `balanced` (default), or `resilient` to select the retry and
operation-deadline contract. All profiles retain the last successful response;
`fast` makes one live attempt and uses stale-if-error without starting
background work, so a short-lived CLI/agent process can exit immediately.
`balanced` and `resilient` may serve stale data immediately and schedule one
daemon refresh.

```python
from kap import KapConfig, KapClient

with KapClient(KapConfig.for_profile("fast")) as client:
    latest = client.get_latest_disclosures(limit=10)

with KapClient(KapConfig(profile="resilient")) as client:
    companies = client.get_companies(online=True)
    print(client.last_request_metrics)  # fetch/TTFB/download/parse/total seconds

```

`force_refresh=True` bypasses both fresh and stale cache entries and waits for
the live result. To explicitly request stale-while-revalidate, use
`refresh_async=True` on the cache-aware client methods. Every operation
publishes its own `operation_id`, stage, attempts, and timing metadata.

For Agent tool calling, pass the same profile to `KapToolkit(profile="fast")`.
The live registry is accepted only after ticker format, uniqueness, minimum
row count, and valid MKK member OID checks. `import kap` and constructing a
client are lazy; SQLite, MCP, and unrelated financial/event modules are not
loaded on the lightweight ticker/feed path.

The optional XLS backend is disabled by default and has no pandas dependency:

```python
from kap import KapClient, KapConfig

with KapClient(KapConfig(enable_xls=True)) as client:
    report = client.download_financial_report_xls("THYAO", year=2024)
```

---

## 🚀 Quickstart

### 1. Synchronous Client

```python
from kap import KapClient

with KapClient() as client:
    # 1. Search companies (fast bundled offline index or live)
    companies = client.search_companies("THYAO")
    print(companies[0].name)  # TÜRK HAVA YOLLARI A.O.

    # 2. Get detailed company profile (shareholders, float, subsidiaries)
    info = client.get_company_general_info("BIMAS")
    print("Market:", info.market)
    print("Major Shareholders:", [(s.name_or_title, s.share_ratio) for s in info.major_shareholders])
    print("Subsidiaries:", [sub.company_title for sub in info.subsidiaries])

    # 3. Get today's live disclosures
    today_disclosures = client.get_today_disclosures()
    for d in today_disclosures[:5]:
        print(f"[{d.stock_code}] {d.title} (#{d.disclosure_index})")

    # 4. Expected forward-looking earnings calendar
    calendar = client.get_expected_disclosures(days_ahead=60)
    for event in calendar[:5]:
        print(f"[{event.stock_code}] {event.subject} ({event.start_date} -> {event.end_date})")

    # 5. Extract corporate events from disclosure text (buybacks, dividends, etc.)
    detail = client.get_disclosure_detail(disclosure_index=123456)
    event = client.extract_events(disclosure_detail=detail)
    print("Detected Event:", event.event_type, "Confidence:", event.confidence)
```

### 2. Asynchronous Client

```python
import asyncio
from kap import AsyncKapClient

async def main():
    async with AsyncKapClient() as client:
        # Fetch indices and constituents
        indices = await client.get_indices()
        for idx in indices[:3]:
            print(f"Index {idx.code}: {len(idx.companies)} members")

        # Latest disclosures
        latest = await client.get_latest_disclosures(limit=10, ticker="GARAN")
        for d in latest:
            print(d.publish_date, d.title)

asyncio.run(main())
```

---

## 🤖 Agent Tool Integration & MCP Server

### 1. Model Context Protocol (MCP) Server
Launch the MCP server over stdio for direct integration into **Claude Desktop**, **Cursor**, **Gemini**, or **Antigravity**:

```bash
kap mcp
```

Add to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "kap": {
      "command": "kap",
      "args": ["mcp"]
    }
  }
}
```

### 2. OpenAI / Function Calling Tool Definitions

```python
from kap.tools import KapToolkit

toolkit = KapToolkit()

# Export tool schemas for OpenAI function calling
openai_tools = toolkit.get_openai_tools()

# Execute any tool dynamically by name
result = toolkit.execute_tool("kap_search_companies", {"query": "ASELS"})
print(result["companies"])
```

### 3. Anthropic Claude Tool Definitions

```python
anthropic_tools = toolkit.get_anthropic_tools()
```

---

## 🛠️ Available Agent Tools

| Tool Name | Description |
| :--- | :--- |
| `kap_search_companies` | Search BIST companies by ticker or company name fragment. |
| `kap_get_company_info` | Retrieve comprehensive company profile: ownership >=5%, free float, subsidiaries, auditor. |
| `kap_get_today_disclosures` | Live stream of today's KAP disclosures with optional member/type filters. |
| `kap_get_company_disclosures` | Historical announcements for a specific company over custom date windows. |
| `kap_get_disclosure_detail` | Read full plain-text announcement body and list PDF/XLS attachments. |
| `kap_get_financial_statements` | Structured balance sheet, income statement, and cash flow items. |
| `kap_get_financials` | Find the correct financial disclosure by ticker, year, and period. |
| `kap_get_expected_calendar` | Forward-looking financial reporting & earnings release calendar. |
| `kap_extract_disclosure_events` | Classify corporate events (Buyback, Dividend, Capital Increase, Guidance, etc.). |
| `kap_get_market_taxonomy` | List BIST stock indices (XU100, XU030), economic sectors, or trading markets. |

---

## 💻 CLI Commands

```bash
# Search companies
kap search THYAO

# Get company profile & ownership
kap info BIMAS

# View today's live announcements
kap today

# View latest announcements
kap latest --limit 20 --ticker GARAN

# View historical announcements
kap disclosures KCHOL --type FR --days 180

# View earnings release calendar
kap calendar --days 90

# View parsed financial statement
kap statement 123456

# Analyze disclosure for events
kap events 123456

# Start MCP Server
kap mcp
```

---

## 🧪 Running Tests

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

The CI workflow builds a wheel in a clean environment and tests the installed
artifact on Python 3.10–3.14. Before opening a PR, run `python -m compileall -q
src tests` and `python -m pytest -q` after activating `.venv`.

### Four-repository performance benchmark

The isolated benchmark compares this repository with `pykap`, `kap-tr-sdk`, and the public KAP-web portion of `bist-investment-agent`. Offline load is the default; live public-KAP checks require an explicit flag. MKK endpoints are never used.

```bash
python -m benchmarks.run --profile standard
python -m benchmarks.run --profile smoke --live --live-iterations 1
```

The benchmark auto-selects the project venv, builds the current source into a
wheel, installs that wheel into a disposable environment, and fails if the
current kap target is entirely skipped. It reports separate package_import,
client_ready, first_offline_lookup, first_live_request, and warm_lookup
scenarios. See benchmarks/README.md for the methodology.

Refresh the bundled offline registry only from the activated project
environment:

~~~bash
python scripts/refresh_registry.py
~~~

The command validates minimum row count, ticker format, uniqueness, and
32-character MKK member OIDs before atomically replacing JSON and metadata.
The weekly CI schedule checks live drift and uploads the diff report.

---

## 📄 License

License status is **proprietary / pending provenance clearance**. This repository must not be redistributed as MIT until the provenance of code adapted from `bist-investment-agent` has been cleared in writing.
