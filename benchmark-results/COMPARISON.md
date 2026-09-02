# Benchmark comparison policy

The repository previously contained hard-coded speed, RSS and success claims
that were not reproducible from the checked-in harness. Those claims are
retired. The source of truth is a freshly generated
`benchmark-results/latest.json` / `latest.md` pair from:

```bash
source .venv/bin/activate
python -m benchmarks.run --profile standard
```

The current harness:

- runs every repository/scenario/load in an isolated subprocess;
- benchmarks the current `kap` installed wheel, not an iCloud-hosted editable
  source path;
- reports missing comparison dependencies as `skipped`;
- checks deterministic fixture correctness and never treats `Correct: no` as a
  performance win;
- keeps live public-KAP checks opt-in and low intensity;
- does not send synthetic 1,000-concurrency load to KAP.

For production-relevant async measurements, add sanitized disclosure fixtures
and measure fetch/parse separately at concurrency 1/4/8 with connection reuse,
cancellation, a shared deadline, 429 responses and a long-running soak. A
single live sample cannot establish a permanent ranking.
