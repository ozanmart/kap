# Four-repository KAP benchmark

This framework compares the current `kap` package with `pykap`, `kap-tr-sdk`, and the public KAP-web portion of `bist-investment-agent`. It never calls MKK or MKK REST endpoints.

The framework deliberately separates three things:

- cold API import/startup cost;
- deterministic offline, cache, and HTML-replay throughput under increasing load;
- opt-in, low-intensity live `kap.org.tr` latency.

Every repository/scenario/load combination runs in a fresh subprocess. The same Python interpreter is used for all four repositories, worker processes have hard deadlines, unsupported capabilities are recorded as `skipped`, and deterministic replay also verifies output correctness. A fast but incorrect parser is therefore visible as `Correct: no`.

Cold import is sampled with independent processes (3/5/10 runs for smoke/standard/stress) because a second import inside the same process would only measure Python's module cache.

## Run

From the repository root:

```bash
python -m benchmarks.run --profile standard
```

Profiles:

- `smoke`: 1 and 10 operations;
- `standard`: 1, 100, and 1,000 operations;
- `stress`: 1, 100, 1,000, and 10,000 operations.

The `auto` interpreter selector prefers the repository `.venv` and never resolves
a virtualenv launcher to its base interpreter. It preflights all four repositories,
builds the current checkout into a fresh wheel, and installs that wheel plus runtime
dependencies into a disposable benchmark environment. Comparison repositories with
missing optional dependencies are reported as `skipped`. If every current-`kap` job
is skipped, the benchmark exits non-zero. It can be selected explicitly:

```bash
python -m benchmarks.run --python /opt/miniconda3/bin/python3 --profile standard
```

Live public-KAP tests are disabled by default. They run serially and use a parent-process hard timeout:

```bash
python -m benchmarks.run --profile smoke --live --live-iterations 1
```

Use `--repo-root REPO=/new/path` to relocate a source repository. Valid keys are `kap`, `pykap`, `kap_tr_sdk`, and `bist_agent`.

Reports are written as timestamped JSON and Markdown plus stable `benchmark-results/latest.json` and `benchmark-results/latest.md` files.

## Interpretation rules

- Compare throughput only within the same scenario and load.
- Treat `Correct: no`, `error`, and `timeout` as failures, irrespective of speed.
- `skipped` means the repository does not expose an equivalent local/public operation; it is not converted into a zero or silently replaced by harness code.
- Live timings include KAP and network variability. Run them repeatedly at different times before making architectural decisions.
- `Peak RSS` is process peak resident memory, including imports and dependencies.
- Async HTTP soak/concurrency behavior is validated by the mock-transport tests
  in `tests/test_http.py`; these tests exercise retry, 429 and semaphore code
  without sending synthetic load to public KAP.
- The current `live_registry` adapter also records `fetch_s`, `ttfb_s`,
  `download_s`, `parse_s`, and `total_s` in the result so a slow live call can
  be attributed to a concrete phase.
## Startup scenarios

The startup scenarios are intentionally separate:

- `package_import`: import only the top-level package;
- `client_ready`: import and construct the client;
- `first_offline_lookup`: first real bundled ticker lookup;
- `first_live_request`: first public feed request;
- `warm_lookup`: repeated lookup after package and index warm-up.
