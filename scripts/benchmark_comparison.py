"""Compatibility entry point for the isolated four-repository benchmark.

Prefer: ``python -m benchmarks.run --profile standard``.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.run import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

