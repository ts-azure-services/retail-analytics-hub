"""Formatter sub-agent for Agent 2 — executive narrative formatting."""

from __future__ import annotations

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient

from agents.shared.config import get_settings
from ..prompts import FORMATTER_SYSTEM_PROMPT


def create_formatter_agent() -> AssistantAgent:
    settings = get_settings()
    model_client = AzureOpenAIChatCompletionClient(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
        model="gpt-4o-mini",
        temperature=0.5,
    )
    return AssistantAgent(
        name="narrative_formatter",
        system_message=FORMATTER_SYSTEM_PROMPT,
        model_client=model_client,
    )
