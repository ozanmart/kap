# Three-repository KAP benchmark

This framework compares the current `kap` package with the two other public Python projects that read the same KAP surfaces, `pykap` and `kap-tr-sdk`. It never calls MKK or MKK REST endpoints.

Every run ends in a **scoreboard**: one 0-1000 `KAP Index` per repository, plus
the five category subscores behind it. The index exists because the per-row
table answers "how fast was this one call" and not "is this library a
reasonable choice". See [Scoring](#scoring) for the weights and the rules that
keep a fast-but-wrong parser from winning.

The framework deliberately separates three things:

- cold API import/startup cost;
- deterministic offline, cache, and HTML-replay throughput under increasing load;
- opt-in, low-intensity live `kap.org.tr` latency.

Every repository/scenario/load combination runs in a fresh subprocess. The same Python interpreter is used for all three repositories, worker processes have hard deadlines, unsupported capabilities are recorded as `skipped`, and deterministic replay also verifies output correctness. A fast but incorrect parser is therefore visible as `Correct: no`.

Cold import is sampled with independent processes (3/5/10 runs for smoke/standard/stress) because a second import inside the same process would only measure Python's module cache.

## Run

From the repository root:

```bash
python -m benchmarks.run --profile standard
```

Profiles:

- `smoke`: 1 and 5 operations;
- `standard`: 1, 5, 10, 25, and 50 operations;
- `stress`: the standard levels plus 100 and 1,000 operations.

The `auto` interpreter selector prefers the repository `.venv` and never resolves
a virtualenv launcher to its base interpreter. It preflights all three repositories,
builds the current checkout into a fresh wheel, and installs that wheel into a
disposable environment which inherits the selected interpreter's preflighted
comparison dependencies. The current `kap` import still comes only from the newly
build wheel. The harness installs the comparison-only packages (`requests`,
`pandas`, `html5lib`, and `pyppeteer`) into that
disposable environment and runs preflight there. Comparison repositories with
missing optional dependencies are reported
as `skipped`. If every current-`kap` job is skipped, the benchmark exits non-zero.
It can be selected explicitly:

```bash
python -m benchmarks.run --python /opt/miniconda3/bin/python3 --profile standard
```

Live public-KAP tests are disabled by default. They run serially and use a parent-process hard timeout:

```bash
python -m benchmarks.run --profile smoke --live --live-iterations 1
```

Use `--repo-root REPO=/new/path` to relocate a source repository. Valid keys are `kap`, `pykap`, and `kap_tr_sdk`.
For repeatable local configuration without command-line overrides, set
`KAP_BENCHMARK_PYKAP_ROOT` and `KAP_BENCHMARK_KAP_TR_SDK_ROOT`. Reports keep
only repository labels, never local absolute paths.

Reports are written as timestamped JSON and Markdown under the ignored
`benchmark-results/` directory. They are generated artifacts, not source files;
keep only intentionally curated summaries in documentation or release notes.

## Scoring

`benchmarks/scoring.py` reduces the measured rows to one index per repository:

| Category | Weight | Definition |
| --- | ---: | --- |
| Correctness | 35% | Share of the repository's own runs that passed their deterministic output check. |
| Capability coverage | 20% | Share of the suite's scenarios the repository can perform at all. |
| Relative speed | 20% | Per scenario and load, `fastest p50 / this p50`, averaged. |
| Reliability | 15% | `1 - (error rate + timeout rate)` over everything it attempted. |
| Memory efficiency | 10% | Per scenario and load, `lowest peak RSS / this peak RSS`, averaged. |

Rules that keep the number honest:

- A row that failed its correctness check is removed from the speed and memory
  comparisons, so being fast and wrong earns nothing.
- Speed and memory are compared only within the same scenario and load;
  milliseconds from different scenarios are never averaged together.
- Coverage is measured against the scenarios the benchmark actually attempted,
  so adding a scenario nobody supports moves no score.
- A repository that skips most of the suite gets a low coverage score and keeps
  its speed average over only what it ran, so skipping the hard half cannot
  produce a better index than completing all of it.

### Fairness rules

A comparison is only worth reading if nobody is set up to fail:

- Every repository is measured on the input its documented approach actually
  consumes. KAP renders the company listing client-side, so an HTTP fetch
  returns only the RSC payload while a browser also exposes `#financialTable`
  (846 rows, verified against the live page on 2026-09-03). A parser that reads
  that table finds nothing in a captured server response — but it was handed
  the wrong input, so it is recorded as `skipped` with that reason, never as
  incorrect. The browser dependency still counts against it in coverage, which
  is where a runtime requirement belongs.
- Shared fixtures hold the same data for everyone. The warm-cache scenario once
  seeded one repository with 2 companies and another with 800, which reported a
  fixture artifact as a speed result; both now hold the bundled registry.
- A scenario is only skipped when the repository genuinely lacks the
  capability, not when an adapter was never written for it. Every skip reason
  in the report names the missing capability.
- Measured field sets are the common denominator. The profile scenario scores
  the five scalars every participating parser documents, so a repository that
  models the company title elsewhere is not failed for a modelling choice.

### Known limitation

The replay scenarios cannot supply a browser-rendered DOM, so browser-based
parsers are skipped there rather than compared. Capturing a rendered snapshot
as a checked-in fixture would let them be measured directly; until then their
parse cost is simply absent from the speed comparison.

The scenario list is a capability checklist for a KAP client, not a list of
this package's features: registry loading, ticker lookup, HTML replay for
listings and company profiles, feed normalization, caching, async HTTP, and the
opt-in live calls. `benchmarks/scoring.py` is unit tested in
`tests/test_benchmark_scoring.py`, including the cases where a wrong-but-fast or
narrow-but-fast repository must not win.

## Interpretation rules

- Compare throughput only within the same scenario and load.
- Treat `Correct: no`, `error`, and `timeout` as failures, irrespective of speed.
- Live registry correctness requires at least 800 unique valid tickers plus a
  fixed reference set; a fast but incomplete 750–790-row result is a failure.
- `skipped` means the repository does not expose an equivalent local/public operation; it is not converted into a zero or silently replaced by harness code.
- Live timings include KAP and network variability. Run them repeatedly at different times before making architectural decisions.
- `Peak RSS` is process peak resident memory, including imports and dependencies.
- Async HTTP soak/concurrency behavior is validated by the mock-transport tests
  in `tests/test_http.py`; these tests exercise retry, 429 and semaphore code
  without sending synthetic load to public KAP.
- The current `live_registry` adapter also records `fetch_s`, `ttfb_s`,
  `download_s`, `parse_s`, and `total_s` in the result so a slow live call can
  be attributed to a concrete phase.
## Deterministic replay scenarios

Replay scenarios feed every repository the identical captured KAP payload, so
they isolate parser capability and cost from network variance:

- `listing_replay`: the company-list page;
- `profile_replay`: a company general-information page, scored on the scalar
  fields every profile parser claims to read;
- `feed_normalize`: a disclosure-feed payload normalized into each
  repository's own row shape.

## Startup scenarios

The startup scenarios are intentionally separate:

- `package_import`: import only the top-level package;
- `client_ready`: import and construct the client;
- `first_offline_lookup`: first real bundled ticker lookup;
- `first_live_request`: first public feed request;
- `warm_lookup`: repeated lookup after package and index warm-up.
