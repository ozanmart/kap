# CLI reference

The `kap` executable is installed with the package and emits human-readable
output by default. Use `kap --help` or a subcommand’s `--help` for the exact
options available in the installed version.

## Commands

```bash
kap --help
kap --version
kap search THYAO                         # offline company search
kap search THYAO --online                # live company search
kap info BIMAS                           # profile and ownership
kap today                                # today’s KAP feed
kap today --member-type bist_sirketleri --json-out
kap latest --limit 20 --ticker GARAN     # recent announcements
kap disclosures KCHOL --type FR --days 180
kap disclosures KCHOL --type FR --days 180 --limit 20
kap detail 1657514 --max-chars 4000
kap detail 1657514 --max-chars 4000 --json-out
kap financials THYAO --year 2025 --period annual
kap financials THYAO --year 2025 --period annual --json-out
kap statement 1657514
kap calendar --days 90
kap calendar --days 90 --ticker THYAO
kap events 1657514
kap taxonomy indices
kap taxonomy indices --json-out
kap taxonomy sectors
kap taxonomy markets
kap mcp
```

### Option matrix

| Command | Options |
| --- | --- |
| `search` | `--online` to use live KAP search instead of the bundled registry. |
| `today` | `--member-type`; `--json-out`. The client returns the complete filtered day feed. |
| `latest` | `--limit`; `--ticker`. |
| `disclosures` | `--type`; `--days`; `--limit`. |
| `detail` | `--max-chars`; `--json-out`. |
| `calendar` | `--days`; `--ticker`. |
| `financials` | Required `--year`; `--period` (`annual`, `Q1`, `Q2`, `Q3`, `Q4`); `--json-out`. |
| `taxonomy` | Category argument `indices`, `sectors` or `markets`; `--json-out`. |
| `info`, `statement`, `events`, `mcp` | No command-specific options. |

`--help` is available globally and for every subcommand. `--version` prints
the installed package version. Ticker filters are normalized before a request.
Date windows, limits, years, periods and disclosure indices are validated
locally, so malformed input exits with a useful error instead of making a
network call.

## Scripting pattern

Treat CLI output as a user-facing interface unless a command explicitly offers
JSON output in your installed version. For repeatable automation, prefer the
Python API or `KapToolkit`, where Pydantic models and typed errors are stable.
Pin the package version for jobs that require a fixed schema.

## MCP from the CLI

`kap mcp` starts a stdio server and keeps protocol messages on stdout. Logs are
sent to stderr. This makes it safe to launch from a desktop agent configuration
or a subprocess supervisor. See [agents-and-mcp.md](agents-and-mcp.md) for the
configuration snippet and tool names.

## CLI dışı bakım komutları

These are repository maintenance scripts, not installed `kap` subcommands:

```bash
python scripts/refresh_registry.py
python -m scripts.validate_live_kap
python scripts/verify_cli.py
python scripts/verify_mcp_stdio.py
python -m benchmarks.run --profile standard
```
