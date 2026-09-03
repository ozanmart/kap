"""Composite scoring for the four-repository KAP benchmark.

The per-row table answers "how fast was this one call". It does not answer the
question a reader actually has, which is whether a library is a reasonable
choice overall. A library that parses one page quickly but cannot fetch a
disclosure at all, or returns the wrong tickers, should not look good next to
one that does the whole job correctly.

This module reduces the measured rows to one **KAP Index** per repository on a
0-1000 scale, plus the five category subscores it is built from. Every category
is derived only from measurements already present in the report; nothing here
introduces a new opinion about the repositories beyond the published weights.

Design rules that keep the number honest:

* Correctness is the heaviest category, and a row whose output failed its
  deterministic check is excluded from the speed and memory comparisons
  entirely. A fast wrong parser cannot buy points with its speed.
* Speed and memory are scored *relatively*, per scenario and load, against the
  best repository in that same group. Absolute milliseconds from different
  scenarios are never averaged together.
* Coverage is measured against the scenarios the benchmark actually attempted,
  so adding a scenario no repository supports changes nobody's score, and a
  repository is never penalized for a category it was not asked to run.
* A repository that skips a scenario scores nothing for it in coverage, but its
  speed and memory averages are taken only over what it did run. Skipping the
  hard half of the suite therefore cannot inflate the remaining averages into a
  better index than a repository that did all of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

MAX_INDEX = 1000

#: Category weights. They sum to 1.0; the index is MAX_INDEX times the weighted
#: sum of the category scores.
CATEGORY_WEIGHTS: dict[str, float] = {
    "correctness": 0.35,
    "coverage": 0.20,
    "speed": 0.20,
    "reliability": 0.15,
    "efficiency": 0.10,
}

CATEGORY_LABELS: dict[str, str] = {
    "correctness": "Correctness",
    "coverage": "Capability coverage",
    "speed": "Relative speed",
    "reliability": "Reliability",
    "efficiency": "Memory efficiency",
}


@dataclass
class RepoScore:
    """One repository's index and the evidence behind it."""

    repo: str
    index: int
    categories: dict[str, float]
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "index": self.index,
            "categories": {name: round(value, 4) for name, value in self.categories.items()},
            "evidence": self.evidence,
        }


def _is_attempted(row: dict[str, Any]) -> bool:
    """A skipped row means the capability is absent, not that a run failed."""
    return row.get("status") != "skipped"


def _is_usable(row: dict[str, Any]) -> bool:
    """Rows eligible for the speed and memory comparisons."""
    return row.get("status") == "ok" and row.get("correct") is not False


def _group_key(row: dict[str, Any]) -> tuple[str, Any]:
    return (str(row.get("scenario")), row.get("iterations"))


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _relative_scores(
    rows: Iterable[dict[str, Any]],
    metric: str,
) -> dict[str, list[float]]:
    """Score each repository against the best value in its own scenario/load group.

    Lower is better for every metric here (latency, resident memory), so the
    score is ``best / observed`` and lands in ``(0, 1]``.
    """
    groups: dict[tuple[str, Any], dict[str, float]] = {}
    for row in rows:
        if not _is_usable(row):
            continue
        value = _positive(row.get(metric))
        if value is None:
            continue
        groups.setdefault(_group_key(row), {})[str(row.get("repo"))] = value

    per_repo: dict[str, list[float]] = {}
    for observations in groups.values():
        best = min(observations.values())
        for repo, value in observations.items():
            per_repo.setdefault(repo, []).append(best / value)
    return per_repo


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def score_results(results: list[dict[str, Any]]) -> list[RepoScore]:
    """Reduce benchmark rows to one ranked index per repository."""
    repos = sorted({str(row.get("repo")) for row in results if row.get("repo")})
    if not repos:
        return []

    # Scenarios the benchmark actually attempted for at least one repository.
    universe = sorted({str(row.get("scenario")) for row in results if row.get("scenario")})
    supported: dict[str, set[str]] = {repo: set() for repo in repos}
    for row in results:
        if row.get("status") == "ok":
            supported[str(row["repo"])].add(str(row["scenario"]))

    speed = _relative_scores(results, "p50_ms")
    efficiency = _relative_scores(results, "peak_rss_mb")

    scores: list[RepoScore] = []
    for repo in repos:
        rows = [row for row in results if str(row.get("repo")) == repo]
        attempted = [row for row in rows if _is_attempted(row)]
        verifiable = [row for row in rows if row.get("status") == "ok" and row.get("correct") is not None]
        passed = [row for row in verifiable if row.get("correct") is True]

        failure_rates = [
            float(row.get("error_rate") or 0.0) + float(row.get("timeout_rate") or 0.0)
            for row in attempted
        ]
        categories = {
            "correctness": len(passed) / len(verifiable) if verifiable else 0.0,
            "coverage": len(supported[repo]) / len(universe) if universe else 0.0,
            "speed": _mean(speed.get(repo, [])),
            "reliability": max(0.0, 1.0 - _mean(failure_rates)) if attempted else 0.0,
            "efficiency": _mean(efficiency.get(repo, [])),
        }
        index = round(MAX_INDEX * sum(CATEGORY_WEIGHTS[name] * value for name, value in categories.items()))
        scores.append(
            RepoScore(
                repo=repo,
                index=index,
                categories=categories,
                evidence={
                    "scenarios_supported": len(supported[repo]),
                    "scenarios_in_suite": len(universe),
                    "rows_attempted": len(attempted),
                    "rows_verified_correct": len(passed),
                    "rows_with_a_correctness_check": len(verifiable),
                    "unsupported_scenarios": sorted(set(universe) - supported[repo]),
                },
            )
        )

    scores.sort(key=lambda item: item.index, reverse=True)
    return scores


def render_scoreboard(scores: list[RepoScore], labels: dict[str, str]) -> list[str]:
    """Render the headline scoreboard as Markdown lines."""
    if not scores:
        return ["_No results to score._"]

    header = " | ".join(CATEGORY_LABELS[name] for name in CATEGORY_WEIGHTS)
    weights = " | ".join(f"{CATEGORY_WEIGHTS[name]:.0%}" for name in CATEGORY_WEIGHTS)
    lines = [
        f"| # | Repository | **KAP Index** | {header} | Scenarios |",
        "|---:|---|---:|" + "---:|" * len(CATEGORY_WEIGHTS) + "---|",
        f"| | _weight_ | _/{MAX_INDEX}_ | {weights} | |",
    ]
    for rank, score in enumerate(scores, start=1):
        cells = " | ".join(f"{score.categories[name]:.2f}" for name in CATEGORY_WEIGHTS)
        evidence = score.evidence
        coverage = f"{evidence.get('scenarios_supported', 0)}/{evidence.get('scenarios_in_suite', 0)}"
        lines.append(
            f"| {rank} | {labels.get(score.repo, score.repo)} | **{score.index}** | {cells} | {coverage} |"
        )
    return lines


def render_methodology() -> list[str]:
    """Render the fixed explanation of how the index is produced."""
    return [
        f"The **KAP Index** is a single 0-{MAX_INDEX} number per repository: "
        f"{MAX_INDEX} means best-in-suite on every category at once. It is the weighted sum of "
        "five category scores, each derived only from the measurements in the table above.",
        "",
        "| Category | Weight | Definition |",
        "|---|---:|---|",
        f"| Correctness | {CATEGORY_WEIGHTS['correctness']:.0%} | Share of the repository's own runs that passed "
        "their deterministic output check. |",
        f"| Capability coverage | {CATEGORY_WEIGHTS['coverage']:.0%} | Share of the suite's scenarios the repository "
        "can perform at all. A scenario it cannot do is not an average it gets to skip. |",
        f"| Relative speed | {CATEGORY_WEIGHTS['speed']:.0%} | Per scenario and load, `fastest p50 / this p50`, "
        "averaged. Milliseconds are never compared across different scenarios. |",
        f"| Reliability | {CATEGORY_WEIGHTS['reliability']:.0%} | `1 - (error rate + timeout rate)` over everything "
        "the repository attempted. |",
        f"| Memory efficiency | {CATEGORY_WEIGHTS['efficiency']:.0%} | Per scenario and load, "
        "`lowest peak RSS / this peak RSS`, averaged. |",
        "",
        "A row whose output failed its correctness check is dropped from the speed and memory "
        "comparisons, so a fast but wrong parser cannot earn points for being fast.",
    ]
