"""Orchestrator for Agent 2 — 4-stage pipeline: intent → planner → analyzer → formatter."""

from __future__ import annotations

import logging

from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination

from agents.shared.config import get_settings
from agents.shared.models import ChatRequest, NarrativeRequest

from .agents.intent import create_intent_agent
from .agents.planner import create_planner_agent
from .agents.analyzer import create_analyzer_agent
from .agents.formatter import create_formatter_agent

logger = logging.getLogger(__name__)


async def _run_pipeline(input_msg: str) -> str:
    """Run the 4-stage narrative pipeline."""
    settings = get_settings()

    logger.info("Starting narrative pipeline")

    # Create sub-agents
    intent_agent = create_intent_agent()
    planner_agent = await create_planner_agent()
    analyzer_agent = create_analyzer_agent()
    formatter_agent = create_formatter_agent()

    # 4 agents × 1 round = 4 messages; allow 5 for tool call overhead
    termination = MaxMessageTermination(max_messages=5)

    # RoundRobinGroupChat ensures strict sequential order
    team = RoundRobinGroupChat(
        participants=[intent_agent, planner_agent, analyzer_agent, formatter_agent],
        termination_condition=termination,
    )

    last_message = ""
    try:
        async for message in team.run_stream(task=input_msg):
            if hasattr(message, "messages"):
                for msg in message.messages:
                    if hasattr(msg, "content") and isinstance(msg.content, str):
                        logger.info("Agent [%s]: %s", getattr(msg, "source", "?"), msg.content[:120])
                        if getattr(msg, "source", "") == "narrative_formatter":
                            last_message = msg.content
            elif hasattr(message, "content") and hasattr(message, "source"):
                logger.info("Stream [%s]: %s", message.source, str(message.content)[:120])
                if message.source == "narrative_formatter" and isinstance(message.content, str):
                    last_message = message.content
    except Exception:
        logger.exception("Narrative pipeline error")

    await team.reset()
    logger.info("Narrative pipeline finished. Got response: %s", bool(last_message))
    return last_message or "Unable to generate narrative. Please try again."


async def run_narrative_pipeline(request: NarrativeRequest) -> str:
    """Generate a business narrative."""
    input_msg = f"""Generate a comprehensive business narrative.
User request: {request.message}
Focus areas: {', '.join(request.focus_areas) if request.focus_areas else 'all areas'}

Analyze all available data across revenue, operations, customer engagement, and inventory to provide
a complete picture of business performance with actionable recommendations."""
    return await _run_pipeline(input_msg)


async def run_chat_pipeline(request: ChatRequest) -> str:
    """Handle interactive follow-up questions with full narrative depth."""
    input_msg = f"""User question: {request.message}
Active tab: {request.active_tab}
Current view: {request.current_view}
Selected metric: {request.selected_metric_id or 'none'}

Provide a deep, data-driven analysis with cross-tab insights and recommendations."""
    return await _run_pipeline(input_msg)
