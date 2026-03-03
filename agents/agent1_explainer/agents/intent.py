"""Intent classification sub-agent for Agent 1."""

from __future__ import annotations

import json

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient

from agents.shared.config import get_settings
from agents.shared.models import IntentResult, TabId, QuestionType
from ..prompts import INTENT_SYSTEM_PROMPT


def create_intent_agent() -> AssistantAgent:
    settings = get_settings()
    model_client = AzureOpenAIChatCompletionClient(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
        model="gpt-4o-mini",
        temperature=0.1,
    )
    return AssistantAgent(
        name="intent_classifier",
        system_message=INTENT_SYSTEM_PROMPT,
        model_client=model_client,
    )


def parse_intent_result(text: str, active_tab: str = "main") -> IntentResult:
    """Parse the intent agent's JSON response into an IntentResult."""
    try:
        # Extract JSON from possible markdown code blocks
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        data = json.loads(text.strip())
        return IntentResult(
            tab=TabId(data.get("tab", active_tab)),
            metric_ids=data.get("metric_ids", []),
            question_type=QuestionType(data.get("question_type", "general")),
            original_question=data.get("original_question", ""),
            clarified_question=data.get("clarified_question", ""),
        )
    except (json.JSONDecodeError, ValueError):
        # Fallback: use active_tab and treat as general question
        return IntentResult(
            tab=TabId(active_tab) if active_tab in [t.value for t in TabId] else TabId.MAIN,
            question_type=QuestionType.GENERAL,
            original_question=text,
            clarified_question=text,
        )
