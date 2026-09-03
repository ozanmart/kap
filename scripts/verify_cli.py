"""Exercise the source or installed KAP CLI with serial public-KAP calls."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


def _run(command: list[str], env: dict[str, str], *, expect: int = 0) -> tuple[str, float]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    elapsed = round(time.perf_counter() - started, 6)
    if completed.returncode != expect:
        output = (completed.stderr or completed.stdout).strip().replace("\n", " ")
        raise AssertionError(f"exit={completed.returncode}, expected={expect}: {output[:400]}")
    return completed.stdout, elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default="python", help="Python executable whose kap package is under test")
    parser.add_argument("--disclosure-index", type=int, default=1657514)
    parser.add_argument("--financial-year", type=int, default=2025)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    prefix = [args.python, "-m", "kap"]
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="kap-cli-verification-") as cache_dir:
        env = {**os.environ, "XDG_CACHE_HOME": cache_dir}

        output, elapsed = _run(prefix + ["search", "THYAO"], env)
        assert "THYAO" in output
        results.append({"name": "company_search", "status": "passed", "elapsed_s": elapsed})

        output, elapsed = _run(prefix + ["today", "--json-out"], env)
        today = json.loads(output)
        assert isinstance(today, list)
        results.append({"name": "today", "status": "passed", "elapsed_s": elapsed, "count": len(today)})

        output, elapsed = _run(prefix + ["disclosures", "GARAN", "--days", "365", "--limit", "3"], env)
        assert "Historical Announcements for GARAN" in output
        results.append({"name": "company_disclosures", "status": "passed", "elapsed_s": elapsed})

        output, elapsed = _run(
            prefix + ["detail", str(args.disclosure_index), "--max-chars", "500", "--json-out"],
            env,
        )
        detail = json.loads(output)
        assert detail["disclosure_index"] == args.disclosure_index
        assert detail["title"] and detail["publish_date"] and detail["content_text"]
        results.append({"name": "disclosure_detail", "status": "passed", "elapsed_s": elapsed})

        output, elapsed = _run(
            prefix + ["financials", "THYAO", "--year", str(args.financial_year), "--period", "annual", "--json-out"],
            env,
        )
        financials = json.loads(output)
        assert financials["stock_code"] == "THYAO" and len(financials["items"]) >= 100
        results.append({
            "name": "financials",
            "status": "passed",
            "elapsed_s": elapsed,
            "items": len(financials["items"]),
        })

        output, elapsed = _run(prefix + ["calendar", "--ticker", "THYAO", "--days", "180"], env)
        assert "THYAO" in output
        results.append({"name": "calendar", "status": "passed", "elapsed_s": elapsed})

        output, elapsed = _run(prefix + ["taxonomy", "indices", "--json-out"], env)
        indices = json.loads(output)
        xu100 = next(row for row in indices if row["code"] == "XU100")
        assert "THYAO" in xu100["companies"]
        results.append({"name": "taxonomy", "status": "passed", "elapsed_s": elapsed, "count": len(indices)})

        output, elapsed = _run(prefix + ["detail", "0"], env, expect=2)
        assert "Traceback" not in output
        results.append({"name": "invalid_input", "status": "passed", "elapsed_s": elapsed})

    report = {"status": "passed", "results": results}
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
