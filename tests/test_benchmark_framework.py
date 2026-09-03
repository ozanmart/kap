from __future__ import annotations

import sys

from benchmarks.core import percentile, render_markdown, runtime_meta, stable_digest, summarize_latencies
from benchmarks.adapters import LIVE_REGISTRY_MIN_TICKERS, _live_registry_result, _warm_cache_exact_lookup
from benchmarks.run import aggregate_cold_imports, select_python


def test_percentile_and_summary_are_deterministic() -> None:
    values = [4.0, 1.0, 3.0, 2.0]
    assert percentile(values, 0.50) == 2.5
    summary = summarize_latencies(values)
    assert summary["min_ms"] == 1.0
    assert summary["p50_ms"] == 2.5
    assert summary["max_ms"] == 4.0


def test_digest_is_order_independent() -> None:
    assert stable_digest(["THYAO", "BIMAS"]) == stable_digest(["BIMAS", "THYAO"])


def test_markdown_exposes_incorrect_results_and_skip_reason() -> None:
    report = {
        "meta": {
            "generated_at_utc": "2026-09-02T00:00:00+00:00",
            "python_executable": "/python",
            "python_version": "3.13",
            "profile": "smoke",
            "live": False,
        },
        "results": [
            {
                "repo": "kap_tr_sdk",
                "scenario": "listing_replay",
                "iterations": 1,
                "status": "ok",
                "p50_ms": 1.0,
                "p95_ms": 1.0,
                "throughput_ops_s": 1000.0,
                "peak_rss_mb": 50.0,
                "item_count": 0,
                "correct": False,
                "warning": "fixture parser returned no rows",
            },
            {
                "repo": "bist_agent",
                "scenario": "offline_registry",
                "iterations": 1,
                "status": "skipped",
                "skip_reason": "no bundled registry",
            },
        ],
    }
    rendered = render_markdown(report)
    assert "| no |" in rendered
    assert "fixture parser returned no rows" in rendered
    assert "no bundled registry" in rendered
    assert all(not line.endswith(" ") for line in rendered.splitlines())


def test_cold_imports_are_aggregated_across_processes() -> None:
    rows = [
        {
            "repo": "kap",
            "scenario": "cold_import",
            "iterations": 1,
            "status": "ok",
            "mean_ms": value,
            "peak_rss_mb": 10.0 + value,
        }
        for value in (10.0, 20.0, 30.0)
    ]
    aggregate = aggregate_cold_imports(rows)[0]
    assert aggregate["iterations"] == 3
    assert aggregate["p50_ms"] == 20.0
    assert aggregate["p95_ms"] == 29.0
    assert aggregate["peak_rss_mb"] == 40.0


def test_explicit_virtualenv_interpreter_path_is_not_resolved(tmp_path) -> None:
    # GitHub Actions uses setup-python directly and does not create the
    # developer-only repository .venv. Build the same launcher shape locally so
    # this regression test is independent of a machine-specific checkout.
    launcher = tmp_path / "venv" / "bin" / "python"
    launcher.parent.mkdir(parents=True)
    try:
        launcher.symlink_to(sys.executable)
        interpreter = str(launcher)
    except OSError:
        # Symlink creation can be disabled on some platforms; an existing
        # interpreter still verifies that select_python preserves its path.
        interpreter = sys.executable
    assert select_python(interpreter) == interpreter


def test_benchmark_runtime_metadata_does_not_leak_local_paths() -> None:
    metadata = runtime_meta("/Users/example/.cache/kap/venv/bin/python", "smoke", False)
    assert metadata["python_executable"] == "python"


def test_live_registry_correctness_rejects_incomplete_but_plausible_snapshot() -> None:
    references = ["THYAO", "BIMAS", "GARAN", "ACSEL", "A1CAP", "ACP"]
    incomplete = references + [f"X{i:04d}" for i in range(LIVE_REGISTRY_MIN_TICKERS - 7)]
    assert len(incomplete) == LIVE_REGISTRY_MIN_TICKERS - 1
    result = _live_registry_result(incomplete)
    assert result["item_count"] == LIVE_REGISTRY_MIN_TICKERS - 1
    assert result["correct"] is False
    assert result["validation"]["minimum_count"] == LIVE_REGISTRY_MIN_TICKERS


def test_live_registry_correctness_accepts_complete_valid_snapshot() -> None:
    references = ["THYAO", "BIMAS", "GARAN", "ACSEL", "A1CAP", "ACP"]
    complete = references + [f"X{i:04d}" for i in range(LIVE_REGISTRY_MIN_TICKERS - len(references))]
    result = _live_registry_result(complete)
    assert result["item_count"] == LIVE_REGISTRY_MIN_TICKERS
    assert result["correct"] is True


def test_current_warm_cache_benchmark_does_not_fall_through_to_source() -> None:
    operation = _warm_cache_exact_lookup("kap")
    try:
        result = operation.invoke()
    finally:
        operation.close()

    assert result["correct"] is True
    assert result["item_count"] == 1
