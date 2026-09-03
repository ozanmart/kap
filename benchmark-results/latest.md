# KAP four-repository benchmark

Generated: `2026-09-03T08:25:13.249967+00:00`<br>
Interpreter: `python` (3.13.12)<br>
Profile: `standard`; live: `false`

## Results

| Repository | Scenario | Load | Status | min | p50 | p95 | p99 | max | mean | σ ms | ops/s | err % | timeout % | RSS MB | Items | Correct |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| kap (current) | Package import | 1 | ok | 0.01 | 0.01 | 0.01 | 0.01 | 0.01 | 0.01 | 0.00 | 72,950.10 | 0.00 | 0.00 | 27.95 | 25 | — |
| pykap | Package import | 1 | ok | 0.04 | 0.04 | 0.04 | 0.04 | 0.04 | 0.04 | 0.00 | 22,514.41 | 0.00 | 0.00 | 81.31 | 29 | — |
| kap-tr-sdk | Package import | 1 | ok | 0.01 | 0.01 | 0.01 | 0.01 | 0.01 | 0.01 | 0.00 | 103,896.10 | 0.00 | 0.00 | 27.97 | 10 | — |
| bist-investment-agent (KAP web only) | Package import | 1 | ok | 0.01 | 0.01 | 0.01 | 0.01 | 0.01 | 0.01 | 0.00 | 106,202.21 | 0.00 | 0.00 | 27.92 | 11 | — |
| kap (current) | Client construction | 1 | ok | 0.06 | 0.06 | 0.06 | 0.06 | 0.06 | 0.06 | 0.00 | 16,427.10 | 0.00 | 0.00 | 39.91 | 1 | yes |
| pykap | Client construction | 1 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.81 | — | — |
| kap-tr-sdk | Client construction | 1 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.83 | — | — |
| bist-investment-agent (KAP web only) | Client construction | 1 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.92 | — | — |
| kap (current) | First offline lookup | 1 | ok | 0.11 | 0.11 | 0.11 | 0.11 | 0.11 | 0.11 | 0.00 | 8,918.62 | 0.00 | 0.00 | 53.89 | 1 | yes |
| pykap | First offline lookup | 1 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.94 | — | — |
| kap-tr-sdk | First offline lookup | 1 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.84 | — | — |
| bist-investment-agent (KAP web only) | First offline lookup | 1 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.88 | — | — |
| kap (current) | Warm lookup | 1 | ok | 0.02 | 0.02 | 0.02 | 0.02 | 0.02 | 0.02 | 0.00 | 40,267.38 | 0.00 | 0.00 | 53.64 | 1 | yes |
| kap (current) | Warm lookup | 5 | ok | 0.00 | 0.01 | 0.02 | 0.02 | 0.02 | 0.01 | 0.01 | 110,192.84 | 0.00 | 0.00 | 53.72 | 1 | yes |
| kap (current) | Warm lookup | 10 | ok | 0.00 | 0.00 | 0.02 | 0.02 | 0.02 | 0.01 | 0.01 | 139,209.84 | 0.00 | 0.00 | 53.73 | 1 | yes |
| kap (current) | Warm lookup | 25 | ok | 0.00 | 0.00 | 0.01 | 0.02 | 0.03 | 0.01 | 0.00 | 165,062.26 | 0.00 | 0.00 | 53.78 | 1 | yes |
| kap (current) | Warm lookup | 50 | ok | 0.00 | 0.00 | 0.01 | 0.02 | 0.02 | 0.00 | 0.00 | 196,527.75 | 0.00 | 0.00 | 53.66 | 1 | yes |
| pykap | Warm lookup | 1 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.89 | — | — |
| pykap | Warm lookup | 5 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.97 | — | — |
| pykap | Warm lookup | 10 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.97 | — | — |
| pykap | Warm lookup | 25 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.91 | — | — |
| pykap | Warm lookup | 50 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.88 | — | — |
| kap-tr-sdk | Warm lookup | 1 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.84 | — | — |
| kap-tr-sdk | Warm lookup | 5 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.91 | — | — |
| kap-tr-sdk | Warm lookup | 10 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.84 | — | — |
| kap-tr-sdk | Warm lookup | 25 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.78 | — | — |
| kap-tr-sdk | Warm lookup | 50 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.89 | — | — |
| bist-investment-agent (KAP web only) | Warm lookup | 1 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.89 | — | — |
| bist-investment-agent (KAP web only) | Warm lookup | 5 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.91 | — | — |
| bist-investment-agent (KAP web only) | Warm lookup | 10 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.84 | — | — |
| bist-investment-agent (KAP web only) | Warm lookup | 25 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.89 | — | — |
| bist-investment-agent (KAP web only) | Warm lookup | 50 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.94 | — | — |
| kap (current) | Cold API import | 5 | ok | 0.16 | 0.17 | 0.19 | 0.19 | 0.19 | 0.17 | 0.01 | — | 0.00 | 0.00 | 28.11 | 25 | — |
| pykap | Cold API import | 5 | ok | 269.89 | 325.16 | 15,503.83 | 18,539.56 | 19,298.49 | 4,097.76 | 7,600.40 | — | 0.00 | 0.00 | 86.23 | 29 | — |
| kap-tr-sdk | Cold API import | 5 | ok | 289.58 | 290.25 | 2,135.91 | 2,135.91 | 2,135.91 | 1,028.24 | 904.40 | — | 0.00 | 0.00 | 89.84 | 37 | — |
| bist-investment-agent (KAP web only) | Cold API import | 5 | ok | 23.17 | 23.37 | 30.53 | 31.49 | 31.73 | 25.44 | 3.29 | — | 0.00 | 0.00 | 32.53 | 17 | — |
| kap (current) | Company-list HTML replay | 1 | ok | 0.27 | 0.27 | 0.27 | 0.27 | 0.27 | 0.27 | 0.00 | 3,616.64 | 0.00 | 0.00 | 50.05 | 4 | yes |
| kap (current) | Company-list HTML replay | 5 | ok | 0.14 | 0.15 | 0.18 | 0.19 | 0.19 | 0.16 | 0.02 | 6,289.31 | 0.00 | 0.00 | 49.97 | 4 | yes |
| kap (current) | Company-list HTML replay | 10 | ok | 0.14 | 0.14 | 0.17 | 0.18 | 0.19 | 0.15 | 0.01 | 6,799.06 | 0.00 | 0.00 | 49.92 | 4 | yes |
| kap (current) | Company-list HTML replay | 25 | ok | 0.14 | 0.14 | 0.15 | 0.18 | 0.18 | 0.14 | 0.01 | 7,047.71 | 0.00 | 0.00 | 50.09 | 4 | yes |
| kap (current) | Company-list HTML replay | 50 | ok | 0.14 | 0.14 | 0.15 | 0.18 | 0.19 | 0.14 | 0.01 | 7,130.38 | 0.00 | 0.00 | 50.17 | 4 | yes |
| pykap | Company-list HTML replay | 1 | ok | 0.84 | 0.84 | 0.84 | 0.84 | 0.84 | 0.84 | 0.00 | 1,190.83 | 0.00 | 0.00 | 86.45 | 3 | no |
| pykap | Company-list HTML replay | 5 | ok | 0.68 | 0.70 | 0.76 | 0.77 | 0.77 | 0.71 | 0.03 | 1,409.11 | 0.00 | 0.00 | 86.62 | 3 | no |
| pykap | Company-list HTML replay | 10 | ok | 0.65 | 0.68 | 0.81 | 0.83 | 0.84 | 0.70 | 0.06 | 1,427.26 | 0.00 | 0.00 | 86.72 | 3 | no |
| pykap | Company-list HTML replay | 25 | ok | 0.64 | 0.66 | 0.85 | 0.87 | 0.87 | 0.69 | 0.06 | 1,447.82 | 0.00 | 0.00 | 87.00 | 3 | no |
| pykap | Company-list HTML replay | 50 | ok | 0.64 | 0.68 | 0.90 | 1.09 | 1.09 | 0.73 | 0.11 | 1,364.50 | 0.00 | 0.00 | 87.11 | 3 | no |
| kap-tr-sdk | Company-list HTML replay | 1 | ok | 0.54 | 0.54 | 0.54 | 0.54 | 0.54 | 0.54 | 0.00 | 1,852.42 | 0.00 | 0.00 | 44.11 | 0 | no |
| kap-tr-sdk | Company-list HTML replay | 5 | ok | 0.40 | 0.43 | 0.47 | 0.47 | 0.48 | 0.43 | 0.03 | 2,325.18 | 0.00 | 0.00 | 44.23 | 0 | no |
| kap-tr-sdk | Company-list HTML replay | 10 | ok | 0.37 | 0.38 | 0.45 | 0.48 | 0.48 | 0.40 | 0.03 | 2,524.08 | 0.00 | 0.00 | 44.25 | 0 | no |
| kap-tr-sdk | Company-list HTML replay | 25 | ok | 0.36 | 0.39 | 0.56 | 0.59 | 0.59 | 0.41 | 0.06 | 2,411.95 | 0.00 | 0.00 | 44.23 | 0 | no |
| kap-tr-sdk | Company-list HTML replay | 50 | ok | 0.36 | 0.37 | 0.58 | 0.61 | 0.62 | 0.40 | 0.06 | 2,503.12 | 0.00 | 0.00 | 44.48 | 0 | no |
| bist-investment-agent (KAP web only) | Company-list HTML replay | 1 | ok | 0.25 | 0.25 | 0.25 | 0.25 | 0.25 | 0.25 | 0.00 | 3,901.80 | 0.00 | 0.00 | 50.91 | 3 | no |
| bist-investment-agent (KAP web only) | Company-list HTML replay | 5 | ok | 0.19 | 0.20 | 0.25 | 0.25 | 0.25 | 0.21 | 0.02 | 4,696.86 | 0.00 | 0.00 | 50.88 | 3 | no |
| bist-investment-agent (KAP web only) | Company-list HTML replay | 10 | ok | 0.19 | 0.20 | 0.24 | 0.25 | 0.25 | 0.21 | 0.02 | 4,789.37 | 0.00 | 0.00 | 50.83 | 3 | no |
| bist-investment-agent (KAP web only) | Company-list HTML replay | 25 | ok | 0.19 | 0.19 | 0.21 | 0.25 | 0.26 | 0.19 | 0.01 | 5,129.08 | 0.00 | 0.00 | 50.98 | 3 | no |
| bist-investment-agent (KAP web only) | Company-list HTML replay | 50 | ok | 0.19 | 0.20 | 0.23 | 0.36 | 0.48 | 0.20 | 0.04 | 4,892.13 | 0.00 | 0.00 | 50.97 | 3 | no |
| kap (current) | Bundled registry load | 1 | ok | 0.32 | 0.32 | 0.32 | 0.32 | 0.32 | 0.32 | 0.00 | 3,080.08 | 0.00 | 0.00 | 52.20 | 805 | — |
| kap (current) | Bundled registry load | 5 | ok | 0.27 | 0.29 | 0.34 | 0.34 | 0.34 | 0.30 | 0.03 | 3,350.18 | 0.00 | 0.00 | 52.27 | 805 | — |
| kap (current) | Bundled registry load | 10 | ok | 0.26 | 0.27 | 0.32 | 0.33 | 0.33 | 0.28 | 0.02 | 3,572.23 | 0.00 | 0.00 | 52.27 | 805 | — |
| kap (current) | Bundled registry load | 25 | ok | 0.26 | 0.26 | 0.28 | 0.32 | 0.33 | 0.27 | 0.01 | 3,710.46 | 0.00 | 0.00 | 52.22 | 805 | — |
| kap (current) | Bundled registry load | 50 | ok | 0.26 | 0.26 | 0.27 | 0.29 | 0.31 | 0.26 | 0.01 | 3,788.05 | 0.00 | 0.00 | 52.23 | 805 | — |
| pykap | Bundled registry load | 1 | ok | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 0.00 | 699.36 | 0.00 | 0.00 | 87.36 | 759 | — |
| pykap | Bundled registry load | 5 | ok | 1.24 | 1.25 | 1.34 | 1.35 | 1.35 | 1.27 | 0.04 | 786.86 | 0.00 | 0.00 | 87.41 | 759 | — |
| pykap | Bundled registry load | 10 | ok | 1.26 | 1.27 | 1.37 | 1.37 | 1.38 | 1.29 | 0.04 | 773.81 | 0.00 | 0.00 | 87.39 | 759 | — |
| pykap | Bundled registry load | 25 | ok | 1.24 | 1.26 | 1.30 | 1.35 | 1.37 | 1.27 | 0.02 | 788.89 | 0.00 | 0.00 | 87.45 | 759 | — |
| pykap | Bundled registry load | 50 | ok | 1.24 | 1.30 | 5.53 | 11.02 | 14.65 | 2.01 | 2.19 | 497.71 | 0.00 | 0.00 | 88.41 | 759 | — |
| kap-tr-sdk | Bundled registry load | 1 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.91 | — | — |
| kap-tr-sdk | Bundled registry load | 5 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.83 | — | — |
| kap-tr-sdk | Bundled registry load | 10 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.94 | — | — |
| kap-tr-sdk | Bundled registry load | 25 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.98 | — | — |
| kap-tr-sdk | Bundled registry load | 50 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.91 | — | — |
| bist-investment-agent (KAP web only) | Bundled registry load | 1 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.91 | — | — |
| bist-investment-agent (KAP web only) | Bundled registry load | 5 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.88 | — | — |
| bist-investment-agent (KAP web only) | Bundled registry load | 10 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.84 | — | — |
| bist-investment-agent (KAP web only) | Bundled registry load | 25 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.98 | — | — |
| bist-investment-agent (KAP web only) | Bundled registry load | 50 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.91 | — | — |
| kap (current) | Exact ticker lookup (offline) | 1 | ok | 0.04 | 0.04 | 0.04 | 0.04 | 0.04 | 0.04 | 0.00 | 26,431.95 | 0.00 | 0.00 | 53.73 | 1 | yes |
| kap (current) | Exact ticker lookup (offline) | 5 | ok | 0.01 | 0.01 | 0.02 | 0.02 | 0.02 | 0.01 | 0.01 | 106,666.67 | 0.00 | 0.00 | 53.72 | 1 | yes |
| kap (current) | Exact ticker lookup (offline) | 10 | ok | 0.00 | 0.01 | 0.02 | 0.03 | 0.03 | 0.01 | 0.01 | 107,962.21 | 0.00 | 0.00 | 53.69 | 1 | yes |
| kap (current) | Exact ticker lookup (offline) | 25 | ok | 0.00 | 0.01 | 0.01 | 0.02 | 0.03 | 0.01 | 0.00 | 143,232.82 | 0.00 | 0.00 | 53.66 | 1 | yes |
| kap (current) | Exact ticker lookup (offline) | 50 | ok | 0.00 | 0.00 | 0.01 | 0.01 | 0.02 | 0.01 | 0.00 | 184,728.84 | 0.00 | 0.00 | 53.66 | 1 | yes |
| pykap | Exact ticker lookup (offline) | 1 | ok | 1.19 | 1.19 | 1.19 | 1.19 | 1.19 | 1.19 | 0.00 | 836.65 | 0.00 | 0.00 | 87.27 | 1 | yes |
| pykap | Exact ticker lookup (offline) | 5 | ok | 1.08 | 1.11 | 1.16 | 1.16 | 1.16 | 1.12 | 0.03 | 894.94 | 0.00 | 0.00 | 87.31 | 1 | yes |
| pykap | Exact ticker lookup (offline) | 10 | ok | 1.04 | 1.06 | 1.13 | 1.15 | 1.16 | 1.07 | 0.03 | 934.78 | 0.00 | 0.00 | 87.22 | 1 | yes |
| pykap | Exact ticker lookup (offline) | 25 | ok | 1.05 | 1.06 | 1.14 | 1.22 | 1.25 | 1.07 | 0.04 | 931.09 | 0.00 | 0.00 | 87.27 | 1 | yes |
| pykap | Exact ticker lookup (offline) | 50 | ok | 1.05 | 1.07 | 1.21 | 1.23 | 1.24 | 1.09 | 0.05 | 916.15 | 0.00 | 0.00 | 87.36 | 1 | yes |
| kap-tr-sdk | Exact ticker lookup (offline) | 1 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.91 | — | — |
| kap-tr-sdk | Exact ticker lookup (offline) | 5 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.84 | — | — |
| kap-tr-sdk | Exact ticker lookup (offline) | 10 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.80 | — | — |
| kap-tr-sdk | Exact ticker lookup (offline) | 25 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.89 | — | — |
| kap-tr-sdk | Exact ticker lookup (offline) | 50 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.86 | — | — |
| bist-investment-agent (KAP web only) | Exact ticker lookup (offline) | 1 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.95 | — | — |
| bist-investment-agent (KAP web only) | Exact ticker lookup (offline) | 5 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.88 | — | — |
| bist-investment-agent (KAP web only) | Exact ticker lookup (offline) | 10 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.84 | — | — |
| bist-investment-agent (KAP web only) | Exact ticker lookup (offline) | 25 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.81 | — | — |
| bist-investment-agent (KAP web only) | Exact ticker lookup (offline) | 50 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.92 | — | — |
| kap (current) | Exact ticker lookup (warm cache) | 1 | ok | 0.06 | 0.06 | 0.06 | 0.06 | 0.06 | 0.06 | 0.00 | 16,960.94 | 0.00 | 0.00 | 54.88 | 1 | yes |
| kap (current) | Exact ticker lookup (warm cache) | 5 | ok | 0.03 | 0.03 | 0.05 | 0.05 | 0.05 | 0.03 | 0.01 | 29,232.76 | 0.00 | 0.00 | 55.19 | 1 | yes |
| kap (current) | Exact ticker lookup (warm cache) | 10 | ok | 0.02 | 0.02 | 0.04 | 0.05 | 0.05 | 0.03 | 0.01 | 34,853.41 | 0.00 | 0.00 | 55.11 | 1 | yes |
| kap (current) | Exact ticker lookup (warm cache) | 25 | ok | 0.02 | 0.02 | 0.03 | 0.05 | 0.06 | 0.03 | 0.01 | 37,669.49 | 0.00 | 0.00 | 55.05 | 1 | yes |
| kap (current) | Exact ticker lookup (warm cache) | 50 | ok | 0.02 | 0.02 | 0.03 | 0.04 | 0.05 | 0.03 | 0.00 | 39,040.91 | 0.00 | 0.00 | 55.12 | 1 | yes |
| pykap | Exact ticker lookup (warm cache) | 1 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.83 | — | — |
| pykap | Exact ticker lookup (warm cache) | 5 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.91 | — | — |
| pykap | Exact ticker lookup (warm cache) | 10 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.80 | — | — |
| pykap | Exact ticker lookup (warm cache) | 25 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.89 | — | — |
| pykap | Exact ticker lookup (warm cache) | 50 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.78 | — | — |
| kap-tr-sdk | Exact ticker lookup (warm cache) | 1 | ok | 0.16 | 0.16 | 0.16 | 0.16 | 0.16 | 0.16 | 0.00 | 6,240.25 | 0.00 | 0.00 | 90.83 | 1 | yes |
| kap-tr-sdk | Exact ticker lookup (warm cache) | 5 | ok | 0.04 | 0.06 | 0.10 | 0.11 | 0.12 | 0.07 | 0.02 | 14,687.91 | 0.00 | 0.00 | 90.69 | 1 | yes |
| kap-tr-sdk | Exact ticker lookup (warm cache) | 10 | ok | 0.04 | 0.05 | 0.10 | 0.13 | 0.14 | 0.06 | 0.03 | 16,826.75 | 0.00 | 0.00 | 90.69 | 1 | yes |
| kap-tr-sdk | Exact ticker lookup (warm cache) | 25 | ok | 0.04 | 0.05 | 0.08 | 0.11 | 0.12 | 0.06 | 0.02 | 17,804.68 | 0.00 | 0.00 | 90.72 | 1 | yes |
| kap-tr-sdk | Exact ticker lookup (warm cache) | 50 | ok | 0.04 | 0.04 | 0.06 | 0.09 | 0.10 | 0.04 | 0.01 | 22,464.76 | 0.00 | 0.00 | 90.72 | 1 | yes |
| bist-investment-agent (KAP web only) | Exact ticker lookup (warm cache) | 1 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.81 | — | — |
| bist-investment-agent (KAP web only) | Exact ticker lookup (warm cache) | 5 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.88 | — | — |
| bist-investment-agent (KAP web only) | Exact ticker lookup (warm cache) | 10 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.89 | — | — |
| bist-investment-agent (KAP web only) | Exact ticker lookup (warm cache) | 25 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.94 | — | — |
| bist-investment-agent (KAP web only) | Exact ticker lookup (warm cache) | 50 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.92 | — | — |
| kap (current) | Async HTTP client soak (local server) | 1 | ok | 26.31 | 26.31 | 26.31 | 26.31 | 26.31 | 26.31 | 0.00 | 38.01 | 0.00 | 0.00 | 46.56 | 32 | yes |
| kap (current) | Async HTTP client soak (local server) | 5 | ok | 25.37 | 26.13 | 30.53 | 31.02 | 31.14 | 27.32 | 2.13 | 36.61 | 0.00 | 0.00 | 47.16 | 32 | yes |
| kap (current) | Async HTTP client soak (local server) | 10 | ok | 25.28 | 26.40 | 28.19 | 28.34 | 28.38 | 26.50 | 1.02 | 37.73 | 0.00 | 0.00 | 47.09 | 32 | yes |
| kap (current) | Async HTTP client soak (local server) | 25 | ok | 24.09 | 28.87 | 31.81 | 33.43 | 33.94 | 28.83 | 2.23 | 34.68 | 0.00 | 0.00 | 47.30 | 32 | yes |
| kap (current) | Async HTTP client soak (local server) | 50 | ok | 23.84 | 28.59 | 32.41 | 35.06 | 36.99 | 28.45 | 2.38 | 35.15 | 0.00 | 0.00 | 47.67 | 32 | yes |
| pykap | Async HTTP client soak (local server) | 1 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.94 | — | — |
| pykap | Async HTTP client soak (local server) | 5 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.92 | — | — |
| pykap | Async HTTP client soak (local server) | 10 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.92 | — | — |
| pykap | Async HTTP client soak (local server) | 25 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.92 | — | — |
| pykap | Async HTTP client soak (local server) | 50 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.88 | — | — |
| kap-tr-sdk | Async HTTP client soak (local server) | 1 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.94 | — | — |
| kap-tr-sdk | Async HTTP client soak (local server) | 5 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.80 | — | — |
| kap-tr-sdk | Async HTTP client soak (local server) | 10 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.81 | — | — |
| kap-tr-sdk | Async HTTP client soak (local server) | 25 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.89 | — | — |
| kap-tr-sdk | Async HTTP client soak (local server) | 50 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.94 | — | — |
| bist-investment-agent (KAP web only) | Async HTTP client soak (local server) | 1 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.89 | — | — |
| bist-investment-agent (KAP web only) | Async HTTP client soak (local server) | 5 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.91 | — | — |
| bist-investment-agent (KAP web only) | Async HTTP client soak (local server) | 10 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.92 | — | — |
| bist-investment-agent (KAP web only) | Async HTTP client soak (local server) | 25 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.97 | — | — |
| bist-investment-agent (KAP web only) | Async HTTP client soak (local server) | 50 | skipped | — | — | — | — | — | — | — | — | 0.00 | 0.00 | 27.83 | — | — |

## Capability and error notes

- **pykap / Client construction:** client-ready scenario is implemented for kap
- **kap-tr-sdk / Client construction:** client-ready scenario is implemented for kap
- **bist-investment-agent (KAP web only) / Client construction:** client-ready scenario is implemented for kap
- **pykap / First offline lookup:** first offline lookup is implemented for kap
- **kap-tr-sdk / First offline lookup:** first offline lookup is implemented for kap
- **bist-investment-agent (KAP web only) / First offline lookup:** first offline lookup is implemented for kap
- **pykap / Warm lookup:** warm lookup is implemented for kap
- **pykap / Warm lookup:** warm lookup is implemented for kap
- **pykap / Warm lookup:** warm lookup is implemented for kap
- **pykap / Warm lookup:** warm lookup is implemented for kap
- **pykap / Warm lookup:** warm lookup is implemented for kap
- **kap-tr-sdk / Warm lookup:** warm lookup is implemented for kap
- **kap-tr-sdk / Warm lookup:** warm lookup is implemented for kap
- **kap-tr-sdk / Warm lookup:** warm lookup is implemented for kap
- **kap-tr-sdk / Warm lookup:** warm lookup is implemented for kap
- **kap-tr-sdk / Warm lookup:** warm lookup is implemented for kap
- **bist-investment-agent (KAP web only) / Warm lookup:** warm lookup is implemented for kap
- **bist-investment-agent (KAP web only) / Warm lookup:** warm lookup is implemented for kap
- **bist-investment-agent (KAP web only) / Warm lookup:** warm lookup is implemented for kap
- **bist-investment-agent (KAP web only) / Warm lookup:** warm lookup is implemented for kap
- **bist-investment-agent (KAP web only) / Warm lookup:** warm lookup is implemented for kap
- **pykap / Company-list HTML replay:** deterministic correctness check failed; do not treat throughput as a valid win
- **pykap / Company-list HTML replay:** deterministic correctness check failed; do not treat throughput as a valid win
- **pykap / Company-list HTML replay:** deterministic correctness check failed; do not treat throughput as a valid win
- **pykap / Company-list HTML replay:** deterministic correctness check failed; do not treat throughput as a valid win
- **pykap / Company-list HTML replay:** deterministic correctness check failed; do not treat throughput as a valid win
- **kap-tr-sdk / Company-list HTML replay:** deterministic correctness check failed; do not treat throughput as a valid win
- **kap-tr-sdk / Company-list HTML replay:** deterministic correctness check failed; do not treat throughput as a valid win
- **kap-tr-sdk / Company-list HTML replay:** deterministic correctness check failed; do not treat throughput as a valid win
- **kap-tr-sdk / Company-list HTML replay:** deterministic correctness check failed; do not treat throughput as a valid win
- **kap-tr-sdk / Company-list HTML replay:** deterministic correctness check failed; do not treat throughput as a valid win
- **bist-investment-agent (KAP web only) / Company-list HTML replay:** deterministic correctness check failed; do not treat throughput as a valid win
- **bist-investment-agent (KAP web only) / Company-list HTML replay:** deterministic correctness check failed; do not treat throughput as a valid win
- **bist-investment-agent (KAP web only) / Company-list HTML replay:** deterministic correctness check failed; do not treat throughput as a valid win
- **bist-investment-agent (KAP web only) / Company-list HTML replay:** deterministic correctness check failed; do not treat throughput as a valid win
- **bist-investment-agent (KAP web only) / Company-list HTML replay:** deterministic correctness check failed; do not treat throughput as a valid win
- **kap-tr-sdk / Bundled registry load:** repository has no bundled offline company registry
- **kap-tr-sdk / Bundled registry load:** repository has no bundled offline company registry
- **kap-tr-sdk / Bundled registry load:** repository has no bundled offline company registry
- **kap-tr-sdk / Bundled registry load:** repository has no bundled offline company registry
- **kap-tr-sdk / Bundled registry load:** repository has no bundled offline company registry
- **bist-investment-agent (KAP web only) / Bundled registry load:** repository has no bundled offline company registry
- **bist-investment-agent (KAP web only) / Bundled registry load:** repository has no bundled offline company registry
- **bist-investment-agent (KAP web only) / Bundled registry load:** repository has no bundled offline company registry
- **bist-investment-agent (KAP web only) / Bundled registry load:** repository has no bundled offline company registry
- **bist-investment-agent (KAP web only) / Bundled registry load:** repository has no bundled offline company registry
- **kap-tr-sdk / Exact ticker lookup (offline):** repository has no public offline exact-ticker lookup
- **kap-tr-sdk / Exact ticker lookup (offline):** repository has no public offline exact-ticker lookup
- **kap-tr-sdk / Exact ticker lookup (offline):** repository has no public offline exact-ticker lookup
- **kap-tr-sdk / Exact ticker lookup (offline):** repository has no public offline exact-ticker lookup
- **kap-tr-sdk / Exact ticker lookup (offline):** repository has no public offline exact-ticker lookup
- **bist-investment-agent (KAP web only) / Exact ticker lookup (offline):** repository has no public offline exact-ticker lookup
- **bist-investment-agent (KAP web only) / Exact ticker lookup (offline):** repository has no public offline exact-ticker lookup
- **bist-investment-agent (KAP web only) / Exact ticker lookup (offline):** repository has no public offline exact-ticker lookup
- **bist-investment-agent (KAP web only) / Exact ticker lookup (offline):** repository has no public offline exact-ticker lookup
- **bist-investment-agent (KAP web only) / Exact ticker lookup (offline):** repository has no public offline exact-ticker lookup
- **pykap / Exact ticker lookup (warm cache):** repository has no comparable warm-cache exact lookup
- **pykap / Exact ticker lookup (warm cache):** repository has no comparable warm-cache exact lookup
- **pykap / Exact ticker lookup (warm cache):** repository has no comparable warm-cache exact lookup
- **pykap / Exact ticker lookup (warm cache):** repository has no comparable warm-cache exact lookup
- **pykap / Exact ticker lookup (warm cache):** repository has no comparable warm-cache exact lookup
- **bist-investment-agent (KAP web only) / Exact ticker lookup (warm cache):** repository has no comparable warm-cache exact lookup
- **bist-investment-agent (KAP web only) / Exact ticker lookup (warm cache):** repository has no comparable warm-cache exact lookup
- **bist-investment-agent (KAP web only) / Exact ticker lookup (warm cache):** repository has no comparable warm-cache exact lookup
- **bist-investment-agent (KAP web only) / Exact ticker lookup (warm cache):** repository has no comparable warm-cache exact lookup
- **bist-investment-agent (KAP web only) / Exact ticker lookup (warm cache):** repository has no comparable warm-cache exact lookup
- **pykap / Async HTTP client soak (local server):** local async HTTP soak is implemented for kap
- **pykap / Async HTTP client soak (local server):** local async HTTP soak is implemented for kap
- **pykap / Async HTTP client soak (local server):** local async HTTP soak is implemented for kap
- **pykap / Async HTTP client soak (local server):** local async HTTP soak is implemented for kap
- **pykap / Async HTTP client soak (local server):** local async HTTP soak is implemented for kap
- **kap-tr-sdk / Async HTTP client soak (local server):** local async HTTP soak is implemented for kap
- **kap-tr-sdk / Async HTTP client soak (local server):** local async HTTP soak is implemented for kap
- **kap-tr-sdk / Async HTTP client soak (local server):** local async HTTP soak is implemented for kap
- **kap-tr-sdk / Async HTTP client soak (local server):** local async HTTP soak is implemented for kap
- **kap-tr-sdk / Async HTTP client soak (local server):** local async HTTP soak is implemented for kap
- **bist-investment-agent (KAP web only) / Async HTTP client soak (local server):** local async HTTP soak is implemented for kap
- **bist-investment-agent (KAP web only) / Async HTTP client soak (local server):** local async HTTP soak is implemented for kap
- **bist-investment-agent (KAP web only) / Async HTTP client soak (local server):** local async HTTP soak is implemented for kap
- **bist-investment-agent (KAP web only) / Async HTTP client soak (local server):** local async HTTP soak is implemented for kap
- **bist-investment-agent (KAP web only) / Async HTTP client soak (local server):** local async HTTP soak is implemented for kap

## Method

Each repository/scenario/load runs in a fresh subprocess. Timed regions exclude harness startup and adapter setup. Offline high-load runs never contact KAP. Live runs are opt-in, low-intensity, and guarded by a parent-process timeout. `Correct` validates the returned ticker set for the deterministic replay fixture; speed without correct output is not treated as a win.
