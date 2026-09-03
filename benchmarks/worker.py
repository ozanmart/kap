from __future__ import annotations

import argparse
import gc
import json
import resource
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from benchmarks.adapters import UnsupportedScenario, build_operation, configure_source_path, import_target
from benchmarks.core import summarize_latencies


def peak_rss_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = configure_source_path(args.repo, Path(args.repo_root) if args.repo_root else None)
    base: dict[str, Any] = {
        "repo": args.repo,
        # Reports may be committed or shared; keep local checkout paths out of
        # the artifact while retaining the useful repository label.
        "repo_root": root.name,
        "scenario": args.scenario,
        "iterations": args.iterations,
        "warmups": args.warmups,
        "status": "ok",
        "python_version": sys.version.split()[0],
    }
    operation = None
    try:
        if args.scenario == "cold_import":
            gc.collect()
            start = time.perf_counter_ns()
            result = import_target(args.repo)
            samples_ms = [(time.perf_counter_ns() - start) / 1_000_000]
            implementation = "documented/top-level usable API import"
        else:
            operation = build_operation(args.repo, args.scenario, Path(args.fixture))
            implementation = operation.implementation
            for _ in range(args.warmups):
                operation.invoke()
            gc.collect()
            samples_ms = []
            result = {}
            start_total = time.perf_counter_ns()
            for _ in range(args.iterations):
                start = time.perf_counter_ns()
                result = operation.invoke()
                samples_ms.append((time.perf_counter_ns() - start) / 1_000_000)
            total_s = (time.perf_counter_ns() - start_total) / 1_000_000_000
            base["measured_seconds"] = total_s
            base["throughput_ops_s"] = args.iterations / total_s if total_s else None

        base.update(summarize_latencies(samples_ms))
        base["error_rate"] = 0.0
        base["timeout_rate"] = 0.0
        base.update(result)
        if result.get("correct") is False:
            base["warning"] = "deterministic correctness check failed; do not treat throughput as a valid win"
        base["implementation"] = implementation
        base["peak_rss_mb"] = peak_rss_mb()
        return base
    except UnsupportedScenario as exc:
        base.update({"status": "skipped", "skip_reason": str(exc), "peak_rss_mb": peak_rss_mb()})
        return base
    except ModuleNotFoundError as exc:
        base.update(
            {
                "status": "skipped",
                "skip_reason": f"missing dependency: {exc.name}",
                "peak_rss_mb": peak_rss_mb(),
            }
        )
        return base
    except PermissionError as exc:
        base.update(
            {
                "status": "skipped",
                "skip_reason": f"sandbox denied local benchmark socket: {exc}",
                "peak_rss_mb": peak_rss_mb(),
            }
        )
        return base
    except Exception as exc:
        base.update(
            {
                "status": "error",
                "error_rate": 1.0,
                "timeout_rate": 0.0,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=8),
                "peak_rss_mb": peak_rss_mb(),
            }
        )
        return base
    finally:
        if operation is not None:
            operation.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, choices=["kap", "pykap", "kap_tr_sdk", "bist_agent"])
    parser.add_argument("--repo-root")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--warmups", type=int, default=0)
    parser.add_argument("--fixture", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), ensure_ascii=False), flush=True)
