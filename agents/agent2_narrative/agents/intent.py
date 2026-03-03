"""Intent classification sub-agent for Agent 2 — Business Narrative."""

from __future__ import annotations

import json

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient

from agents.shared.config import get_settings
from agents.shared.models import NarrativeIntentResult, DecisionDomain, TimeHorizon, Urgency, TabId
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
        name="narrative_intent",
        system_message=INTENT_SYSTEM_PROMPT,
        model_client=model_client,
    )


def parse_intent_result(text: str) -> NarrativeIntentResult:
    """Parse the intent agent's JSON response."""
    try:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        data = json.loads(text.strip())
        return NarrativeIntentResult(
            decision_domain=DecisionDomain(data.get("decision_domain", "cross_functional")),
            time_horizon=TimeHorizon(data.get("time_horizon", "short_term")),
            urgency=Urgency(data.get("urgency", "medium")),
            sub_questions=data.get("sub_questions", []),
            original_question=data.get("original_question", ""),
            tabs_to_query=[TabId(t) for t in data.get("tabs_to_query", ["main"])],
        )
    except (json.JSONDecodeError, ValueError):
        return NarrativeIntentResult(
            decision_domain=DecisionDomain.CROSS_FUNCTIONAL,
            tabs_to_query=[TabId.MAIN, TabId.OMNICHANNEL, TabId.CUSTOMER_ENGAGEMENT, TabId.INVENTORY_REPLENISHMENT],
        )
