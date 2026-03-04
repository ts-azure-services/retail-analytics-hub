"""@executor functions for the sentiment analysis workflow."""

import json
import logging

from typing_extensions import Never

from agent_framework import executor, AgentExecutorResponse, WorkflowContext

from agents.agent3_sentiment import db

logger = logging.getLogger(__name__)

_SOURCE = "agent3-sentiment"

# Shared context between executors (AgentExecutorResponse doesn't carry custom metadata)
_context: dict = {}


def _parse_json(text: str) -> dict:
    """Parse JSON from text, handling markdown code blocks."""
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    return json.loads(text.strip())


@executor(id="fetch_review")
async def fetch_review(text: str, ctx: WorkflowContext[str]) -> None:
    """Receive review_id + text and package for the classifier agent."""
    payload = json.loads(text)
    review_id = payload["review_id"]
    review_text = payload["review_text"]
    _context["review_id"] = review_id
    _context["review_text"] = review_text
    await ctx.send_message(review_text)


@executor(id="adapt_classification")
async def adapt_classification(response: AgentExecutorResponse, ctx: WorkflowContext[str]) -> None:
    """Extract classifier JSON and package for the responder agent."""
    text = response.agent_run_response.text or ""

    try:
        classification = _parse_json(text)
    except (json.JSONDecodeError, IndexError):
        classification = {"sentiment_category": "neutral", "sentiment_score": 0.0}

    review_text = _context.get("review_text", "")
    _context["sentiment_category"] = classification.get("sentiment_category", "neutral")
    _context["sentiment_score"] = classification.get("sentiment_score", 0.0)
    _context["key_phrases"] = classification.get("key_phrases", [])
    _context["confidence"] = classification.get("confidence", 0.0)

    responder_input = {
        "review_text": review_text,
        "sentiment_category": _context["sentiment_category"],
        "sentiment_score": _context["sentiment_score"],
    }
    await ctx.send_message(json.dumps(responder_input))


@executor(id="persist_results")
async def persist_results(response: AgentExecutorResponse, ctx: WorkflowContext[Never, str]) -> None:
    """Parse responder JSON, update DuckDB, yield final output."""
    text = response.agent_run_response.text or ""

    try:
        response = _parse_json(text)
    except (json.JSONDecodeError, IndexError):
        response = {}

    review_id = _context.get("review_id")
    sentiment_category = _context.get("sentiment_category", "")
    sentiment_score = _context.get("sentiment_score", 0.0)

    status = response.get("status", "processed for response")
    chatbot_statement = response.get("chatbot_statement")
    needs_human_review = response.get("needs_human_review", False)

    if review_id is not None:
        db.update_review_result(
            review_id,
            sentiment_category=sentiment_category,
            sentiment_score=sentiment_score,
            status=status,
            chatbot_statement=chatbot_statement,
        )
        logger.info("Review %s → %s (%s)", review_id, status, sentiment_category)

    result = {
        "review_id": review_id,
        "sentiment_category": sentiment_category,
        "sentiment_score": sentiment_score,
        "status": status,
        "chatbot_statement": chatbot_statement,
        "needs_human_review": needs_human_review,
    }
    await ctx.yield_output(json.dumps(result))
