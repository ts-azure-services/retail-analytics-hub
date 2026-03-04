"""WorkflowBuilder orchestration for the sentiment analysis pipeline."""

from __future__ import annotations

import json
import logging

from agent_framework import WorkflowBuilder, WorkflowOutputEvent

from agents.agent3_sentiment.agents import (
    create_classifier_executor,
    create_responder_executor,
)
from agents.agent3_sentiment.executors import (
    fetch_review,
    adapt_classification,
    persist_results,
)

logger = logging.getLogger(__name__)

_workflow = None


def get_workflow():
    """Lazily build and cache the sentiment analysis workflow."""
    global _workflow
    if _workflow is not None:
        return _workflow

    classifier_executor = create_classifier_executor()
    responder_executor = create_responder_executor()

    _workflow = (
        WorkflowBuilder()
        .set_start_executor(fetch_review)
        .add_edge(fetch_review, classifier_executor)
        .add_edge(classifier_executor, adapt_classification)
        .add_edge(adapt_classification, responder_executor)
        .add_edge(responder_executor, persist_results)
        .build()
    )
    return _workflow


async def analyze_review(review_id: int, review_text: str) -> dict:
    """Run a single review through the sentiment pipeline and return the result."""
    workflow = get_workflow()
    input_data = json.dumps({"review_id": review_id, "review_text": review_text})

    result: dict = {}
    async for event in workflow.run_stream(input_data):
        if isinstance(event, WorkflowOutputEvent):
            result = json.loads(str(event.data))

    return result
