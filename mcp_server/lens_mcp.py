# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2,<3"]
# ///
"""The MCP server: the desk tools, spoken in the Model Context Protocol.

This file is the protocol and nothing else. What the tools are, what they return and how
an answer is cut to size all live in ``backend/mcp_tools.py``, which the test suite
covers; this registers that catalogue with the official SDK and forwards each call to
the terminal's API. It holds no figure and no rule of its own, so it has nothing to get
wrong about the book.

It is a separate process from the API for one reason. The protocol SDK needs Python 3.10
or later and the backend runs on 3.9. The protocol itself changed shape in July 2026 (the
handshake went, each request now carries its own version), and the SDK speaks both the
new form and the old one, which a hand-written server would have to keep up with. So the
SDK does the protocol here and the backend is reached over HTTP, like any other client.

Run it with uv, which reads the dependency block at the top of this file and needs no
virtualenv in the repository:

    uv run mcp_server/lens_mcp.py                 # stdio, for a client that launches it
    uv run mcp_server/lens_mcp.py --http 8765     # Streamable HTTP on 127.0.0.1:8765/mcp

The API must be up (./run.sh, port 8000). ``LENS_API`` points at another address. A tool
called while the API is down answers with a tool error that says so; the server itself
stays up.

It binds to 127.0.0.1 only and has no authentication, which is right for one analyst's
own machine and wrong for anything else: the tools read the whole book, including the
holdings the broker link returns, and one of them writes to the thesis log.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import anyio
from mcp.server import Server, ServerRequestContext
from mcp.types import (CallToolRequestParams, CallToolResult, ListToolsResult,
                       PaginatedRequestParams, TextContent, Tool, ToolAnnotations)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
import mcp_tools  # noqa: E402  the catalogue, plain standard library

API = os.getenv("LENS_API", "http://127.0.0.1:8000").rstrip("/")
# The first read of a company's fair value recomputes the peer set, which has taken most
# of a minute cold. Long enough for that, short enough that a hung API is reported.
TIMEOUT_S = 240
VERSION = "1.0.0"


def fetch(method: str, path: str, params: dict | None, body: dict | None):
    """One request to the terminal's API: (status, parsed JSON or None). An HTTP error is
    an answer and is returned as one; only a connection that fails raises."""
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Accept": "application/json",
                                              "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    try:
        return status, json.loads(raw.decode("utf-8")) if raw else None
    except ValueError:
        return status, None


def _tools() -> list:
    return [Tool(name=t["name"], title=t["title"], description=t["description"],
                 input_schema=t["input_schema"],
                 annotations=ToolAnnotations(
                     title=t["title"], read_only_hint=t["read_only"],
                     destructive_hint=False, idempotent_hint=t["read_only"],
                     # The tools read this machine's own book; nothing reaches outward
                     # through them that the API does not already fetch for the page.
                     open_world_hint=False))
            for t in mcp_tools.catalogue()]


async def list_tools(ctx: ServerRequestContext,
                     params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=_tools())


async def call_tool(ctx: ServerRequestContext,
                    params: CallToolRequestParams) -> CallToolResult:
    """Run one tool off the event loop (it blocks on HTTP) and return its answer as JSON
    text. A tool that cannot answer is a result the model reads and can act on, not a
    protocol error it never sees."""
    try:
        data = await anyio.to_thread.run_sync(
            mcp_tools.call, params.name, params.arguments or {}, fetch)
    except mcp_tools.ToolError as exc:
        return CallToolResult(content=[TextContent(type="text", text=str(exc))],
                              is_error=True)
    except Exception as exc:              # a fault in a tool must not take the server down
        return CallToolResult(
            content=[TextContent(type="text",
                                 text=f"{params.name} failed: {type(exc).__name__}: {exc}")],
            is_error=True)
    text = json.dumps(data, default=str, ensure_ascii=False, separators=(",", ":"))
    return CallToolResult(content=[TextContent(type="text", text=text)])


server = Server("novatalis-lens", version=VERSION, title="Novatalis Lens",
                description="The Novatalis Lens research book: valuations, gates, "
                            "catalysts, positioning and the thesis log.",
                instructions=mcp_tools.INSTRUCTIONS,
                on_list_tools=list_tools, on_call_tool=call_tool)


async def _stdio() -> None:
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--http", type=int, metavar="PORT",
                        help="serve Streamable HTTP on 127.0.0.1:PORT/mcp instead of stdio")
    args = parser.parse_args()
    if args.http:
        import uvicorn
        app = server.streamable_http_app(json_response=True, stateless_http=True,
                                         host="127.0.0.1")
        uvicorn.run(app, host="127.0.0.1", port=args.http, log_level="warning")
    else:
        anyio.run(_stdio)


if __name__ == "__main__":
    main()
