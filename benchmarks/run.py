from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmarks.adapters import DEFAULT_ROOTS
from benchmarks.core import OFFLINE_LOADS, render_markdown, summarize_latencies, utc_stamp, write_report


ROOT = Path(__file__).resolve().parents[1]
REPOS = ["kap", "pykap", "kap_tr_sdk", "bist_agent"]
OFFLINE_SCENARIOS = [
    "package_import",
    "client_ready",
    "first_offline_lookup",
    "warm_lookup",
    "cold_import",
    "listing_replay",
    "offline_registry",
    "offline_exact_lookup",
    "warm_cache_exact_lookup",
    "async_http_soak",
]
LIVE_SCENARIOS = ["first_live_request", "live_feed", "live_registry"]
COLD_PROCESS_RUNS = {"smoke": 3, "standard": 5, "stress": 10}
RUNTIME_REQUIRED_MODULES = ["httpx", "pydantic", "bs4", "lxml"]
REPO_REQUIRED_MODULES = {
    "kap": RUNTIME_REQUIRED_MODULES + ["diskcache"],
    "pykap": ["requests", "bs4", "pandas"],
    "kap_tr_sdk": ["requests", "pyppeteer", "pandas"],
    "bist_agent": ["httpx", "requests", "tenacity", "bs4", "pydantic", "dotenv"],
}


def _candidate_pythons() -> list[str]:
    active_venv = os.environ.get("VIRTUAL_ENV")
    raw = [
        str(Path(active_venv) / "bin" / "python") if active_venv else None,
        str(ROOT / ".venv" / "bin" / "python"),
        sys.executable,
        "/opt/miniconda3/bin/python3",
        shutil.which("python3"),
        "/usr/local/bin/python3",
        "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3",
    ]
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        if item and item not in seen and Path(item).exists():
            seen.add(item)
            out.append(item)
    return out


def _supports_all_dependencies(python: str) -> bool:
    code = (
        "import importlib.util,sys; "
        f"mods={RUNTIME_REQUIRED_MODULES + ['build']!r}; "
        "sys.exit(0 if all(importlib.util.find_spec(x) for x in mods) else 1)"
    )
    try:
        return subprocess.run([python, "-c", code], timeout=10, capture_output=True).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def select_python(requested: str) -> str:
    if requested != "auto":
        requested_path = Path(requested).expanduser()
        if not requested_path.exists():
            requested_path = Path(shutil.which(requested) or requested_path)
        if not requested_path.exists():
            raise SystemExit(f"Python interpreter does not exist: {requested}")
        # Keep the venv launcher path intact. Resolving its symlink points at
        # the base interpreter and silently drops the venv site-packages.
        return str(requested_path)
    for candidate in _candidate_pythons():
        if _supports_all_dependencies(candidate):
            return candidate
    raise SystemExit(
        "No benchmark Python has the current package's runtime and build dependencies. "
        "Pass --python PATH to the project's virtualenv."
    )


def dependency_report(python: str) -> dict[str, list[str]]:
    """Preflight all comparison dependencies before any benchmark worker starts."""
    code = (
        "import importlib.util,sys; "
        f"mods={REPO_REQUIRED_MODULES!r}; "
        "print(';'.join(f'{repo}=' + ','.join(m for m in required if not importlib.util.find_spec(m)) "
        "for repo,required in mods.items()))"
    )
    output = subprocess.run([python, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    result: dict[str, list[str]] = {}
    for item in output.split(";"):
        if not item:
            continue
        repo, _, missing = item.partition("=")
        result[repo] = [module for module in missing.split(",") if module]
    return result


def build_current_wheel(base_python: str, workspace: Path) -> Path:
    """Build the current source tree into a fresh wheel for artifact benchmarking."""
    dist_dir = workspace / "wheelhouse"
    dist_dir.mkdir(parents=True, exist_ok=True)
    commands = [
        [base_python, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(dist_dir)]
    ]
    uv = shutil.which("uv") or "/Users/omerozanmart/.local/bin/uv"
    if Path(uv).exists():
        commands.append([uv, "build", "--wheel", "--out-dir", str(dist_dir)])
    errors: list[str] = []
    for command in commands:
        process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        if process.returncode == 0:
            break
        errors.append(f"$ {' '.join(command)}\\n{process.stderr[-1000:]}")
    else:
        raise SystemExit("Automatic wheel build failed.\\n" + "\\n".join(errors))
    wheels = sorted(dist_dir.glob("kap-*.whl"))
    if not wheels:
        raise SystemExit("Automatic wheel build completed without producing kap-*.whl")
    return wheels[-1]


def prepare_isolated_environment(base_python: str, wheel: Path, workspace: Path) -> str:
    """Create a disposable venv and install the freshly built wheel with runtime deps."""
    env_dir = workspace / "benchmark-venv"
    subprocess.run([base_python, "-m", "venv", str(env_dir)], cwd=ROOT, check=True, timeout=60)
    env_python = env_dir / "bin" / "python"
    if not env_python.exists():
        raise SystemExit(f"Temporary benchmark interpreter was not created: {env_python}")
    process = subprocess.run(
        [str(env_python), "-m", "pip", "install", "--disable-pip-version-check", "--quiet", str(wheel)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if process.returncode != 0:
        raise SystemExit("Installing the freshly built wheel in the temporary environment failed.\n" + process.stderr[-2000:])
    if not _supports_runtime_dependencies(str(env_python)):
        raise SystemExit("The temporary environment is missing the current package runtime dependencies.")
    return str(env_python)


def _supports_runtime_dependencies(python: str) -> bool:
    code = (
        "import importlib.util; "
        f"mods={RUNTIME_REQUIRED_MODULES!r}; "
        "raise SystemExit(0 if all(importlib.util.find_spec(x) for x in mods) else 1)"
    )
    try:
        return subprocess.run([python, "-c", code], timeout=10, capture_output=True).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _job(
    python: str,
    repo: str,
    scenario: str,
    iterations: int,
    warmups: int,
    timeout_s: float,
    fixture: Path,
    roots: dict[str, Path],
) -> dict[str, Any]:
    command = [
        python,
        "-m",
        "benchmarks.worker",
        "--repo",
        repo,
        "--repo-root",
        str(roots[repo]),
        "--scenario",
        scenario,
        "--iterations",
        str(iterations),
        "--warmups",
        str(warmups),
        "--fixture",
        str(fixture),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    started = datetime.now(timezone.utc).isoformat()
    try:
        process = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {
            "repo": repo,
            "scenario": scenario,
            "iterations": iterations,
            "warmups": warmups,
            "status": "timeout",
            "error": f"worker exceeded hard timeout ({timeout_s:.0f}s)",
            "started_at_utc": started,
        }
    stdout_lines = [line for line in process.stdout.splitlines() if line.strip()]
    if process.returncode != 0 or not stdout_lines:
        return {
            "repo": repo,
            "scenario": scenario,
            "iterations": iterations,
            "warmups": warmups,
            "status": "error",
            "error": f"worker exit={process.returncode}: {process.stderr.strip()[-1000:]}",
            "started_at_utc": started,
        }
    try:
        row = json.loads(stdout_lines[-1])
    except json.JSONDecodeError:
        return {
            "repo": repo,
            "scenario": scenario,
            "iterations": iterations,
            "warmups": warmups,
            "status": "error",
            "error": f"worker emitted invalid JSON: {process.stdout[-1000:]}",
            "started_at_utc": started,
        }
    row["started_at_utc"] = started
    if process.stderr.strip():
        row["worker_stderr_tail"] = process.stderr.strip()[-1000:]
    return row


def parse_root_overrides(values: list[str]) -> dict[str, Path]:
    roots = dict(DEFAULT_ROOTS)
    for value in values:
        try:
            repo, path = value.split("=", 1)
        except ValueError as exc:
            raise SystemExit(f"Invalid --repo-root {value!r}; expected REPO=/path") from exc
        if repo not in roots:
            raise SystemExit(f"Unknown repo in --repo-root: {repo}")
        roots[repo] = Path(path).expanduser().resolve()
    return roots


def aggregate_cold_imports(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine independent cold-process samples; importing twice in one process is not cold."""
    cold = [row for row in rows if row["scenario"] == "cold_import"]
    other = [row for row in rows if row["scenario"] != "cold_import"]
    for repo in REPOS:
        repo_rows = [row for row in cold if row["repo"] == repo]
        if not repo_rows:
            continue
        failures = [row for row in repo_rows if row["status"] != "ok"]
        if failures:
            aggregate = dict(failures[0])
            aggregate["iterations"] = len(repo_rows)
            aggregate["status"] = "error" if any(row["status"] in {"error", "timeout"} for row in failures) else "skipped"
            reason = failures[0].get("error") or failures[0].get("skip_reason") or "unknown"
            aggregate["skip_reason"] = f"{len(failures)}/{len(repo_rows)} cold import processes unavailable; first: {reason}"
            aggregate.pop("error", None)
        else:
            samples = [float(row["mean_ms"]) for row in repo_rows]
            aggregate = dict(repo_rows[0])
            aggregate.update(summarize_latencies(samples))
            aggregate["iterations"] = len(samples)
            aggregate["process_samples_ms"] = samples
            aggregate["peak_rss_mb"] = max(float(row.get("peak_rss_mb") or 0) for row in repo_rows)
        other.append(aggregate)
    return other


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated four-repository KAP benchmark")
    parser.add_argument("--profile", choices=sorted(OFFLINE_LOADS), default="standard")
    parser.add_argument("--python", default="auto", help="One interpreter used by all repos (default: auto)")
    parser.add_argument("--live", action="store_true", help="Enable low-intensity public kap.org.tr tests")
    parser.add_argument("--live-iterations", type=int, default=1, choices=range(1, 4), metavar="{1,2,3}")
    parser.add_argument("--timeout", type=float, default=45.0, help="Hard timeout per offline worker")
    parser.add_argument("--live-timeout", type=float, default=35.0, help="Hard timeout per live worker")
    parser.add_argument("--jobs", type=int, default=2, help="Parallel offline workers; live workers are always serial")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "benchmark-results")
    parser.add_argument("--repo-root", action="append", default=[], metavar="REPO=/path")
    parser.add_argument("--scenario", action="append", choices=OFFLINE_SCENARIOS + LIVE_SCENARIOS)
    args = parser.parse_args()

    if args.jobs < 1 or args.jobs > 4:
        parser.error("--jobs must be between 1 and 4")
    base_python = select_python(args.python)
    roots = parse_root_overrides(args.repo_root)
    missing = [f"{repo}={path}" for repo, path in roots.items() if not path.exists()]
    if missing:
        raise SystemExit("Missing repository roots: " + ", ".join(missing))

    scenarios = args.scenario or list(OFFLINE_SCENARIOS)
    if args.live and not args.scenario:
        scenarios.extend(LIVE_SCENARIOS)
    if not args.live and any(item in LIVE_SCENARIOS for item in scenarios):
        raise SystemExit("Live scenarios require --live")

    fixture = ROOT / "tests" / "fixtures" / "bist_sirketler.html"
    loads = OFFLINE_LOADS[args.profile]
    jobs: list[tuple[str, str, int, int, float]] = []
    for scenario in scenarios:
        if scenario == "cold_import":
            scenario_loads = [1] * COLD_PROCESS_RUNS[args.profile]
        elif scenario in {"package_import", "client_ready", "first_offline_lookup"}:
            scenario_loads = [1]
        else:
            scenario_loads = loads
        if scenario in LIVE_SCENARIOS:
            scenario_loads = [args.live_iterations]
        for repo in REPOS:
            for iterations in scenario_loads:
                warmups = 0 if scenario in {"cold_import"} | set(LIVE_SCENARIOS) else min(3, iterations)
                timeout = args.live_timeout if scenario in LIVE_SCENARIOS else args.timeout
                jobs.append((repo, scenario, iterations, warmups, timeout))

    offline_jobs = [job for job in jobs if job[1] not in LIVE_SCENARIOS]
    live_jobs = [job for job in jobs if job[1] in LIVE_SCENARIOS]
    results: list[dict[str, Any]] = []
    dependency_status = dependency_report(base_python)
    print(f"Base interpreter: {base_python}", flush=True)
    print("Dependency preflight:", flush=True)
    for repo in REPOS:
        missing_modules = dependency_status.get(repo, [])
        print(
            f"  {repo}: {'ok' if not missing_modules else 'missing ' + ', '.join(missing_modules)}",
            flush=True,
        )

    # Always benchmark the current checkout as the newly built artifact. The
    # disposable environment prevents an old editable install from leaking in.
    with tempfile.TemporaryDirectory(prefix="kap-benchmark-") as temp_dir:
        benchmark_workspace = Path(temp_dir)
        wheel = build_current_wheel(base_python, benchmark_workspace)
        python = prepare_isolated_environment(base_python, wheel, benchmark_workspace)
        print(f"Artifact wheel: {wheel}", flush=True)
        print(f"Benchmark interpreter: {python}", flush=True)
        print(f"Offline jobs: {len(offline_jobs)}; live jobs: {len(live_jobs)}", flush=True)
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            futures = {
                executor.submit(_job, python, *job, fixture, roots): job
                for job in offline_jobs
            }
            for future in as_completed(futures):
                row = future.result()
                results.append(row)
                print(f"[{row['status']:^7}] {row['repo']:<12} {row['scenario']:<24} n={row['iterations']}", flush=True)

        for job in live_jobs:
            row = _job(python, *job, fixture, roots)
            results.append(row)
            print(f"[{row['status']:^7}] {row['repo']:<12} {row['scenario']:<24} n={row['iterations']}", flush=True)

    results = aggregate_cold_imports(results)
    scenario_order = {name: i for i, name in enumerate(OFFLINE_SCENARIOS + LIVE_SCENARIOS)}
    repo_order = {name: i for i, name in enumerate(REPOS)}
    results.sort(key=lambda row: (scenario_order[row["scenario"]], repo_order[row["repo"]], row["iterations"]))
    report = {
        "meta": {
            "run_id": utc_stamp(),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "python_executable": python,
            "base_python_executable": base_python,
            "artifact_wheel": str(wheel),
            "python_version": next((row.get("python_version") for row in results if row.get("python_version")), "unknown"),
            "profile": args.profile,
            "live": args.live,
            "offline_loads": loads,
            "live_iterations": args.live_iterations if args.live else 0,
            "network_policy": "public kap.org.tr only; no MKK endpoints",
            "repo_roots": {key: str(value) for key, value in roots.items()},
            "dependency_preflight": dependency_status,
        },
        "results": results,
    }
    json_path, md_path = write_report(report, args.output_dir)
    print(f"\nJSON: {json_path}")
    print(f"Markdown: {md_path}\n")
    print(render_markdown(report))
    current_rows = [row for row in results if row.get("repo") == "kap"]
    target_unavailable = not current_rows or all(row.get("status") == "skipped" for row in current_rows)
    return 1 if target_unavailable or any(row["status"] in {"error", "timeout"} for row in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
