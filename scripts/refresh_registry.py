"""Refresh the bundled KAP company registry from the public registry endpoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kap import KapClient, KapConfig


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "src" / "kap" / "data" / "bist_companies_general.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-records", type=int, default=750)
    args = parser.parse_args()

    config = KapConfig.for_profile(
        "resilient",
        enable_cache=False,
        registry_min_records=args.min_records,
        registry_require_company_ids=True,
    )
    with KapClient(config) as client:
        companies = client.listings.refresh_registry(str(args.output))
        metadata_path = args.output.with_suffix(".meta.json")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    print(
        json.dumps(
            {
                "output": str(args.output),
                "count": len(companies),
                "metadata": metadata,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
