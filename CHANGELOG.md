# Changelog

## 0.1.0 — unreleased

- Fixed the sync client raising `AttributeError: 'dict' object has no attribute
  ...` (or silently returning `list[dict]`) for any entry the async client had
  written to the shared cache. Both clients use one cache namespace and one
  cache directory but stored different representations: model instances on the
  sync side, `model_dump()` dictionaries on the async side. Both now store
  dictionaries through shared `_dump`/`_load` helpers, so either client can read
  the other's entries and no pickled model class has to survive an upgrade.
- Fixed `AsyncKapClient.extract_events`/`extract_events_many` still
  misclassifying routine Financial Report filings as false-positive events
  (e.g. `BUYBACK`); the FR guard now reads `disclosure_type` from the detail
  object, matching the sync client.
- Fixed `AsyncKapClient.get_company_general_info` returning an all-blank profile
  for an unknown ticker instead of raising `KapNotFoundError`.
- Added behavioral sync/async parity coverage for the FR guard, the not-found
  guard and cross-client cache interoperability. The existing parity test only
  compared method names, which is why these three defects reached the branch.
- Fixed `tests/test_profiles_lazy.py` running its short-lived-process subprocess
  without `PYTHONPATH`, so that test exercised whatever `kap` was installed in
  the environment rather than this checkout.
- Fixed `search_companies`/`kap search` missing every company whose name
  contains a Turkish lowercase `i`: `"Şişe".upper()` yields `ŞIŞE` (dotless I)
  while the registry holds `ŞİŞE`, so the query and the index could never meet.
  Both sides are now folded through one Turkish-aware table, which also makes
  diacritic-free queries such as `sise cam` or `turk hava` work.
- `AsyncKapClient.get_historical_disclosures` now fetches KAP's mandatory
  one-year query windows concurrently; a decade-long query no longer costs ten
  sequential round trips.
- `AsyncKapClient.get_financials` no longer fetches every matching candidate up
  front. It resolves the highest-index filing first, which satisfies nearly
  every lookup, and only falls back to the remaining candidates - concurrently -
  when that one is unusable.

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
