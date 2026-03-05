"""Agent + AgentExecutor creation functions for the explainer pipeline."""

from __future__ import annotations

from agent_framework import ChatAgent, AgentExecutor
from agent_framework.azure import AzureOpenAIChatClient

from agents.shared.config import get_settings, get_azure_token_provider
from agents.agent1_explainer.prompts import (
    INTENT_SYSTEM_PROMPT,
    ANALYZER_SYSTEM_PROMPT,
    FORMATTER_SYSTEM_PROMPT,
)


def create_intent_classifier() -> AgentExecutor:
    """Create the intent classification AgentExecutor."""
    settings = get_settings()
    client = AzureOpenAIChatClient(
        endpoint=settings.azure_openai_endpoint,
        ad_token_provider=get_azure_token_provider(),
        api_version=settings.azure_openai_api_version,
        deployment_name="gpt-4o-mini",
    )
    agent = ChatAgent(
        chat_client=client,
        name="Intent Classifier",
        instructions=INTENT_SYSTEM_PROMPT,
    )
    return AgentExecutor(agent, id="intent_classifier")


def create_data_analyzer() -> AgentExecutor:
    """Create the data analyzer AgentExecutor."""
    settings = get_settings()
    client = AzureOpenAIChatClient(
        endpoint=settings.azure_openai_endpoint,
        ad_token_provider=get_azure_token_provider(),
        api_version=settings.azure_openai_api_version,
        deployment_name="gpt-4o-mini",
    )
    agent = ChatAgent(
        chat_client=client,
        name="Data Analyzer",
        instructions=ANALYZER_SYSTEM_PROMPT,
    )
    return AgentExecutor(agent, id="data_analyzer")


def create_response_formatter() -> AgentExecutor:
    """Create the response formatter AgentExecutor."""
    settings = get_settings()
    client = AzureOpenAIChatClient(
        endpoint=settings.azure_openai_endpoint,
        ad_token_provider=get_azure_token_provider(),
        api_version=settings.azure_openai_api_version,
        deployment_name="gpt-4o-mini",
    )
    agent = ChatAgent(
        chat_client=client,
        name="Response Formatter",
        instructions=FORMATTER_SYSTEM_PROMPT,
    )
    return AgentExecutor(agent, id="response_formatter")
