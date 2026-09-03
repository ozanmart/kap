# Agents and MCP

KAP exposes the same client behavior to function-calling agents through
`KapToolkit` and to MCP clients through a stdio server.

## `KapToolkit`

```python
from kap.tools import KapToolkit

toolkit = KapToolkit(profile="balanced")
try:
    openai_tools = toolkit.get_openai_tools()
    result = toolkit.execute_tool(
        "kap_get_latest_disclosures",
        {"ticker": "GARAN", "limit": 10},
    )
finally:
    toolkit.close()
```

Use `get_openai_tools()` for OpenAI-compatible function declarations and
`get_anthropic_tools()` for Anthropic-compatible declarations. Each schema
contains required/optional arguments and validation constraints. Tool names
are stable `kap_*` identifiers:

`kap_search_companies`, `kap_get_company_info`, `kap_get_today_disclosures`,
`kap_get_company_disclosures`, `kap_get_disclosure_detail`,
`kap_get_financial_statements`, `kap_get_financials`, `kap_get_expected_calendar`,
`kap_extract_disclosure_events` and `kap_get_market_taxonomy`.

`execute_tool` accepts a dictionary or JSON string and returns JSON-compatible
data. Invalid arguments produce a structured validation result; the toolkit
does not execute arbitrary Python or shell commands.

## MCP stdio

Install the optional dependency and launch:

```bash
python -m pip install "kap[mcp]"
kap mcp
```

Claude Desktop example:

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

The server advertises the same ten tools and protocol metadata as the toolkit.
It uses stdio framing, writes diagnostics to stderr, and never sends logs into
the protocol stream. Use an absolute executable path in desktop environments
where the package manager’s PATH is not inherited.

## Agent-safe data handling

Tool responses include source-facing identifiers such as ticker, member OID,
disclosure index, publish date, normalized disclosure type/class and attachment
metadata. Preserve these fields when an agent summarizes a disclosure so a
human can trace the answer back to KAP. Do not treat extracted event labels as
investment advice; they are parser classifications with confidence metadata.

## Time and cache budgets

Pass the same `profile` used by the application (`fast`, `balanced` or
`resilient`). For a short-lived tool process, `fast` avoids leaving a daemon
refresh behind. For an interactive assistant, `balanced` provides bounded
stale-while-revalidate behavior and typed errors.
