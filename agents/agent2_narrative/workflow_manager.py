"""WorkflowBuilder orchestration for the narrative pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from agent_framework import WorkflowBuilder, WorkflowOutputEvent

from agents.shared.models import ChatRequest, NarrativeRequest
from agents.agent2_narrative.agents import (
    create_intent_classifier,
    create_data_analyzer,
    create_deep_reasoner,
    create_narrative_formatter,
)
from agents.agent2_narrative.executors import (
    prepare_input,
    gather_data,
    extract_output,
)

logger = logging.getLogger(__name__)

def _build_workflow():
    """Build a new narrative workflow instance.

    A fresh instance is created per request because the agent_framework
    Workflow does not allow concurrent executions on the same instance.
    """
    intent_classifier = create_intent_classifier()
    data_analyzer = create_data_analyzer()
    deep_reasoner = create_deep_reasoner()
    narrative_formatter = create_narrative_formatter()

    return (
        WorkflowBuilder()
        .set_start_executor(prepare_input)
        .add_edge(prepare_input, intent_classifier)
        .add_edge(intent_classifier, gather_data)
        .add_edge(gather_data, data_analyzer)
        .add_edge(data_analyzer, deep_reasoner)
        .add_edge(deep_reasoner, narrative_formatter)
        .add_edge(narrative_formatter, extract_output)
        .build()
    )


async def _run_pipeline(input_payload: dict) -> str:
    """Run the narrative pipeline with the given payload."""
    workflow = _build_workflow()
    input_data = json.dumps(input_payload)

    logger.info("Starting narrative pipeline")

    result_text = ""
    async for event in workflow.run_stream(input_data):
        if isinstance(event, WorkflowOutputEvent):
            result_text = str(event.data) if event.data else ""

    logger.info("Narrative pipeline finished. Got response: %s", bool(result_text))
    return result_text or "Unable to generate narrative. Please try again."


async def run_narrative_pipeline(request: NarrativeRequest) -> str:
    """Generate a business narrative."""
    return await _run_pipeline({
        "mode": "narrative",
        "message": request.message,
        "focus_areas": request.focus_areas,
    })


async def run_chat_pipeline(request: ChatRequest) -> str:
    """Handle interactive follow-up questions with narrative depth."""
    return await _run_pipeline({
        "mode": "chat",
        "message": request.message,
        "active_tab": request.active_tab,
        "current_view": request.current_view,
        "selected_metric_id": request.selected_metric_id,
    })


async def stream_chat_pipeline(
    request: ChatRequest,
) -> AsyncGenerator[dict[str, str], None]:
    """Run the chat pipeline and yield SSE events.

    Events emitted:
      event=status  – pipeline stage progress
      event=chunk   – partial response text
      event=done    – final complete response + metadata
      event=error   – error message
    """
    yield {"event": "status", "data": json.dumps({"stage": "processing", "message": "Synthesizing narrative…"})}

    try:
        response_text = await run_chat_pipeline(request)
    except Exception as exc:
        logger.exception("Streaming chat pipeline error")
        yield {"event": "error", "data": json.dumps({"message": str(exc)})}
        return

    words = response_text.split(" ")
    buffer = ""
    for i, word in enumerate(words):
        buffer += (" " if buffer else "") + word
        at_end = i == len(words) - 1
        if len(buffer) >= 25 or word.endswith((".", "!", "?", ":", "\n")) or at_end:
            yield {"event": "chunk", "data": buffer}
            buffer = ""
            if not at_end:
                await asyncio.sleep(0.015)

    if buffer:
        yield {"event": "chunk", "data": buffer}

    yield {
        "event": "done",
        "data": json.dumps({
            "response": response_text,
            "agent": "narrative",
            "metadata": {
                "active_tab": request.active_tab,
                "current_view": request.current_view,
            },
        }),
    }
