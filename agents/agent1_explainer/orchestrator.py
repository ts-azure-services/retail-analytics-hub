"""Orchestrator for Agent 1 — Sequential pipeline: intent → planner → formatter."""

from __future__ import annotations

import logging

from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination

from agents.shared.config import get_settings
from agents.shared.models import ChatRequest

from .agents.intent import create_intent_agent, parse_intent_result
from .agents.planner import create_planner_agent
from .agents.formatter import create_formatter_agent

logger = logging.getLogger(__name__)


async def run_explainer_pipeline(request: ChatRequest) -> str:
    """Run the 3-stage explainer pipeline and return the formatted response."""

    settings = get_settings()

    logger.info("Starting explainer pipeline for tab=%s message=%s", request.active_tab, request.message[:80])

    # Create sub-agents
    intent_agent = create_intent_agent()
    planner_agent = await create_planner_agent()
    formatter_agent = create_formatter_agent()

    # 3 agents × 1 round = 3 messages; allow 4 for tool call overhead
    termination = MaxMessageTermination(max_messages=4)

    # RoundRobinGroupChat ensures strict sequential order:
    # intent_classifier → data_planner → response_formatter
    team = RoundRobinGroupChat(
        participants=[intent_agent, planner_agent, formatter_agent],
        termination_condition=termination,
    )

    # Build the input message with context
    input_msg = f"""User question: {request.message}
Active tab: {request.active_tab}
Current view: {request.current_view}
Selected metric: {request.selected_metric_id or 'none'}"""

    # Run the team
    last_message = ""
    try:
        async for message in team.run_stream(task=input_msg):
            if hasattr(message, "messages"):
                # This is the final TaskResult
                for msg in message.messages:
                    if hasattr(msg, "content") and isinstance(msg.content, str):
                        logger.info("Agent [%s]: %s", getattr(msg, "source", "?"), msg.content[:120])
                        if getattr(msg, "source", "") == "response_formatter":
                            last_message = msg.content
            elif hasattr(message, "content") and hasattr(message, "source"):
                logger.info("Stream [%s]: %s", message.source, str(message.content)[:120])
                if message.source == "response_formatter" and isinstance(message.content, str):
                    last_message = message.content
    except Exception:
        logger.exception("Pipeline error")

    await team.reset()
    logger.info("Pipeline finished. Got response: %s", bool(last_message))
    return last_message or "I wasn't able to generate a response. Please try rephrasing your question."
