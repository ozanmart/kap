# Testing and release

## Local checks

Run the fast deterministic checks before opening a pull request:

```bash
python -m compileall -q src tests
python -m pytest -q
python -m build --no-isolation --wheel --sdist
```

The test suite covers models, validators, cache semantics, sync/async parity,
CLI behavior, toolkit schemas, MCP framing and package metadata. The CI job
also installs the built wheel into a clean target and runs tests with an empty
`PYTHONPATH`; this catches missing package data and accidental editable-install
dependencies.

## Public-KAP live gate

The live verifier is intentionally low intensity and uses public KAP only:

```bash
python -m scripts.validate_live_kap \
  --output benchmark-results/live-validation-source.json
```

It checks the registry, complete-day feed, exact ticker matching, disclosure
detail metadata, historical criteria, taxonomy, profiles, financial selection,
calendar, every agent tool and true async HTTP. Live checks are network tests,
not unit tests; run them deliberately and keep the resulting report out of
commits unless it is an intentional release artifact.

## Benchmarks

The isolated benchmark compares this package with the selected reference
repositories without contacting MKK endpoints:

```bash
python -m benchmarks.run --profile standard
python -m benchmarks.run --profile smoke --live --live-iterations 1
```

It reports package import, client readiness, first offline lookup, first live
request and warm lookup separately, then reduces every measurement to one
0-1000 `KAP Index` per repository weighted on correctness, capability coverage,
relative speed, reliability and memory. See
[../benchmarks/README.md](../benchmarks/README.md) for methodology, the category
weights and the interpretation rules.

## Registry refresh

Refresh the bundled company snapshot only from a controlled environment:

```bash
python scripts/refresh_registry.py
```

The command validates row count, ticker format, uniqueness and 32-character
member OIDs, then replaces the JSON and metadata atomically. Review the diff
and run the full test suite before committing a refreshed snapshot.

## Release checklist

1. Run compile, unit, installed-wheel and (when network is available) live-gate
   checks.
2. Build both wheel and sdist and inspect metadata with `pip check`.
3. Confirm `LICENSE`, `py.typed`, registry data and documentation are present
   in the wheel/sdist.
4. Review `CHANGELOG.md`, security notes and the provenance audit.
5. Tag the version only after the public API and data-source assumptions are
   documented.

The project is MIT-licensed, but [PROVENANCE_AUDIT.md](../PROVENANCE_AUDIT.md)
must still be reviewed before redistributing adapted material.
