"""WorkflowBuilder orchestration for the explainer pipeline."""

from __future__ import annotations

import json
import logging

from agent_framework import WorkflowBuilder, WorkflowOutputEvent

from agents.shared.models import ChatRequest
from agents.agent1_explainer.agents import (
    create_intent_classifier,
    create_data_analyzer,
    create_response_formatter,
)
from agents.agent1_explainer.executors import (
    prepare_input,
    gather_data,
    extract_output,
)

logger = logging.getLogger(__name__)

def _build_workflow():
    """Build a new explainer workflow instance.

    A fresh instance is created per request because the agent_framework
    Workflow does not allow concurrent executions on the same instance.
    """
    intent_classifier = create_intent_classifier()
    data_analyzer = create_data_analyzer()
    response_formatter = create_response_formatter()

    return (
        WorkflowBuilder()
        .set_start_executor(prepare_input)
        .add_edge(prepare_input, intent_classifier)
        .add_edge(intent_classifier, gather_data)
        .add_edge(gather_data, data_analyzer)
        .add_edge(data_analyzer, response_formatter)
        .add_edge(response_formatter, extract_output)
        .build()
    )


async def run_explainer_pipeline(request: ChatRequest) -> str:
    """Run the explainer pipeline and return the formatted response."""
    workflow = _build_workflow()
    input_payload = {
        "message": request.message,
        "active_tab": request.active_tab,
        "current_view": request.current_view,
        "selected_metric_id": request.selected_metric_id,
    }
    input_data = json.dumps(input_payload)

    logger.info(
        "Starting explainer pipeline for tab=%s message=%s",
        request.active_tab,
        request.message[:80],
    )

    result_text = ""
    async for event in workflow.run_stream(input_data):
        if isinstance(event, WorkflowOutputEvent):
            result_text = str(event.data) if event.data else ""

    logger.info("Pipeline finished. Got response: %s", bool(result_text))
    return result_text or "I wasn't able to generate a response. Please try rephrasing your question."
