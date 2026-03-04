"""@executor functions for the explainer workflow."""

import json
import logging

from typing_extensions import Never

from agent_framework import executor, AgentExecutorResponse, WorkflowContext

from agents.shared.mcp_tools import call_tool, TAB_TOOL_MAP

logger = logging.getLogger(__name__)

_SOURCE = "agent1-explainer"

# Shared context passed between executors via module-level dict
# (AgentExecutorResponse doesn't carry custom metadata)
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
    """Package the ChatRequest fields into the prompt for the intent classifier."""
    payload = json.loads(text)
    prompt = (
        f"User question: {payload['message']}\n"
        f"Active tab: {payload['active_tab']}\n"
        f"Current view: {payload['current_view']}\n"
        f"Selected metric: {payload.get('selected_metric_id') or 'none'}"
    )
    _context["active_tab"] = payload["active_tab"]
    _context["message"] = payload["message"]
    await ctx.send_message(prompt)


@executor(id="gather_data")
async def gather_data(response: AgentExecutorResponse, ctx: WorkflowContext[str]) -> None:
    """Parse intent JSON and call MCP tool handlers to gather data."""
    text = response.agent_run_response.text or ""
    active_tab = _context.get("active_tab", "main")

    try:
        intent = _parse_json(text)
    except (json.JSONDecodeError, IndexError):
        intent = {"tab": active_tab, "metric_ids": [], "question_type": "general"}

    tab = intent.get("tab", active_tab)
    metric_ids = intent.get("metric_ids", [])
    question_type = intent.get("question_type", "general")

    gathered = {"intent": intent, "data": {}}

    # 1. Summary tool for the classified tab
    tab_tools = TAB_TOOL_MAP.get(tab, TAB_TOOL_MAP.get("main", {}))
    summary_tool = tab_tools.get("summary")
    if summary_tool:
        gathered["data"]["summary"] = call_tool(summary_tool)

    # 2. Driver tool for each metric_id
    driver_tool = tab_tools.get("drivers")
    if driver_tool and metric_ids:
        gathered["data"]["drivers"] = {}
        for mid in metric_ids:
            gathered["data"]["drivers"][mid] = call_tool(driver_tool, metric_id=mid)

    # 3. Extra tools for comparison/analysis questions
    if question_type in ("comparison", "general"):
        extras = tab_tools.get("extra", [])
        if extras:
            gathered["data"]["extras"] = {}
            for tool_name in extras:
                gathered["data"]["extras"][tool_name] = call_tool(tool_name)

    data_text = json.dumps(gathered, default=str)
    logger.info("Gathered data for tab=%s metrics=%s (%d chars)", tab, metric_ids, len(data_text))

    await ctx.send_message(data_text)


@executor(id="extract_output")
async def extract_output(response: AgentExecutorResponse, ctx: WorkflowContext[Never, str]) -> None:
    """Pass through the formatter's response as the final output."""
    text = response.agent_run_response.text or ""
    await ctx.yield_output(text)
