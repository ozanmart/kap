# Changelog

## 0.1.0 — unreleased

- Fixed `get_financials`/`get_financial_statement` returning zero line items
  for holding, bank, insurance and leasing/factoring companies: the parser
  only recognized `tbl_general_role_*` table classes, missing the
  sector-specific `tbl_<sector>_role_*` variants KAP renders for those
  taxonomies. Verified live against KCHOL, GARAN, ANSGR, TURSG, ISFIN and
  LIDFA.
- Fixed `extract_events`/`extract_events_many` misclassifying routine
  Financial Report filings as false-positive events (e.g. `BUYBACK` from the
  standard "Geri Alınmış Paylar" balance-sheet line) when called with only a
  `DisclosureDetail`, as the CLI's `events` command does; the FR-type guard
  now also reads `disclosure_type` from the detail object.
- Fixed `search_companies`/`kap search` raising `TypeError: unhashable type:
  'Company'` on any multi-word name query (e.g. `"Hava Yolları"`); the local
  search index now intersects on ticker strings instead of model instances.
- Fixed `get_company_general_info`/`kap info` silently returning an all-blank
  profile with exit code 0 for an unknown ticker; it now raises
  `KapNotFoundError`, and the CLI no longer swallows the error.
- Fixed `kap calendar` output omitting `ExpectedDisclosure.subject`, which
  made distinct expected-disclosure entries look like exact duplicates.
- Enabled HTTP/2 on both HTTP clients (new `h2` dependency); falls back to
  HTTP/1.1 automatically against origins that don't offer it.
- `AsyncKapClient.get_financials` now fetches multiple year/period candidates
  concurrently instead of one sequential round trip at a time.
- Removed the unused experimental XLS financial-report download path
  (`enable_xls`, `download_financial_report_xls`) and its dead parsing
  helpers; nothing in the CLI or MCP toolkit used it.
- Added sync and async KAP clients with bounded retries, operation deadlines,
  stale-cache fallback, and request metrics.
- Added normalized company, disclosure, taxonomy, calendar, and financial
  models plus agent-tool and MCP adapters.
- Added validated offline BIST registry snapshots and public-KAP release gates.
- Added a shared exception hierarchy, lazy component wiring, typed-package
  marker, and public contribution/security guidance.

The project license is MIT.
