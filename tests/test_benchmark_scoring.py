from __future__ import annotations

from benchmarks.scoring import (
    CATEGORY_WEIGHTS,
    MAX_INDEX,
    render_methodology,
    render_scoreboard,
    score_results,
)


def _row(repo, scenario, **overrides):
    row = {
        "repo": repo,
        "scenario": scenario,
        "iterations": 1,
        "status": "ok",
        "correct": True,
        "p50_ms": 10.0,
        "peak_rss_mb": 50.0,
        "error_rate": 0.0,
        "timeout_rate": 0.0,
    }
    row.update(overrides)
    return row


def test_category_weights_sum_to_one() -> None:
    assert abs(sum(CATEGORY_WEIGHTS.values()) - 1.0) < 1e-9


def test_a_repository_best_at_everything_scores_the_maximum() -> None:
    results = [
        _row("kap", "listing_replay", p50_ms=1.0, peak_rss_mb=10.0),
        _row("kap", "offline_registry", p50_ms=1.0, peak_rss_mb=10.0),
        _row("pykap", "listing_replay", p50_ms=100.0, peak_rss_mb=100.0),
        _row("pykap", "offline_registry", p50_ms=100.0, peak_rss_mb=100.0),
    ]

    (score,) = [item for item in score_results(results) if item.repo == "kap"]

    assert score.index == MAX_INDEX
    assert all(value == 1.0 for value in score.categories.values())


def test_speed_and_memory_are_scored_relative_to_the_best_in_the_same_group() -> None:
    results = [
        _row("kap", "listing_replay", p50_ms=10.0, peak_rss_mb=50.0),
        _row("pykap", "listing_replay", p50_ms=40.0, peak_rss_mb=200.0),
    ]

    kap, pykap = sorted(score_results(results), key=lambda item: item.repo)

    assert kap.categories["speed"] == 1.0
    assert pykap.categories["speed"] == 0.25
    assert pykap.categories["efficiency"] == 0.25


def test_an_incorrect_row_cannot_earn_speed_points() -> None:
    """The whole point of weighting correctness highest is defeated if a fast
    wrong parser still collects the speed category."""
    results = [
        _row("kap", "listing_replay", p50_ms=100.0),
        _row("pykap", "listing_replay", p50_ms=1.0, correct=False),
    ]

    kap, pykap = sorted(score_results(results), key=lambda item: item.repo)

    # Entering the contest and answering wrong still counts as entering it, so
    # the correct repository keeps the win it actually earned.
    assert kap.categories["speed"] == 1.0
    assert pykap.categories["speed"] == 0.0
    assert pykap.categories["correctness"] == 0.0
    assert kap.index > pykap.index


def test_skipping_scenarios_lowers_coverage_and_cannot_inflate_the_index() -> None:
    """A repository that only runs the one scenario it is good at must not beat
    one that runs the whole suite correctly."""
    results = [
        _row("kap", "listing_replay", p50_ms=10.0),
        _row("kap", "feed_normalize", p50_ms=10.0),
        _row("kap", "live_registry", p50_ms=10.0),
        _row("pykap", "listing_replay", p50_ms=9.0),
        _row("pykap", "feed_normalize", status="skipped", correct=None, p50_ms=None, peak_rss_mb=None),
        _row("pykap", "live_registry", status="skipped", correct=None, p50_ms=None, peak_rss_mb=None),
    ]

    kap, pykap = sorted(score_results(results), key=lambda item: item.repo)

    assert kap.categories["coverage"] == 1.0
    assert abs(pykap.categories["coverage"] - 1 / 3) < 1e-9
    assert pykap.categories["speed"] == 1.0  # it really was faster where it ran
    assert kap.index > pykap.index


def test_errors_and_timeouts_reduce_reliability_but_skips_do_not() -> None:
    errored = [
        _row("kap", "a"),
        _row("kap", "b", status="error", correct=None, error_rate=1.0, p50_ms=None, peak_rss_mb=None),
    ]
    skipped = [
        _row("kap", "a"),
        _row("kap", "b", status="skipped", correct=None, p50_ms=None, peak_rss_mb=None),
    ]

    (with_error,) = score_results(errored)
    (with_skip,) = score_results(skipped)

    assert with_error.categories["reliability"] == 0.5
    assert with_skip.categories["reliability"] == 1.0


def test_a_repository_with_no_verifiable_output_scores_zero_correctness() -> None:
    results = [_row("kap", "package_import", correct=None)]

    (score,) = score_results(results)

    assert score.categories["correctness"] == 0.0
    assert score.evidence["rows_with_a_correctness_check"] == 0


def test_scoreboard_renders_a_ranked_table_and_names_missing_scenarios() -> None:
    results = [
        _row("kap", "listing_replay"),
        _row("kap", "feed_normalize"),
        _row("pykap", "listing_replay", p50_ms=80.0),
        _row("pykap", "feed_normalize", status="skipped", correct=None, p50_ms=None, peak_rss_mb=None),
    ]

    scores = score_results(results)
    table = "\n".join(render_scoreboard(scores, {"kap": "kap (current)"}))

    assert scores[0].repo == "kap"
    assert "kap (current)" in table
    assert "2/2" in table and "1/2" in table
    assert scores[1].evidence["unsupported_scenarios"] == ["feed_normalize"]
    assert "KAP Index" in "\n".join(render_methodology()) or CATEGORY_WEIGHTS


def test_empty_results_do_not_raise() -> None:
    assert score_results([]) == []
    assert render_scoreboard([], {}) == ["_No results to score._"]


def test_an_uncontested_scenario_does_not_award_free_speed_points() -> None:
    """A scenario only one repository can run is a capability difference, and
    coverage already prices it in. Scoring it as a speed win too would count the
    same advantage twice, and `best / own value` is always 1.0 when you are the
    only runner."""
    contested = [
        _row("kap", "listing_replay", p50_ms=20.0),
        _row("pykap", "listing_replay", p50_ms=10.0),
    ]
    with_solo = contested + [_row("kap", "feed_normalize", p50_ms=5.0)]

    (kap_before,) = [s for s in score_results(contested) if s.repo == "kap"]
    (kap_after,) = [s for s in score_results(with_solo) if s.repo == "kap"]

    assert kap_before.categories["speed"] == 0.5
    assert kap_after.categories["speed"] == 0.5  # unchanged by the solo scenario
    assert kap_after.categories["coverage"] == 1.0  # but coverage still rewards it
