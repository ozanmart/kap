"""Smoke-test the installed ``kap mcp`` JSON-RPC stdio transport."""

from __future__ import annotations

import argparse
import json
import select
import subprocess
import time
from typing import Any


def _read_response(process: subprocess.Popen[str], timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        ready, _, _ = select.select([process.stdout], [], [], max(0.0, deadline - time.monotonic()))
        if not ready:
            break
        line = process.stdout.readline() if process.stdout else ""
        if not line:
            break
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"non-JSON-RPC stdout from MCP server: {line[:200].rstrip()}") from exc
    stderr = process.stderr.read()[-2000:] if process.poll() is not None and process.stderr else ""
    raise RuntimeError(f"MCP response timeout/EOF (exit={process.poll()}): {stderr}")


def _send(process: subprocess.Popen[str], message: dict[str, Any]) -> None:
    if process.stdin is None:
        raise RuntimeError("MCP stdin is unavailable")
    process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
    process.stdin.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", default="kap", help="Path to installed kap executable")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    process = subprocess.Popen(
        [args.command, "mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        _send(process, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "kap-wheel-verifier", "version": "1"},
            },
        })
        initialized = _read_response(process, args.timeout)
        if initialized.get("result", {}).get("serverInfo", {}).get("name") != "kap-mcp-server":
            raise AssertionError(f"unexpected initialize response: {initialized}")

        _send(process, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        _send(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = _read_response(process, args.timeout)
        names = [tool["name"] for tool in listed.get("result", {}).get("tools", [])]
        if len(names) != 10 or "kap_search_companies" not in names or "kap_get_financials" not in names:
            raise AssertionError(f"unexpected MCP tool list: {names}")

        _send(process, {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "kap_search_companies", "arguments": {"query": "THYAO"}},
        })
        called = _read_response(process, args.timeout)
        result = called.get("result", {})
        companies = result.get("structuredContent", {}).get("companies", [])
        if result.get("isError") or not companies or companies[0].get("ticker") != "THYAO":
            raise AssertionError(f"unexpected MCP tool result: {called}")

        print(json.dumps({
            "status": "passed",
            "server": initialized["result"]["serverInfo"],
            "protocol_version": initialized["result"]["protocolVersion"],
            "tool_count": len(names),
            "tool_call_ticker": companies[0]["ticker"],
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
