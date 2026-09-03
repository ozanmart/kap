from __future__ import annotations

import hashlib
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from benchmarks.scoring import render_methodology, render_scoreboard, score_results


REPO_LABELS = {
    "kap": "kap (current)",
    "pykap": "pykap",
    "kap_tr_sdk": "kap-tr-sdk",
}

SCENARIO_LABELS = {
    "cold_import": "Cold API import",
    "package_import": "Package import",
    "client_ready": "Client construction",
    "first_offline_lookup": "First offline lookup",
    "warm_lookup": "Warm lookup",
    "first_live_request": "First live request",
    "listing_replay": "Company-list HTML replay",
    "offline_registry": "Bundled registry load",
    "offline_exact_lookup": "Exact ticker lookup (offline)",
    "warm_cache_exact_lookup": "Exact ticker lookup (warm cache)",
    "async_http_soak": "Async HTTP client soak (local server)",
    "profile_replay": "Company-profile HTML replay",
    "feed_normalize": "Disclosure-feed normalization replay",
    "live_feed": "Live public disclosure feed",
    "live_registry": "Live public company registry",
}

OFFLINE_LOADS = {
    "smoke": [1, 5],
    "standard": [1, 5, 10, 25, 50],
    "stress": [1, 5, 10, 25, 50, 100, 1_000],
}


def percentile(values: list[float], percent: float) -> float | None:
    """Return a linearly interpolated percentile for already measured samples."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percent
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def summarize_latencies(samples_ms: list[float]) -> dict[str, float | None]:
    if not samples_ms:
        return {
            "mean_ms": None,
            "min_ms": None,
            "p50_ms": None,
            "p95_ms": None,
            "p99_ms": None,
            "max_ms": None,
            "stddev_ms": None,
        }
    return {
        "mean_ms": statistics.fmean(samples_ms),
        "min_ms": min(samples_ms),
        "p50_ms": percentile(samples_ms, 0.50),
        "p95_ms": percentile(samples_ms, 0.95),
        "p99_ms": percentile(samples_ms, 0.99),
        "max_ms": max(samples_ms),
        "stddev_ms": statistics.pstdev(samples_ms),
    }


def stable_digest(values: Iterable[str]) -> str:
    canonical = "\n".join(sorted(str(value) for value in values))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    meta = report["meta"]
    rows = report["results"]
    lines = [
        "# KAP three-repository benchmark",
        "",
        f"Generated: `{meta['generated_at_utc']}`<br>",
        f"Interpreter: `{meta['python_executable']}` ({meta['python_version']})<br>",
        f"Profile: `{meta['profile']}`; live: `{str(meta['live']).lower()}`",
        "",
        "## Scoreboard",
        "",
    ]
    lines.extend(render_scoreboard(score_results(rows), REPO_LABELS))
    lines.extend(["", "<details>", "<summary>How the KAP Index is computed</summary>", ""])
    lines.extend(render_methodology())
    lines.extend([
        "",
        "</details>",
        "",
        "## Results",
        "",
        "| Repository | Scenario | Load | Status | min | p50 | p95 | p99 | max | mean | σ ms | ops/s | err % | timeout % | RSS MB | Items | Correct |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ])
    for row in rows:
        lines.append(
            "| {repo} | {scenario} | {load} | {status} | {min} | {p50} | {p95} | {p99} | {max} | {mean} | {stddev} | {ops} | {error_rate} | {timeout_rate} | {rss} | {items} | {correct} |".format(
                repo=REPO_LABELS.get(row["repo"], row["repo"]),
                scenario=SCENARIO_LABELS.get(row["scenario"], row["scenario"]),
                load=row.get("iterations", "—"),
                status=row["status"],
                min=_fmt(row.get("min_ms")),
                p50=_fmt(row.get("p50_ms")),
                p95=_fmt(row.get("p95_ms")),
                p99=_fmt(row.get("p99_ms")),
                max=_fmt(row.get("max_ms")),
                mean=_fmt(row.get("mean_ms")),
                stddev=_fmt(row.get("stddev_ms")),
                ops=_fmt(row.get("throughput_ops_s")),
                error_rate=_fmt(100 * float(row.get("error_rate", 0.0))),
                timeout_rate=_fmt(100 * float(row.get("timeout_rate", 0.0))),
                rss=_fmt(row.get("peak_rss_mb")),
                items=_fmt(row.get("item_count"), 0),
                correct=("yes" if row.get("correct") is True else "no" if row.get("correct") is False else "—"),
            )
        )

    lines.extend(["", "## Capability and error notes", ""])
    notes = 0
    for row in rows:
        if row["status"] != "ok" or row.get("warning") or row.get("error"):
            notes += 1
            reason = row.get("error") or row.get("warning") or row.get("skip_reason") or "unknown"
            lines.append(
                f"- **{REPO_LABELS.get(row['repo'], row['repo'])} / "
                f"{SCENARIO_LABELS.get(row['scenario'], row['scenario'])}:** {reason}"
            )
        elif row.get("request_metrics"):
            notes += 1
            metrics = row["request_metrics"]
            lines.append(
                f"- **{REPO_LABELS.get(row['repo'], row['repo'])} / "
                f"{SCENARIO_LABELS.get(row['scenario'], row['scenario'])} phases:** "
                f"fetch={_fmt(metrics.get('fetch_s'))}s, "
                f"ttfb={_fmt(metrics.get('ttfb_s'))}s, "
                f"download={_fmt(metrics.get('download_s'))}s, "
                f"parse={_fmt(metrics.get('parse_s'))}s, "
                f"total={_fmt(metrics.get('total_s'))}s"
            )
    if not notes:
        lines.append("- No skips, warnings, or errors.")

    lines.extend(
        [
            "",
            "## Method",
            "",
            "Each repository/scenario/load runs in a fresh subprocess. Timed regions exclude harness startup and adapter setup. "
            "Offline high-load runs never contact KAP. Live runs are opt-in, low-intensity, and guarded by a parent-process timeout. "
            "`Correct` validates the returned ticker set for the deterministic replay fixture; speed without correct output is not treated as a win.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report.setdefault("scores", [item.to_dict() for item in score_results(report["results"])])
    stamp = report["meta"]["run_id"]
    json_path = output_dir / f"benchmark-{stamp}.json"
    md_path = output_dir / f"benchmark-{stamp}.md"
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    rendered = render_markdown(report)
    json_path.write_text(encoded, encoding="utf-8")
    md_path.write_text(rendered, encoding="utf-8")
    (output_dir / "latest.json").write_text(encoded, encoding="utf-8")
    (output_dir / "latest.md").write_text(rendered, encoding="utf-8")
    return json_path, md_path


def runtime_meta(python_executable: str, profile: str, live: bool) -> dict[str, Any]:
    return {
        "run_id": utc_stamp(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_executable": Path(python_executable).name,
        "python_version": sys.version.split()[0],
        "profile": profile,
        "live": live,
        "network_policy": "opt-in, public kap.org.tr only; no MKK endpoints",
    }
