# KAP four-repository benchmark

Generated: `2026-09-02T04:22:05.952679+00:00`  
Interpreter: `/var/folders/zz/zkd3m3_d17x3z1wg5rzfvjnc0000gn/T/kap-benchmark-qo0lkvml/benchmark-venv/bin/python` (3.13.12)  
Profile: `smoke`; live: `true`

## Results

| Repository | Scenario | Load | Status | p50 ms | p95 ms | ops/s | Peak RSS MB | Items | Correct |
|---|---|---:|---|---:|---:|---:|---:|---:|---|
| kap (current) | Live public company registry | 1 | ok | 4,856.53 | 4,856.53 | 0.21 | 79.17 | 805 | — |
| pykap | Live public company registry | 1 | skipped | — | — | — | 32.25 | — | — |
| kap-tr-sdk | Live public company registry | 1 | skipped | — | — | — | 27.89 | — | — |
| bist-investment-agent (KAP web only) | Live public company registry | 1 | skipped | — | — | — | 32.12 | — | — |

## Capability and error notes

- **kap (current) / Live public company registry phases:** fetch=2.21s, ttfb=1.31s, download=0.90s, parse=0.13s, total=2.38s
- **pykap / Live public company registry:** missing dependency: requests
- **kap-tr-sdk / Live public company registry:** missing dependency: requests
- **bist-investment-agent (KAP web only) / Live public company registry:** missing dependency: tenacity

## Method

Each repository/scenario/load runs in a fresh subprocess. Timed regions exclude harness startup and adapter setup. Offline high-load runs never contact KAP. Live runs are opt-in, low-intensity, and guarded by a parent-process timeout. `Correct` validates the returned ticker set for the deterministic replay fixture; speed without correct output is not treated as a win.
