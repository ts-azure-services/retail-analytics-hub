"""Tool registry: imports MCP tool handler functions for direct invocation.

Provides call_tool(name, **kwargs) and TAB_TOOL_MAP for deterministic
tool selection based on intent classification.
"""

from __future__ import annotations

import logging
from typing import Callable

from agents.mcp_server.tools import (
    main_tab,
    omnichannel_tab,
    engagement_tab,
    inventory_tab,
    timeseries,
    aggregated,
)

logger = logging.getLogger(__name__)

# ── Tool registry ────────────────────────────────────────────────

_REGISTRY: dict[str, Callable] | None = None


def get_tool_registry() -> dict[str, Callable]:
    """Lazily build and cache name → handler_fn mapping."""
    global _REGISTRY
    if _REGISTRY is not None:
        return _REGISTRY

    _REGISTRY = {}
    for module in (main_tab, omnichannel_tab, engagement_tab, inventory_tab, timeseries, aggregated):
        for tool_def, handler in module.get_tools():
            _REGISTRY[tool_def.name] = handler

    logger.info("MCP tool registry loaded: %d tools", len(_REGISTRY))
    return _REGISTRY


def call_tool(name: str, **kwargs) -> dict:
    """Call an MCP tool handler by name with error wrapping."""
    registry = get_tool_registry()
    if name not in registry:
        return {"error": f"Unknown tool: {name}. Available: {sorted(registry.keys())}"}

    try:
        result = registry[name](**kwargs)
        return result
    except Exception as e:
        logger.exception("Tool %s failed", name)
        return {"error": f"Tool {name} failed: {e}"}


# ── Tab → tool name mapping ─────────────────────────────────────

TAB_TOOL_MAP: dict[str, dict] = {
    "main": {
        "summary": "get_main_metrics_summary",
        "drivers": "get_main_metric_drivers",
        "extra": [],
    },
    "omnichannel": {
        "summary": "get_omnichannel_metrics_summary",
        "drivers": "get_omnichannel_metric_drivers",
        "extra": ["get_channel_comparison"],
    },
    "customer-engagement": {
        "summary": "get_engagement_metrics_summary",
        "drivers": "get_engagement_metric_drivers",
        "extra": ["get_segment_analysis"],
    },
    "inventory-replenishment": {
        "summary": "get_inventory_metrics_summary",
        "drivers": "get_inventory_metric_drivers",
        "extra": ["get_sku_analysis"],
    },
}
