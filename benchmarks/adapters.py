from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from benchmarks.core import stable_digest


CURRENT_ROOT = Path(__file__).resolve().parents[1]


def _external_repo(env_name: str, sibling_name: str, download_name: str) -> Path:
    """Resolve an optional comparison checkout without embedding local paths."""
    configured = os.environ.get(env_name)
    if configured:
        return Path(configured).expanduser()
    sibling = CURRENT_ROOT.parent / sibling_name
    if sibling.exists():
        return sibling
    return Path.home() / "Downloads" / download_name


DEFAULT_ROOTS = {
    "kap": CURRENT_ROOT,
    "pykap": _external_repo("KAP_BENCHMARK_PYKAP_ROOT", "pykap-master", "pykap-master"),
    "kap_tr_sdk": _external_repo("KAP_BENCHMARK_KAP_TR_SDK_ROOT", "kap-tr-sdk-main", "kap-tr-sdk-main"),
}
EXPECTED_REPLAY_TICKERS = {"ACSEL", "ADEL", "A1CAP", "ACP"}

#: Replaying a captured *server* response to a parser that consumes a
#: *browser-rendered* DOM measures the capture, not the parser. KAP renders the
#: listing client-side: fetched over HTTP the page carries only the RSC payload,
#: while in a browser it also exposes `#financialTable` (846 rows, verified
#: against the live page on 2026-09-03). A parser that reads that table is not
#: wrong for finding nothing in the server bytes - it was handed the wrong
#: input - so it is skipped here rather than recorded as incorrect. The
#: dependency still shows up where it belongs: in capability coverage, since
#: such a parser needs a headless browser at runtime and the others do not.
BROWSER_RENDERED_DOM_SKIP = (
    "parser consumes a browser-rendered DOM (`#financialTable`), which a captured "
    "server response does not contain; replaying it would measure the capture, "
    "not the parser"
)
LIVE_REGISTRY_REFERENCE_TICKERS = {"THYAO", "BIMAS", "GARAN", "ACSEL", "A1CAP", "ACP"}
LIVE_REGISTRY_MIN_TICKERS = 800


class UnsupportedScenario(RuntimeError):
    pass


@dataclass
class Operation:
    invoke: Callable[[], dict[str, Any]]
    close: Callable[[], None] = lambda: None
    implementation: str = ""


def configure_source_path(repo: str, root: Path | None = None) -> Path:
    selected = (root or DEFAULT_ROOTS[repo]).resolve()
    # The current package is benchmarked as the installed wheel.  Inserting
    # `kap/src` here would reintroduce the iCloud-hosted editable tree and make
    # the benchmark measure filesystem hydration instead of the artifact.
    if repo != "kap":
        sys.path.insert(0, str(selected))
    return selected


def _result(values: list[str], *, expected: set[str] | None = None) -> dict[str, Any]:
    actual = {str(value).strip().upper() for value in values if str(value).strip()}
    return {
        "item_count": len(actual),
        "digest": stable_digest(actual),
        "correct": actual == expected if expected is not None else None,
        "sample": sorted(actual)[:5],
    }


def _live_feed_result(values: list[str]) -> dict[str, Any]:
    result = _result(values)
    result["correct"] = bool(result["item_count"]) and all(str(value).isdigit() for value in values if value)
    return result


def _live_registry_result(values: list[str]) -> dict[str, Any]:
    normalized = [str(value).strip().upper() for value in values if str(value).strip()]
    result = _result(normalized)
    unique = set(normalized)
    result["correct"] = (
        len(normalized) == len(unique)
        and len(unique) >= LIVE_REGISTRY_MIN_TICKERS
        and LIVE_REGISTRY_REFERENCE_TICKERS.issubset(unique)
        and all(re.fullmatch(r"[A-Z0-9]{2,6}", ticker) for ticker in unique)
    )
    if not result["correct"]:
        result["validation"] = {
            "minimum_count": LIVE_REGISTRY_MIN_TICKERS,
            "duplicates": len(normalized) - len(unique),
            "missing_reference_tickers": sorted(LIVE_REGISTRY_REFERENCE_TICKERS - unique),
            "invalid_tickers": sorted(ticker for ticker in unique if not re.fullmatch(r"[A-Z0-9]{2,6}", ticker))[:10],
        }
    return result


#: The module each repository documents as its entry point, and the attribute a
#: caller reaches for first. Touching the attribute matters: this package
#: resolves its client lazily, so importing alone would not pay a cost the
#: others pay eagerly, and the comparison would flatter it.
COLD_IMPORT_TARGETS = {
    "kap": ("kap", "KapClient"),
    "pykap": ("pykap", "get_bist_companies"),
    "kap_tr_sdk": ("kap_sdk.kap_client", "KapClient"),
}


def import_target(repo: str) -> dict[str, Any]:
    module_name, attribute = COLD_IMPORT_TARGETS[repo]
    module = importlib.import_module(module_name)
    entry_point = getattr(module, attribute)
    return {
        "item_count": len(vars(module)),
        "digest": stable_digest(vars(module)),
        "correct": callable(entry_point),
    }


def _package_import(repo: str) -> Operation:
    targets = {
        "kap": "kap",
        "pykap": "pykap",
        "kap_tr_sdk": "kap_sdk",
    }

    def invoke() -> dict[str, Any]:
        module = importlib.import_module(targets[repo])
        return {"item_count": len(vars(module)), "digest": stable_digest(vars(module)), "correct": None}

    return Operation(invoke, implementation="top-level package import only")


def _client_ready(repo: str) -> Operation:
    if repo == "kap":
        def invoke() -> dict[str, Any]:
            kap = importlib.import_module("kap")
            client = kap.KapClient(config=kap.KapConfig(enable_cache=False))
            client.close()
            return {"item_count": 1, "correct": True}

        return Operation(invoke, implementation="package import + lazy KapClient construction")

    if repo == "kap_tr_sdk":
        def invoke() -> dict[str, Any]:
            module = importlib.import_module("kap_sdk.kap_client")
            client = module.KapClient()
            client.cache.close()
            return {"item_count": 1, "correct": True}

        return Operation(invoke, implementation="package import + KapClient construction")

    raise UnsupportedScenario("repository exposes module-level functions, not a client object")


def _first_offline_lookup(repo: str) -> Operation:
    if repo == "kap":
        def invoke() -> dict[str, Any]:
            kap = importlib.import_module("kap")
            client = kap.KapClient(config=kap.KapConfig(enable_cache=False))
            try:
                company = client.get_company("THYAO")
                return _result([company.ticker] if company else [], expected={"THYAO"})
            finally:
                client.close()

        return Operation(invoke, implementation="package import + lazy client + first bundled lookup")

    if repo == "pykap":
        def invoke() -> dict[str, Any]:
            module = importlib.import_module("pykap.get_general_info")
            company = module.get_general_info("THYAO", online=False)
            return _result([company.get("ticker", "")] if company else [], expected={"THYAO"})

        return Operation(invoke, implementation="package import + first bundled lookup")

    raise UnsupportedScenario("repository has no offline lookup; every query needs the network")


def _warm_lookup(repo: str) -> Operation:
    if repo == "kap":
        kap = importlib.import_module("kap")
        client = kap.KapClient(config=kap.KapConfig(enable_cache=False))
        client.get_company("THYAO")

        def invoke() -> dict[str, Any]:
            company = client.get_company("THYAO")
            return _result([company.ticker] if company else [], expected={"THYAO"})

        return Operation(invoke, client.close, "repeated bundled lookup after client/index warm-up")

    if repo == "pykap":
        module = importlib.import_module("pykap.get_general_info")
        module.get_general_info("THYAO", online=False)

        def invoke() -> dict[str, Any]:
            company = module.get_general_info("THYAO", online=False)
            return _result([company.get("ticker", "")] if company else [], expected={"THYAO"})

        return Operation(invoke, implementation="repeated bundled lookup after module warm-up")

    raise UnsupportedScenario("repository has no offline lookup; every query needs the network")


def _first_live_request(repo: str) -> Operation:
    if repo != "kap":
        raise UnsupportedScenario("first live request is implemented for kap")

    def invoke() -> dict[str, Any]:
        kap = importlib.import_module("kap")
        client = kap.KapClient(config=kap.KapConfig.for_profile("fast", enable_cache=False))
        try:
            rows = client.get_latest_disclosures(limit=1)
            return _result([str(row.disclosure_index or row.disclosure_id or "") for row in rows])
        finally:
            client.close()

    return Operation(invoke, implementation="package import + lazy client + first public feed request")


def build_operation(repo: str, scenario: str, fixture_path: Path) -> Operation:
    logging.disable(logging.CRITICAL)
    if scenario == "package_import":
        return _package_import(repo)
    if scenario == "client_ready":
        return _client_ready(repo)
    if scenario == "first_offline_lookup":
        return _first_offline_lookup(repo)
    if scenario == "warm_lookup":
        return _warm_lookup(repo)
    if scenario == "first_live_request":
        return _first_live_request(repo)
    if scenario == "listing_replay":
        return _listing_replay(repo, fixture_path)
    if scenario == "profile_replay":
        return _profile_replay(repo, fixture_path)
    if scenario == "feed_normalize":
        return _feed_normalize(repo, fixture_path)
    if scenario == "offline_registry":
        return _offline_registry(repo)
    if scenario == "offline_exact_lookup":
        return _offline_exact_lookup(repo)
    if scenario == "warm_cache_exact_lookup":
        return _warm_cache_exact_lookup(repo)
    if scenario == "async_http_soak":
        return _async_http_soak(repo)
    if scenario == "live_feed":
        return _live_feed(repo)
    if scenario == "live_registry":
        return _live_registry(repo)
    raise UnsupportedScenario(f"Unknown scenario: {scenario}")


def _listing_replay(repo: str, fixture_path: Path) -> Operation:
    html = fixture_path.read_text(encoding="utf-8")

    if repo == "kap":
        listings = importlib.import_module("kap.scrapers.listings")
        scraper = listings.ListingsScraper()

        def invoke() -> dict[str, Any]:
            payload = listings._extract_next_payload_texts(html)
            rows = listings._extract_json_objects(payload) if payload.strip() else []
            companies = scraper._parse_companies_rows(rows)
            if not companies:
                companies = scraper._parse_companies_table(html)
            return _result([item.ticker for item in companies], expected=EXPECTED_REPLAY_TICKERS)

        return Operation(invoke, scraper.base.close, "RSC-first parser with SSR-table fallback")

    if repo == "pykap":
        module = importlib.import_module("pykap.get_bist_companies")

        class Response:
            text = html

            @staticmethod
            def raise_for_status() -> None:
                return None

        def invoke() -> dict[str, Any]:
            original = module.requests.get
            module.requests.get = lambda *args, **kwargs: Response()
            try:
                rows = module._get_bist_companies(output_format="dict") or []
            finally:
                module.requests.get = original
            return _result([row.get("ticker", "") for row in rows], expected=EXPECTED_REPLAY_TICKERS)

        return Operation(invoke, implementation="requests + BeautifulSoup + regex parser (HTTP replayed)")

    if repo == "kap_tr_sdk":
        raise UnsupportedScenario(BROWSER_RENDERED_DOM_SKIP)

    raise UnsupportedScenario(repo)


PROFILE_MEMBER_OID = "4028e4a140f2ed720140f376bebb01a7"
PROFILE_SOURCE_URL = f"https://www.kap.org.tr/tr/sirket-bilgileri/genel/{PROFILE_MEMBER_OID}"


#: Only the scalar fields every participating profile parser documents. A field
#: one repository models elsewhere (kap-tr-sdk carries the company title on its
#: Company object, not on CompanyInfo) would otherwise fail it for a modelling
#: choice rather than for a parsing failure.
PROFILE_FIELDS = ("website", "auditor", "sector", "market", "indices")


def _profile_field_values(values: dict[str, Any]) -> dict[str, Any]:
    """Compare profile parsers on the scalar fields all of them claim to read."""
    present = {name for name in PROFILE_FIELDS if str(values.get(name) or "").strip()}
    return {
        "item_count": len(present),
        "digest": stable_digest(f"{name}={values[name]}" for name in sorted(present)),
        "correct": present == set(PROFILE_FIELDS),
        "sample": sorted(present),
    }


def _profile_replay(repo: str, fixture_path: Path) -> Operation:
    """Parse a captured KAP company-profile page. No repository is given a
    network call, so this isolates parser capability and cost."""
    html = (fixture_path.parent / "kap_company_general_live.html").read_text(encoding="utf-8")

    if repo == "kap":
        module = importlib.import_module("kap.scrapers.company_general")

        def invoke() -> dict[str, Any]:
            info = module.parse_company_general_html(html, PROFILE_MEMBER_OID, PROFILE_SOURCE_URL)
            return _profile_field_values({
                "sector": info.sector,
                "market": info.market,
                "auditor": info.auditor,
                "website": info.website,
                "indices": info.indices,
            })

        return Operation(invoke, implementation="RSC scalar fields with scoped HTML fallback")

    if repo == "kap_tr_sdk":
        raise UnsupportedScenario(BROWSER_RENDERED_DOM_SKIP)

    raise UnsupportedScenario("repository has no company-profile page parser")


def _feed_normalize(repo: str, fixture_path: Path) -> Operation:
    """Normalize a captured disclosure feed payload into the repository's own
    row shape, which is the step every KAP client has to get right."""
    payload = json.loads((fixture_path.parent / "kap_feed_live.json").read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else payload.get("data", [])
    expected = {
        str((row.get("disclosureBasic") or row).get("disclosureIndex") or "")
        for row in rows
        if isinstance(row, dict)
    } - {""}

    if repo == "kap":
        module = importlib.import_module("kap.scrapers.disclosures")

        def invoke() -> dict[str, Any]:
            normalized = [module._normalize_raw_disclosure(row, "tr") for row in rows if isinstance(row, dict)]
            return _result([str(item.disclosure_index) for item in normalized], expected=expected)

        return Operation(invoke, implementation="typed Pydantic Disclosure per row")

    if repo == "kap_tr_sdk":
        models = importlib.import_module("kap_sdk.models.disclosure")

        def invoke() -> dict[str, Any]:
            normalized = [
                models.Disclosure(
                    disclosureBasic=models.DisclosureBasic(**row["disclosureBasic"]),
                    disclosureDetail=models.DisclosureDetail(**row["disclosureDetail"]),
                )
                for row in rows
                if isinstance(row, dict)
            ]
            return _result(
                [str(item.disclosureBasic.disclosureIndex) for item in normalized],
                expected=expected,
            )

        return Operation(invoke, implementation="typed dataclass per row")

    raise UnsupportedScenario("repository has no disclosure feed to normalize")


def _offline_registry(repo: str) -> Operation:
    if repo == "kap":
        module = importlib.import_module("kap.scrapers.listings")

        def invoke() -> dict[str, Any]:
            return _result([row.ticker for row in module.get_bundled_companies()])

        return Operation(invoke, implementation="lru-cached bundled JSON index")
    if repo == "pykap":
        module = importlib.import_module("pykap.get_bist_companies")

        def invoke() -> dict[str, Any]:
            rows = module.get_bist_companies(online=False, output_format="dict")
            return _result([row.get("ticker", "") for row in rows])

        return Operation(invoke, implementation="bundled JSON decoded on every call")
    raise UnsupportedScenario("repository has no bundled offline company registry")


def _offline_exact_lookup(repo: str) -> Operation:
    if repo == "kap":
        kap = importlib.import_module("kap")
        client = kap.KapClient(config=kap.KapConfig(enable_cache=False))

        def invoke() -> dict[str, Any]:
            company = client.get_company("THYAO")
            return _result([company.ticker] if company else [], expected={"THYAO"})

        return Operation(invoke, client.close, "public get_company over cached in-memory index")
    if repo == "pykap":
        module = importlib.import_module("pykap.get_general_info")

        def invoke() -> dict[str, Any]:
            company = module.get_general_info("THYAO", online=False)
            return _result([company.get("ticker", "")] if company else [], expected={"THYAO"})

        return Operation(invoke, implementation="public get_general_info; bundled JSON reparsed per call")
    raise UnsupportedScenario("repository has no public offline exact-ticker lookup")


def _warm_cache_registry_rows() -> list[dict[str, Any]]:
    """Build the shared warm-cache fixture in kap-tr-sdk's own row shape.

    Both repositories must hold the same number of companies for the warm-hit
    comparison to mean anything. The rows come from the bundled snapshot, which
    is a data file rather than any repository's measured code path.
    """
    listings = importlib.import_module("kap.scrapers.listings")
    return [
        {
            "path": company.ticker.lower(),
            "name": company.name,
            "code": company.ticker,
            "city": company.city or "",
            "independent_audit_firm": company.auditor or "",
        }
        for company in listings.get_bundled_companies()
    ]


def _warm_cache_exact_lookup(repo: str) -> Operation:
    if repo == "kap":
        kap = importlib.import_module("kap")
        temp_dir = tempfile.TemporaryDirectory(prefix="kap-bench-")
        client = kap.KapClient(config=kap.KapConfig(enable_cache=True, cache_dir=temp_dir.name))
        client.get_companies()
        # A warm hit must not fall through to the data source.
        client.listings.get_companies = lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("warm cache unexpectedly called the source")
        )

        def invoke() -> dict[str, Any]:
            rows = client.get_companies()
            company = next((row for row in rows if row.ticker == "THYAO"), None)
            return _result([company.ticker] if company else [], expected={"THYAO"})

        def close() -> None:
            client.close()
            temp_dir.cleanup()

        return Operation(invoke, close, "memory/disk cache hit; underlying registry source disabled")
    if repo != "kap_tr_sdk":
        raise UnsupportedScenario("repository has no response cache; every lookup reparses its bundled JSON")
    module = importlib.import_module("kap_sdk.kap_client")
    temp_dir = tempfile.TemporaryDirectory(prefix="kap-bench-")
    module._CACHE_DIR = temp_dir.name
    client = module.KapClient()
    # Seed the full registry, not a two-row stub. Scanning 2 entries against
    # another repository's 800 is not the same operation, and the difference
    # would be reported as a speed result rather than as the fixture artifact
    # it is.
    client.cache.set("companies", _warm_cache_registry_rows())
    loop = asyncio.new_event_loop()

    def invoke() -> dict[str, Any]:
        company = loop.run_until_complete(client.get_company("THYAO"))
        return _result([company.code] if company else [], expected={"THYAO"})

    def close() -> None:
        client.cache.close()
        loop.close()
        temp_dir.cleanup()

    return Operation(invoke, close, "async public get_company over diskcache hit")


def _async_http_soak(repo: str) -> Operation:
    """Exercise the SDK's real async HTTP path against a local TCP server."""
    if repo != "kap":
        raise UnsupportedScenario(
            "no public API issues concurrent HTTP requests: pykap is synchronous, and "
            "kap-tr-sdk's async methods wrap blocking requests calls"
        )

    kap = importlib.import_module("kap")
    base_module = importlib.import_module("kap.scrapers.base")
    loop = asyncio.new_event_loop()
    state = {"active": 0, "max_active": 0, "requests": 0}

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while await reader.readline():
                while True:
                    header = await reader.readline()
                    if not header or header in {b"\r\n", b"\n"}:
                        break
                state["requests"] += 1
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
                await asyncio.sleep(0.001)
                body = b'{"ok":true}'
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    + f"Content-Length: {len(body)}\r\nConnection: keep-alive\r\n\r\n".encode()
                    + body
                )
                await writer.drain()
                state["active"] -= 1
        finally:
            writer.close()
            await writer.wait_closed()

    server = loop.run_until_complete(asyncio.start_server(handler, "127.0.0.1", 0))
    port = server.sockets[0].getsockname()[1]
    scraper = base_module.BaseScraper(
        kap.KapConfig(
            base_url=f"http://127.0.0.1:{port}",
            max_concurrency=8,
            max_retries=1,
            request_deadline_s=5.0,
            enable_cache=False,
        )
    )

    async def invoke_async() -> dict[str, Any]:
        responses = await asyncio.gather(*[
            scraper.request_async("GET", f"/soak/{index}") for index in range(32)
        ])
        return {
            "item_count": len(responses),
            "correct": all(response.json().get("ok") is True for response in responses),
            "max_active": state["max_active"],
            "batch_size": 32,
            "concurrency_limit": 8,
        }

    def invoke() -> dict[str, Any]:
        return loop.run_until_complete(invoke_async())

    def close() -> None:
        loop.run_until_complete(scraper.aclose())
        server.close()
        loop.run_until_complete(server.wait_closed())
        loop.close()

    return Operation(invoke, close, "shared AsyncClient + local TCP server + semaphore")


def _live_feed(repo: str) -> Operation:
    if repo == "kap":
        kap = importlib.import_module("kap")
        config = kap.KapConfig(enable_cache=False, timeout_s=10.0, max_retries=1)
        client = kap.KapClient(config=config)

        def invoke() -> dict[str, Any]:
            rows = client.get_today_disclosures()
            ids = [str(row.disclosure_index or row.disclosure_id or "") for row in rows]
            return _live_feed_result(ids)

        return Operation(invoke, client.close, "shared httpx.Client; one attempt; 10s request timeout")
    if repo == "kap_tr_sdk":
        module = importlib.import_module("kap_sdk.kap_client")
        client = module.KapClient()
        loop = asyncio.new_event_loop()

        def invoke() -> dict[str, Any]:
            rows = loop.run_until_complete(client.get_announcements())
            ids = [str(getattr(row.disclosureBasic, "disclosureIndex", "")) for row in rows]
            return _live_feed_result(ids)

        def close() -> None:
            client.cache.close()
            loop.close()

        return Operation(invoke, close, "async signature wrapping synchronous requests.post; no explicit timeout")
    raise UnsupportedScenario("repository has no comparable live disclosure-feed API")


def _live_registry(repo: str) -> Operation:
    if repo == "kap":
        kap = importlib.import_module("kap")
        client = kap.KapClient(config=kap.KapConfig(enable_cache=False, timeout_s=12.0))

        def invoke() -> dict[str, Any]:
            result = _live_registry_result([row.ticker for row in client.get_companies(online=True, force_refresh=True)])
            result["request_metrics"] = dict(client.last_request_metrics)
            return result

        return Operation(invoke, client.close, "direct shared-client HTTP + RSC parser")
    if repo == "pykap":
        module = importlib.import_module("pykap.get_bist_companies")

        def invoke() -> dict[str, Any]:
            rows = module.get_bist_companies(online=True, output_format="dict") or []
            return _live_registry_result([row.get("ticker", "") for row in rows])

        return Operation(invoke, implementation="requests + BeautifulSoup + regex; 30s request timeout")
    if repo == "kap_tr_sdk":
        module = importlib.import_module("kap_sdk.kap_client")
        client = module.KapClient()
        loop = asyncio.new_event_loop()

        def invoke() -> dict[str, Any]:
            rows = loop.run_until_complete(client.get_companies(fetch_remote=True))
            return _live_registry_result([row.code for row in rows])

        def close() -> None:
            client.cache.close()
            loop.close()

        return Operation(invoke, close, "headless Chromium/pyppeteer scraper")
    raise UnsupportedScenario(repo)
