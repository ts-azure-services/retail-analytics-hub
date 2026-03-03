"""MCP stdio server entry point.

Exposes SQL-backed tools for each dashboard tab, plus timeseries and
cross-tab aggregated queries.  Both Agent 1 and Agent 2 spawn this as a
subprocess via stdio transport.
"""

from __future__ import annotations

import json
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .tools import main_tab, omnichannel_tab, engagement_tab, inventory_tab, timeseries, aggregated

app = Server("retail-analytics-mcp")

# ── Collect tools from all modules ────────────────────────────────

_TOOL_REGISTRY: dict[str, tuple] = {}  # name → (handler_fn, Tool)


def _register_module(module):
    for tool_def, handler in module.get_tools():
        _TOOL_REGISTRY[tool_def.name] = (handler, tool_def)


_register_module(main_tab)
_register_module(omnichannel_tab)
_register_module(engagement_tab)
_register_module(inventory_tab)
_register_module(timeseries)
_register_module(aggregated)


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [tool_def for _, tool_def in _TOOL_REGISTRY.values()]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name not in _TOOL_REGISTRY:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    handler, _ = _TOOL_REGISTRY[name]
    try:
        result = handler(**arguments)
        return [TextContent(type="text", text=json.dumps(result, default=str))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
