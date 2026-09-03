# Data and API reference

The public Python surface is centered on `KapClient` and `AsyncKapClient`.
Methods return Pydantic models (or typed lists/dictionaries for compatibility)
and accept ticker symbols or KAP member OIDs where documented.

## Company and taxonomy

| Method | Result |
| --- | --- |
| `get_companies(online=False)` | Full `Company` registry; offline by default. |
| `search_companies(query, online=False)` | Exact/partial ticker or name matches. |
| `get_company(ticker, online=False)` | One `Company` or `None`. |
| `get_company_general_info(ticker_or_oid)` | `CompanyGeneralInfo` with market, sector, ownership, free float, subsidiaries and auditor. |
| `get_indices()` | `Indice` records and constituents. |
| `get_sectors()` | `Sector` records. |
| `get_markets()` | `Market` records. |

## Disclosures

| Method | Result and important filters |
| --- | --- |
| `get_today_disclosures(...)` | Complete Europe/Istanbul calendar-day feed; filter by member type and disclosure type. Slice the returned list locally when a smaller view is needed. |
| `get_latest_disclosures(...)` | Recent feed with optional ticker/type/class and limit. |
| `get_company_disclosures(ticker_or_oid, ...)` | Historical company announcements for a date window. |
| `get_historical_disclosures(...)` | Historical feed with explicit dates and subject criteria. |
| `get_company_disclosures_by_type(...)` | Compatibility helper for a company and disclosure type. |
| `get_disclosure_subjects(disclosure_class="FR")` | Valid KAP subject taxonomy. |
| `get_disclosure_detail(disclosure_index)` | Full text, normalized `disclosure_type`/`disclosure_class` and attachment metadata. |

Use disclosure indices as source identifiers. A detail response may contain PDF
or XLS links; downloading or parsing an attachment is separate from reading the
announcement body.

## Financials, calendar and events

- `get_financials(ticker_or_oid, year, period)` selects the matching financial
  disclosure and returns a structured summary.
- `get_financial_statement(disclosure_index)` parses statement sections and
  line items from a selected disclosure.
- `download_financial_report_xls(...)` is an opt-in experimental path enabled
  by `KapConfig(enable_xls=True)`.
- `get_expected_disclosures(days_ahead=180, ticker_or_oid=None)` returns the
  expected reporting/earnings calendar.
- `extract_events(detail)` and `extract_events_many(details)` classify events
  from disclosure text; `score_company_events` ranks derived events.

## Models and serialization

Models live under `kap.models` and are Pydantic v2 models. Use
`model.model_dump()` or `model.model_dump_json()` for application boundaries.
Do not rely on scraper-specific dictionaries when a model is available. Dates
are normalized to ISO-compatible Python date/datetime values where the source
provides them.

## Exceptions

All public network and input failures use `kap.exceptions`:

| Exception | Meaning |
| --- | --- |
| `KapError` | Base class for SDK errors. |
| `KapConnectionError` | Transport or public KAP connection failure. |
| `KapDeadlineExceeded` | Operation deadline elapsed before completion. |
| `KapValidationError` | Caller input is invalid or outside the supported range. |
| `KapNotFoundError` | Requested disclosure/company/resource is absent. |

Legacy imports from `kap.scrapers.base` remain compatible, but new code should
import from `kap.exceptions`.

## Input rules

Ticker values are normalized to uppercase and must be valid BIST symbols or
known member OIDs. Limits, years, periods, disclosure indices, date windows and
calendar horizons are validated before network access. Validation errors are
deterministic and safe to report to an end user.
