"""@executor functions for the narrative workflow."""

import json
import logging

from typing_extensions import Never

from agent_framework import executor, AgentExecutorResponse, WorkflowContext

from agents.shared.mcp_tools import call_tool, TAB_TOOL_MAP

logger = logging.getLogger(__name__)

_SOURCE = "agent2-narrative"

# Shared context between executors (AgentExecutorResponse doesn't carry custom metadata)
_context: dict = {}


def _parse_json(text: str) -> dict:
    """Parse JSON from text, handling markdown code blocks."""
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    return json.loads(text.strip())


@executor(id="prepare_input")
async def prepare_input(text: str, ctx: WorkflowContext[str]) -> None:
    """Package the request into a prompt for the intent classifier."""
    payload = json.loads(text)
    mode = payload.get("mode", "narrative")
    _context["mode"] = mode

    if mode == "chat":
        prompt = (
            f"User question: {payload['message']}\n"
            f"Active tab: {payload.get('active_tab', 'main')}\n"
            f"Current view: {payload.get('current_view', 'dashboard')}\n"
            f"Selected metric: {payload.get('selected_metric_id') or 'none'}\n\n"
            "Provide a deep, data-driven analysis with cross-tab insights and recommendations."
        )
    else:
        focus = payload.get("focus_areas", [])
        prompt = (
            "Generate a comprehensive business narrative.\n"
            f"User request: {payload['message']}\n"
            f"Focus areas: {', '.join(focus) if focus else 'all areas'}\n\n"
            "Analyze all available data across revenue, operations, customer engagement, and inventory to provide\n"
            "a complete picture of business performance with actionable recommendations."
        )

    await ctx.send_message(prompt)


@executor(id="gather_data")
async def gather_data(response: AgentExecutorResponse, ctx: WorkflowContext[str]) -> None:
    """Parse intent JSON and call MCP tool handlers — broader scope than Agent 1."""
    text = response.agent_run_response.text or ""

    try:
        intent = _parse_json(text)
    except (json.JSONDecodeError, IndexError):
        intent = {
            "decision_domain": "cross_functional",
            "tabs_to_query": ["main", "omnichannel", "customer-engagement", "inventory-replenishment"],
        }

    tabs = intent.get("tabs_to_query", ["main"])
    domain = intent.get("decision_domain", "cross_functional")

    gathered = {"intent": intent, "data": {}}

    # 1. Summary + extras for ALL tabs in tabs_to_query
    for tab in tabs:
        tab_tools = TAB_TOOL_MAP.get(tab)
        if not tab_tools:
            continue
        summary_tool = tab_tools.get("summary")
        if summary_tool:
            gathered["data"][f"{tab}_summary"] = call_tool(summary_tool)
        for extra_tool in tab_tools.get("extra", []):
            gathered["data"][extra_tool] = call_tool(extra_tool)

    # 2. Cross-tab health check
    gathered["data"]["health_check"] = call_tool("get_cross_tab_health_check")

    # 3. Timeseries data
    gathered["data"]["demand_trend"] = call_tool("get_hourly_demand_trend", hours=48)
    gathered["data"]["demand_by_hour"] = call_tool("get_demand_by_hour_of_day")

    # 4. Correlation analysis for cross-functional questions
    if domain == "cross_functional" or len(tabs) > 1:
        gathered["data"]["correlations"] = call_tool(
            "get_correlation_analysis", metric_a="conversion", metric_b="revenue"
        )

    data_text = json.dumps(gathered, default=str)
    logger.info("Gathered narrative data for tabs=%s (%d chars)", tabs, len(data_text))

    await ctx.send_message(data_text)


@executor(id="extract_output")
async def extract_output(response: AgentExecutorResponse, ctx: WorkflowContext[Never, str]) -> None:
    """Pass through the formatter's response as the final output."""
    text = response.agent_run_response.text or ""
    await ctx.yield_output(text)
