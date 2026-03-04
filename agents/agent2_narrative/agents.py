"""Agent + AgentExecutor creation functions for the narrative pipeline."""

from __future__ import annotations

from agent_framework import ChatAgent, AgentExecutor
from agent_framework.azure import AzureOpenAIChatClient

from agents.shared.config import get_settings
from agents.agent2_narrative.prompts import (
    INTENT_SYSTEM_PROMPT,
    ANALYZER_SYSTEM_PROMPT,
    REASONER_SYSTEM_PROMPT,
    FORMATTER_SYSTEM_PROMPT,
)


def create_intent_classifier() -> AgentExecutor:
    """Create the narrative intent classification AgentExecutor."""
    settings = get_settings()
    client = AzureOpenAIChatClient(
        endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
        deployment_name="gpt-4o-mini",
    )
    agent = ChatAgent(
        chat_client=client,
        instructions=INTENT_SYSTEM_PROMPT,
        name="Narrative Intent",
    )
    return AgentExecutor(agent, id="intent_classifier")


def create_data_analyzer() -> AgentExecutor:
    """Create the data analyzer AgentExecutor (gpt-4o for comprehensive synthesis)."""
    settings = get_settings()
    client = AzureOpenAIChatClient(
        endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
        deployment_name="gpt-4o",
    )
    agent = ChatAgent(
        chat_client=client,
        instructions=ANALYZER_SYSTEM_PROMPT,
        name="Data Analyzer",
    )
    return AgentExecutor(agent, id="data_analyzer")


def create_deep_reasoner() -> AgentExecutor:
    """Create the deep reasoner AgentExecutor (gpt-4o for causal analysis)."""
    settings = get_settings()
    client = AzureOpenAIChatClient(
        endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
        deployment_name="gpt-4o",
    )
    agent = ChatAgent(
        chat_client=client,
        instructions=REASONER_SYSTEM_PROMPT,
        name="Deep Reasoner",
    )
    return AgentExecutor(agent, id="deep_reasoner")


def create_narrative_formatter() -> AgentExecutor:
    """Create the narrative formatter AgentExecutor."""
    settings = get_settings()
    client = AzureOpenAIChatClient(
        endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
        deployment_name="gpt-4o-mini",
    )
    agent = ChatAgent(
        chat_client=client,
        instructions=FORMATTER_SYSTEM_PROMPT,
        name="Narrative Formatter",
    )
    return AgentExecutor(agent, id="narrative_formatter")
