"""Tool registry: imports MCP tool handler functions for direct invocation.

Provides call_tool(name, **kwargs) and TAB_TOOL_MAP for deterministic
tool selection based on intent classification.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from agents.mcp_server.tools import (
    main_tab,
    omnichannel_tab,
    engagement_tab,
    inventory_tab,
    reviews_tab,
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
    for module in (main_tab, omnichannel_tab, engagement_tab, inventory_tab, reviews_tab, timeseries, aggregated):
        for tool_def, handler in module.get_tools():
            _REGISTRY[tool_def.name] = handler

    logger.info("MCP tool registry loaded: %d tools", len(_REGISTRY))
    return _REGISTRY


# ── TTL cache for tool results ───────────────────────────────────

_TOOL_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL_SECONDS = 45


def _cache_key(name: str, kwargs: dict) -> str:
    """Build a deterministic cache key from tool name + arguments."""
    sorted_args = tuple(sorted(kwargs.items()))
    return f"{name}:{sorted_args}"


def invalidate_tool_cache() -> None:
    """Clear the entire tool result cache."""
    _TOOL_CACHE.clear()


def call_tool(name: str, **kwargs) -> dict:
    """Call an MCP tool handler by name with TTL caching and error wrapping."""
    registry = get_tool_registry()
    if name not in registry:
        return {"error": f"Unknown tool: {name}. Available: {sorted(registry.keys())}"}

    key = _cache_key(name, kwargs)
    now = time.monotonic()

    cached = _TOOL_CACHE.get(key)
    if cached is not None:
        ts, result = cached
        if now - ts < _CACHE_TTL_SECONDS:
            logger.debug("Cache hit for %s (age %.1fs)", name, now - ts)
            return result

    try:
        result = registry[name](**kwargs)
        _TOOL_CACHE[key] = (now, result)
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
        "metric_ids": ["revenue", "customers", "conversion", "aov", "clv", "return-rate"],
    },
    "omnichannel": {
        "summary": "get_omnichannel_metrics_summary",
        "drivers": "get_omnichannel_metric_drivers",
        "extra": ["get_channel_comparison"],
        "metric_ids": [
            "omni-arrival-rate", "omni-conversion", "omni-cart-abandon",
            "omni-avg-journey", "omni-total-orders", "omni-ontime",
            "omni-fulfillment-dur", "omni-payment-success",
        ],
    },
    "customer-engagement": {
        "summary": "get_engagement_metrics_summary",
        "drivers": "get_engagement_metric_drivers",
        "extra": ["get_segment_analysis"],
        "metric_ids": [
            "ce-active-rate", "ce-churn-rate", "ce-open-rate", "ce-campaign-ctr",
            "ce-enrollment-rate", "ce-redemption-rate", "ce-resolution-rate", "ce-satisfaction",
        ],
    },
    "inventory-replenishment": {
        "summary": "get_inventory_metrics_summary",
        "drivers": "get_inventory_metric_drivers",
        "extra": ["get_sku_analysis"],
        "metric_ids": [
            "ir-qty-on-hand", "ir-below-reorder", "ir-stockout-count", "ir-fill-rate",
            "ir-supplier-ontime", "ir-avg-lead-time", "ir-turnover", "ir-shrinkage-rate",
        ],
    },
    "customer-reviews": {
        "summary": "get_reviews_metrics_summary",
        "drivers": "get_reviews_metric_drivers",
        "extra": ["get_review_analysis"],
        "metric_ids": [
            "cr-avg-sentiment", "cr-review-volume", "cr-positive-rate",
            "cr-negative-rate", "cr-response-rate",
        ],
    },
}
