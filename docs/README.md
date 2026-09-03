# KAP documentation

This directory contains the detailed reference for the KAP SDK, CLI and agent
interfaces. Start with the quickstart, then use the architecture and API pages
as the reference when integrating the library.

| Guide | Covers |
| --- | --- |
| [Quickstart](quickstart.md) | Installation, first requests, sync/async lifecycle and common workflows. |
| [Architecture](architecture.md) | Layer boundaries, request flow, caching and extension points. |
| [Data and API](data-and-api.md) | Public clients, operations, models, filters and exceptions. |
| [Configuration](configuration.md) | Profiles, timeouts, retries, cache and SQLite persistence. |
| [CLI](cli.md) | Command reference, filters, JSON output and scripting. |
| [Agents and MCP](agents-and-mcp.md) | `KapToolkit`, function-calling schemas and MCP stdio setup. |
| [Testing and release](testing-and-release.md) | Tests, wheel verification, live checks, benchmarks and release checklist. |

KAP reads public KAP data only. It does not authenticate, submit disclosures,
or call MKK REST endpoints. Values returned by the live service can change;
applications should persist the disclosure index and publish date when they
need an auditable reference.
