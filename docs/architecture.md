# Architecture

KAP is intentionally layered. Public clients own orchestration; scrapers own
one KAP surface; models define the data contract; cache and storage provide
durability; CLI and agent adapters translate external inputs into the same
client calls.

```text
Application / CLI / Agent
          |
  KapClient | AsyncKapClient
          |
  validation + deadlines + retry budget + cache metadata
          |
  scraper components (listings, disclosures, company_general, financials, calendar)
          |
  httpx transport -> public KAP SSR/API endpoints
          |
  Pydantic models + SQLite persistence
```

## Repository layout

```text
src/kap/
  client.py, async_client.py    public sync/async orchestration
  config.py                     profiles and runtime configuration
  _components.py, _validation.py shared internal factories and input rules
  scrapers/                     focused fetchers and parsers
  models/                       stable Pydantic response models
  cache.py, storage/             memory/disk cache and SQLite persistence
  tools/                        toolkit schemas and MCP server
  cli.py                        Click command line adapter
  data/                         validated offline BIST registry
tests/                          unit, contract and installed-wheel coverage
benchmarks/                     isolated performance methodology
```

## Request lifecycle

1. A public method validates query, ticker, date, period and pagination input.
2. The client starts an operation with a bounded deadline and operation ID.
3. A deterministic cache key includes the operation, normalized arguments and
   parser schema version.
4. A fresh cache value is returned immediately. A stale value can be returned
   while a bounded background refresh is scheduled, depending on profile.
5. On a miss, the selected scraper performs the smallest required public KAP
   request. Retries are bounded by the operation deadline and total attempt
   count.
6. The parser converts the response into a Pydantic model or typed result.
7. The successful value, fetched timestamp and warnings are persisted in the
   cache; optional SQLite writes keep queryable local history.
8. Request metrics record stage timings, attempts, stale/fresh state and the
   operation ID for diagnostics.

## Sync and async parity

`KapClient` uses `httpx.Client`; `AsyncKapClient` uses `httpx.AsyncClient` and
async scraper methods. Shared factories and validators prevent the two APIs
from drifting. Cache keys and model shapes are intentionally equivalent, so a
consumer can switch clients without changing downstream serialization.

## Lazy components

`KapClient` and `AsyncKapClient` construct only the transport, cache and storage
at startup. Scrapers are loaded through `_components.py` on first use. This
keeps `import kap` and offline registry searches lightweight and avoids loading
SQLite, MCP or optional financial parsers for unrelated operations.

## Data boundaries

The SDK uses public KAP website/SSR and JSON surfaces. It does not automate a
browser and does not call MKK REST APIs. HTML/JSON quirks are isolated inside
scrapers; callers should depend on models and documented exceptions rather than
private parser helpers.

## Extension points

- Add a scraper component when a new KAP surface needs a distinct fetch/parse
  boundary.
- Add a Pydantic model when a response contract is stable and reusable.
- Add a client method only when sync/async behavior, validation and cache policy
  can be specified together.
- Add an agent tool as a thin schema/adapter over an existing client method.

Keep network access, parsing and policy out of models. New public behavior must
have unit coverage and an installed-wheel check before release.
