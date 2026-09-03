# CLI reference

The `kap` executable is installed with the package and emits human-readable
output by default. Use `kap --help` or a subcommand’s `--help` for the exact
options available in the installed version.

## Commands

```bash
kap search THYAO                         # offline company search
kap info BIMAS                           # profile and ownership
kap today                                # today’s KAP feed
kap latest --limit 20 --ticker GARAN     # recent announcements
kap disclosures KCHOL --type FR --days 180
kap detail 1657514 --max-chars 4000
kap financials THYAO --year 2025 --period 12A
kap statement 1657514
kap calendar --days 90
kap events 1657514
kap taxonomy indices
kap taxonomy sectors
kap taxonomy markets
kap mcp
```

Ticker filters are normalized before a request. Date windows, limits, years,
periods and disclosure indices are validated locally, so malformed input exits
with a useful error instead of making a network call.

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
