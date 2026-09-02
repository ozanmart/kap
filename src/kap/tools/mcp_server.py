from __future__ import annotations

import asyncio
import atexit
import json
import logging
import sys
from typing import Any

from .toolkit import KapToolkit

logger = logging.getLogger("kap.mcp")


def create_mcp_tool_definitions(toolkit: KapToolkit) -> list[dict[str, Any]]:
    """Build tool definitions in Model Context Protocol format."""
    mcp_tools = []
    for name, (input_cls, handler) in toolkit.get_tool_map().items():
        doc = handler.__doc__ or input_cls.__doc__ or name
        mcp_tools.append({
            "name": name,
            "description": doc.strip(),
            "inputSchema": input_cls.model_json_schema(),
        })
    return mcp_tools


async def run_mcp_stdio_server() -> None:
    """Run a JSON-RPC stdio server compliant with the Model Context Protocol (MCP)."""
    toolkit = KapToolkit()
    atexit.register(toolkit.close)
    tools_list = create_mcp_tool_definitions(toolkit)

    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)
    w_transport, w_protocol = await asyncio.get_event_loop().connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout
    )
    writer = asyncio.StreamWriter(w_transport, w_protocol, reader, asyncio.get_event_loop())

    def send_response(response: dict[str, Any]) -> None:
        payload = json.dumps(response, ensure_ascii=False) + "\n"
        writer.write(payload.encode("utf-8"))

    while True:
        line = await reader.readline()
        if not line:
            break
        try:
            msg = json.loads(line.decode("utf-8").strip())
        except Exception:
            continue

        msg_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params", {})

        if method == "initialize":
            send_response({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "kap-mcp-server", "version": "0.1.0"},
                },
            })
        elif method == "tools/list":
            send_response({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": tools_list},
            })
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            try:
                # Tool handlers are intentionally synchronous for the public API;
                # keep blocking HTTP/parsing work off the MCP event loop.
                result_data = await asyncio.to_thread(toolkit.execute_tool, tool_name, arguments)
                send_response({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result_data, ensure_ascii=False, indent=2, default=str)}],
                        "structuredContent": result_data,
                        "isError": False,
                    },
                })
            except Exception as e:
                send_response({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": str(e)}],
                        "isError": True,
                    },
                })
        elif method == "ping":
            send_response({"jsonrpc": "2.0", "id": msg_id, "result": {}})
        else:
            if msg_id is not None:
                send_response({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                })

    toolkit.close()


def main() -> None:
    """CLI entrypoint for running the KAP MCP server."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    asyncio.run(run_mcp_stdio_server())


if __name__ == "__main__":
    main()
