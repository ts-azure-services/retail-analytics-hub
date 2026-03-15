"""@executor functions for the explainer workflow."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from typing_extensions import Never

from opentelemetry import context as otel_context, trace

from agent_framework import executor, AgentExecutorResponse, WorkflowContext

from agents.shared.mcp_tools import call_tool, TAB_TOOL_MAP

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

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

    tab_tools = TAB_TOOL_MAP.get(tab, TAB_TOOL_MAP.get("main", {}))

    # Fall back to all metrics for the tab when the classifier returns none
    if not metric_ids:
        metric_ids = tab_tools.get("metric_ids", [])

    gathered: dict = {"intent": intent, "data": {}}

    # Build a list of (result_key, tool_name, kwargs) to run in parallel
    tasks: list[tuple[str, str, dict]] = []

    # 1. Summary tool
    summary_tool = tab_tools.get("summary")
    if summary_tool:
        tasks.append(("summary", summary_tool, {}))

    # 2. Driver tool for each metric_id
    driver_tool = tab_tools.get("drivers")
    if driver_tool and metric_ids:
        for mid in metric_ids:
            tasks.append((f"drivers.{mid}", driver_tool, {"metric_id": mid}))

    # 3. Extra tools for comparison/analysis questions
    if question_type in ("comparison", "general"):
        for tool_name in tab_tools.get("extra", []):
            tasks.append((f"extras.{tool_name}", tool_name, {}))

    # Execute all tool calls concurrently with OTEL context propagation
    results: dict[str, dict] = {}
    parent_ctx = otel_context.get_current()

    def _call_with_context(tool_name: str, **kw) -> dict:
        token = otel_context.attach(parent_ctx)
        try:
            return call_tool(tool_name, **kw)
        finally:
            otel_context.detach(token)

    with _tracer.start_as_current_span("gather_data.parallel_tools", attributes={"tool.count": len(tasks)}):
        with ThreadPoolExecutor(max_workers=min(len(tasks), 8)) as pool:
            future_map = {
                pool.submit(_call_with_context, tool_name, **kwargs): result_key
                for result_key, tool_name, kwargs in tasks
            }
            for future in as_completed(future_map):
                result_key = future_map[future]
                results[result_key] = future.result()

    # Assemble results into the expected structure
    if "summary" in results:
        gathered["data"]["summary"] = results.pop("summary")

    drivers = {k.split(".", 1)[1]: v for k, v in results.items() if k.startswith("drivers.")}
    if drivers:
        gathered["data"]["drivers"] = drivers

    extras = {k.split(".", 1)[1]: v for k, v in results.items() if k.startswith("extras.")}
    if extras:
        gathered["data"]["extras"] = extras

    data_text = json.dumps(gathered, default=str)
    logger.info("Gathered data for tab=%s metrics=%s (%d chars)", tab, metric_ids, len(data_text))

    await ctx.send_message(data_text)


@executor(id="extract_output")
async def extract_output(response: AgentExecutorResponse, ctx: WorkflowContext[Never, str]) -> None:
    """Pass through the formatter's response as the final output."""
    text = response.agent_run_response.text or ""
    await ctx.yield_output(text)
