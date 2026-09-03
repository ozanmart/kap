"""Validate core SDK and agent-tool behavior against public kap.org.tr only.

This is an opt-in release gate. It intentionally sends a small, serial set of
requests and never calls MKK or another market-data provider.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from kap import AsyncKapClient, KapClient, KapConfig
from kap.scrapers.disclosures import _matches_ticker
from kap.tools import KapToolkit


def _timed(name: str, func: Callable[[], Any], checks: Callable[[Any], None]) -> tuple[Any, dict[str, Any]]:
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    try:
        value = func()
        checks(value)
    except Exception as exc:
        return None, {
            "name": name,
            "status": "failed",
            "started_at_utc": started_at,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_s": round(time.perf_counter() - started, 6),
            "error_type": type(exc).__name__,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return value, {
        "name": name,
        "status": "passed",
        "started_at_utc": started_at,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": round(time.perf_counter() - started, 6),
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _check_registry(rows: Any) -> None:
    _require(len(rows) >= 800, f"expected >=800 companies, got {len(rows)}")
    tickers = [row.ticker for row in rows]
    _require(len(tickers) == len(set(tickers)), "registry contains duplicate tickers")
    _require({"THYAO", "BIMAS", "GARAN", "ACSEL"}.issubset(tickers), "reference tickers missing")
    _require(all(re.fullmatch(r"[A-Z0-9]{2,6}", ticker) for ticker in tickers), "invalid ticker")


def _check_feed(rows: Any) -> None:
    _require(isinstance(rows, list), "today feed schema invalid")
    _require(
        all(
            hasattr(row, "disclosure_index")
            and hasattr(row, "title")
            and hasattr(row, "publish_date")
            for row in rows
        ),
        "today feed schema invalid",
    )
    _require(all(row.disclosure_index > 0 for row in rows), "feed contains invalid disclosure index")
    _require(all(row.title and row.publish_date for row in rows), "feed contains missing title/date")


def _check_historical(rows: Any) -> None:
    _require(bool(rows), "historical financial query is empty")
    _require(all(row.disclosure_index > 0 for row in rows), "historical rows contain invalid index")
    _require(all(row.title and row.company_title and row.publish_date for row in rows), "historical semantic fields missing")
    _require(all(row.disclosure_class == "FR" for row in rows), "historical class filter not preserved")


def _check_profile(info: Any) -> None:
    _require(info.ticker == "BIMAS", f"wrong ticker: {info.ticker}")
    _require(len(info.major_shareholders) >= 2, "BIMAS major shareholders missing")
    _require(isinstance(info.free_float, list), "free float schema invalid")
    _require(
        all(getattr(row, "float_ratio", None) is not None for row in info.free_float),
        "free float row missing ratio",
    )
    _require(len(info.subsidiaries) >= 5, "BIMAS subsidiaries incomplete")


def _check_financial(statement: Any, year: int) -> None:
    _require(statement.stock_code == "THYAO", f"wrong financial ticker: {statement.stock_code}")
    _require(len(statement.items) >= 100, f"financial statement too small: {len(statement.items)}")
    _require(any(str(year) in label for label in statement.period_labels), "requested year absent")
    _require(statement.currency == "TRY", f"unexpected currency: {statement.currency}")
    _require(statement.scale == 1_000_000, f"unexpected scale: {statement.scale}")


def _check_calendar(rows: Any) -> None:
    _require(bool(rows), "THYAO calendar is empty")
    _require(all(row.stock_code and "THYAO" in row.stock_code.split(", ") for row in rows), "calendar ticker mismatch")
    _require(all(row.start_date or row.end_date for row in rows), "calendar date missing")


def _check_taxonomy(kind: str, rows: Any) -> None:
    minimum = {"indices": 50, "sectors": 40, "markets": 5}[kind]
    _require(len(rows) >= minimum, f"{kind} unexpectedly small: {len(rows)}")
    if kind == "indices":
        xu100 = next((row for row in rows if row.code == "XU100"), None)
        _require(xu100 is not None and "THYAO" in xu100.companies, "XU100/THYAO membership missing")


def _validate_agent_tools(
    toolkit: KapToolkit,
    disclosure_index: int,
    financial_index: int,
    financial_year: int,
) -> dict[str, Any]:
    calls = {
        "kap_search_companies": {"query": "THYAO", "page_size": 2},
        "kap_get_company_info": {"ticker": "BIMAS"},
        "kap_get_today_disclosures": {"page_size": 1},
        "kap_get_company_disclosures": {"ticker": "GARAN", "limit": 3},
        "kap_get_disclosure_detail": {"disclosure_index": disclosure_index, "max_chars": 500},
        "kap_get_financial_statements": {"disclosure_index": financial_index, "ticker": "THYAO"},
        "kap_get_financials": {"ticker": "THYAO", "year": financial_year, "period": "annual"},
        "kap_get_expected_calendar": {"ticker": "THYAO", "days_ahead": 180, "page_size": 3},
        "kap_extract_disclosure_events": {
            "disclosure_index": disclosure_index,
            "ticker": "GARAN",
            "body_text": "Yönetim Kurulu pay geri alımına karar verdi.",
        },
        "kap_get_market_taxonomy": {"category": "indices", "page_size": 3},
    }
    outputs = {name: toolkit.execute_tool(name, arguments) for name, arguments in calls.items()}
    _require(set(outputs) == set(toolkit.get_tool_map()), "not every registered agent tool was executed")
    _require(outputs["kap_search_companies"]["companies"][0]["ticker"] == "THYAO", "search tool mismatch")
    _require(outputs["kap_get_company_info"]["major_shareholders_count"] >= 2, "profile tool incomplete")
    _require(outputs["kap_get_today_disclosures"]["count"] == 1, "today tool pagination mismatch")
    _require(outputs["kap_get_disclosure_detail"]["content_text"], "detail tool body missing")
    _require(outputs["kap_get_financials"]["currency"] == "TRY", "financial tool currency missing")
    _require(outputs["kap_get_expected_calendar"]["total_found"] >= 1, "calendar tool empty")
    _require(outputs["kap_get_market_taxonomy"]["count"] == 3, "taxonomy tool pagination mismatch")
    return outputs


async def _validate_async(cache_dir: Path) -> dict[str, Any]:
    # Disable cache here so this gate exercises real async HTTP and parsing,
    # instead of merely proving that sync-populated disk entries deserialize.
    config = KapConfig.for_profile("balanced", enable_cache=False, cache_dir=cache_dir)
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    metrics: dict[str, Any] = {}
    try:
        async with AsyncKapClient(config) as client:
            latest = await client.get_latest_disclosures(limit=3, ticker="GARAN")
            _require(bool(latest), "async GARAN history is empty")
            _require(all(_matches_ticker(row, "GARAN") for row in latest), "async exact ticker filter failed")
            detail = await client.get_disclosure_detail(latest[0].disclosure_index)
            _require(detail.disclosure_index == latest[0].disclosure_index, "async detail id mismatch")
            _require(bool(detail.title and detail.publish_date and detail.content_text), "async detail fields missing")
            metrics = dict(client.last_request_metrics)
        return {
            "name": "async_parity",
            "status": "passed",
            "profile": config.profile,
            "started_at_utc": started_at,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_s": round(time.perf_counter() - started, 6),
            "attempts": int(metrics.get("attempts", 0)),
            "request_metrics": metrics,
        }
    except Exception as exc:
        if "client" in locals():
            metrics = dict(client.last_request_metrics)
        return {
            "name": "async_parity",
            "status": "failed",
            "profile": config.profile,
            "started_at_utc": started_at,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_s": round(time.perf_counter() - started, 6),
            "attempts": int(metrics.get("attempts", 0)),
            "error_type": type(exc).__name__,
            "error": f"{type(exc).__name__}: {exc}",
            "request_metrics": metrics,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--financial-year", type=int, default=2025)
    parser.add_argument("--skip-global-calendar", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="kap-live-validation-") as temp_dir:
        cache_dir = Path(temp_dir)
        config = KapConfig.for_profile("balanced", enable_cache=True, cache_dir=cache_dir)
        with KapClient(config) as client:
            def timed(name: str, func: Callable[[], Any], checks: Callable[[Any], None]):
                value, result = _timed(name, func, checks)
                metrics = dict(client.last_request_metrics)
                result["profile"] = config.profile
                result["attempts"] = int(metrics.get("attempts", 0))
                result["request_metrics"] = metrics
                return value, result

            bundled, row = timed("bundled_registry", lambda: client.get_companies(), _check_registry)
            row["count"] = len(bundled or [])
            results.append(row)

            live, row = timed(
                "live_registry",
                lambda: client.get_companies(online=True, force_refresh=True),
                _check_registry,
            )
            row["count"] = len(live or [])
            row["request_metrics"] = dict(client.last_request_metrics)
            results.append(row)

            today, row = timed("today_feed", client.get_today_disclosures, _check_feed)
            row["count"] = len(today or [])
            results.append(row)

            latest, row = timed(
                "exact_ticker_history",
                lambda: client.get_latest_disclosures(limit=3, ticker="GARAN"),
                lambda rows: (
                    _require(bool(rows), "GARAN history is empty"),
                    _require(all(_matches_ticker(item, "GARAN") for item in rows), "exact ticker filter failed"),
                ),
            )
            row["count"] = len(latest or [])
            results.append(row)

            if latest:
                _, row = timed(
                    "disclosure_detail",
                    lambda: client.get_disclosure_detail(latest[0].disclosure_index),
                    lambda detail: (
                        _require(detail.disclosure_index == latest[0].disclosure_index, "detail id mismatch"),
                        _require(detail.stock_code == "GARAN", f"detail ticker mismatch: {detail.stock_code}"),
                        _require(bool(detail.disclosure_type and detail.disclosure_class), "detail type/class missing"),
                        _require(bool(detail.title and detail.publish_date and detail.content_text), "detail fields missing"),
                        _require(re.fullmatch(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}", detail.publish_date or "") is not None, "detail date is not normalized"),
                    ),
                )
                results.append(row)

            from_date = date.today() - timedelta(days=365)
            historical, row = timed(
                "historical_criteria",
                lambda: client.get_historical_disclosures("THYAO", from_date=from_date, disclosure_class="FR"),
                _check_historical,
            )
            row["count"] = len(historical or [])
            results.append(row)

            for kind, fetch in (
                ("indices", client.get_indices),
                ("sectors", client.get_sectors),
                ("markets", client.get_markets),
            ):
                rows, row = timed(
                    f"taxonomy_{kind}",
                    fetch,
                    lambda value, kind=kind: _check_taxonomy(kind, value),
                )
                row["count"] = len(rows or [])
                results.append(row)

            subjects, row = timed(
                "disclosure_subjects",
                lambda: client.get_disclosure_subjects("FR"),
                lambda rows: (
                    _require(len(rows) >= 1, "FR subjects are empty"),
                    _require(any(item.subject == "Finansal Rapor" for item in rows), "financial subject missing"),
                ),
            )
            row["count"] = len(subjects or [])
            results.append(row)

            typed, row = timed(
                "company_disclosures_by_type",
                lambda: client.get_company_disclosures_by_type("THYAO", "FAR"),
                lambda rows: (
                    _require(bool(rows), "THYAO activity reports are empty"),
                    _require(all(item.get("disclosureIndex") for item in rows), "typed disclosure id missing"),
                ),
            )
            row["count"] = len(typed or [])
            results.append(row)

            _, row = timed("company_profile", lambda: client.get_company_general_info("BIMAS"), _check_profile)
            results.append(row)

            statement, row = timed(
                "financial_lookup",
                lambda: client.get_financials("THYAO", args.financial_year, "annual", force_refresh=True),
                lambda value: _check_financial(value, args.financial_year),
            )
            row["items"] = len(statement.items) if statement else 0
            row["disclosure_index"] = statement.disclosure_index if statement else None
            results.append(row)

            _, row = timed(
                "ticker_calendar",
                lambda: client.get_expected_disclosures(days_ahead=180, ticker_or_oid="THYAO"),
                _check_calendar,
            )
            results.append(row)

            if not args.skip_global_calendar:
                global_calendar, row = timed(
                    "global_calendar",
                    lambda: client.get_expected_disclosures(days_ahead=180),
                    lambda rows: (
                        _require(len(rows) >= 100, f"global calendar unexpectedly small: {len(rows)}"),
                        _require(all(row.stock_code or row.company_title for row in rows), "placeholder calendar row exposed"),
                    ),
                )
                row["count"] = len(global_calendar or [])
                results.append(row)

            toolkit = KapToolkit(client=client)
            tool_output, row = timed(
                "all_agent_tools",
                lambda: _validate_agent_tools(
                    toolkit,
                    latest[0].disclosure_index if latest else 0,
                    statement.disclosure_index if statement else 0,
                    args.financial_year,
                ),
                lambda output: _require(len(output) == 10, "agent tool execution count mismatch"),
            )
            row["tool_count"] = len(toolkit.get_tool_map())
            row["executed"] = len(tool_output or {})
            results.append(row)

        results.append(asyncio.run(_validate_async(cache_dir)))

    failed = [row for row in results if row["status"] != "passed"]
    report = {
        "status": "failed" if failed else "passed",
        "network_policy": "public kap.org.tr only; no MKK/MKK REST",
        "profile": "balanced",
        "results": results,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
