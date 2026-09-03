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
- Fixed `run_with_deadline_async` never publishing a `parse_error` stage when a
  parser raised, so a failed async parse was indistinguishable from a running
  one in `last_request_metrics`.
- Moved the HTTP retry/deadline/metrics policy and the parser-deadline
  bookkeeping into single implementations shared by the sync and async
  transports, and dropped the duplicated Next.js RSC payload helpers from the
  listings scraper in favor of `kap.parsing.rsc`.
- Fixed `normalize_decimal_value` routing through `float` before building a
  `Decimal`, which lost precision on the large magnitudes that appear in
  full-unit TRY statements; the value is now parsed straight from the
  normalized text.
- Fixed `KapToolkit.get_tool_map` referencing `BaseModel` without importing it,
  which made `typing.get_type_hints` raise `NameError` for any tool that
  introspects the toolkit.
- `kap events` now prints every detected event instead of only the first one.
- Fixed the async stale-while-revalidate refresh being scheduled as an unowned
  `asyncio` task, which let it be garbage collected mid-flight.
- Removed the unused `mcp` install extra: the MCP server implements the
  protocol's JSON-RPC framing directly and never imported the package.
- Documented that KAP's public taxonomy exposes a single sector level, so
  `Sector.sub_sectors` stays empty, and corrected the `kap taxonomy` help text.
- Corrected the event-scoring comment: `exp(-age/30)` is a 30-day decay
  constant, not a half-life.
- Removed `tests/run_all.py`, a hand-rolled runner duplicating pytest.
- Fixed `get_historical_disclosures` returning zero rows for every caller. The
  detailed-inquiry endpoint answers any non-empty `subjectList` with an empty
  result whatever subject OID it is given, and the client sent the
  financial-report subject by default. The query now goes out unfiltered and
  the subject is matched against the one each row reports, allowing for the
  qualifier KAP appends (`Sorumluluk Beyanı` arrives as
  `Sorumluluk Beyanı (Konsolide)`). An unresolvable `subject_oid` now raises
  `KapValidationError` listing the valid subjects instead of silently widening
  the query, and the financial-report default only applies inside the `FR`
  class.
- Removed `SUBJECT_OID_ACTIVITY_REPORT`, which was unused and matched no
  subject in any live disclosure class.
- Fixed every network call raising `ImportError` when `h2` is absent instead of
  falling back to HTTP/1.1. `h2` is a declared dependency, but httpx raises from
  the client constructor, so any environment missing it lost the whole SDK.
- Fixed `get_company_disclosures`/`kap disclosures` silently returning nothing
  for a `range_days` KAP does not serve. The company feed honors 1-365 days or a
  four-digit calendar year and answers anything else with an empty list, which
  looked like a company with no filings; other values now raise
  `KapValidationError`.
- Fixed company-profile text keeping the source markup's newlines and
  non-breaking spaces (a subsidiary title arrived as `THY ... A.Ş.\n`).
- `kap statement` gained `--ticker`, since a report page does not always carry
  the stock code and the output otherwise read `UNKNOWN`.
- `kap events` now prints the decayed impact score instead of `None`.
- Added a composite **KAP Index** to the benchmark: one 0-1000 score per project
  weighted on correctness (35%), capability coverage (20%), relative speed
  (20%), reliability (15%) and memory efficiency (10%). A row that fails its
  correctness check is excluded from the speed and memory comparisons, speed is
  only compared within the same scenario and load, and a scenario only one
  project can perform is scored as coverage rather than as an uncontested speed
  win.
- Added `profile_replay` and `feed_normalize` benchmark scenarios so company-
  profile parsing and disclosure-feed normalization are compared across
  repositories on identical captured payloads.
- Narrowed the benchmark to the two other public KAP projects, `pykap` and
  `kap-tr-sdk`.

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
