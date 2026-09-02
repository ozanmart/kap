from __future__ import annotations

from benchmarks.core import percentile, render_markdown, stable_digest, summarize_latencies
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


def test_explicit_virtualenv_interpreter_path_is_not_resolved() -> None:
    interpreter = "/Users/omerozanmart/Desktop/kap/.venv/bin/python"
    assert select_python(interpreter) == interpreter
