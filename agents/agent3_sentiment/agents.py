"""Agent + AgentExecutor creation functions for the sentiment pipeline."""

from __future__ import annotations

from agent_framework import ChatAgent, AgentExecutor
from agent_framework.azure import AzureOpenAIChatClient

from agents.shared.config import get_settings, get_azure_token_provider
from agents.agent3_sentiment.prompts import (
    CLASSIFIER_SYSTEM_PROMPT,
    RESPONDER_SYSTEM_PROMPT,
)


def create_classifier_executor() -> AgentExecutor:
    """Create the sentiment classifier AgentExecutor."""
    settings = get_settings()
    client = AzureOpenAIChatClient(
        endpoint=settings.azure_openai_endpoint,
        ad_token_provider=get_azure_token_provider(),
        api_version=settings.azure_openai_api_version,
        deployment_name=settings.agent_model,
    )
    agent = ChatAgent(
        chat_client=client,
        instructions=CLASSIFIER_SYSTEM_PROMPT,
        name="Sentiment Classifier",
    )
    return AgentExecutor(agent, id="sentiment_classifier")


def create_responder_executor() -> AgentExecutor:
    """Create the response agent AgentExecutor."""
    settings = get_settings()
    client = AzureOpenAIChatClient(
        endpoint=settings.azure_openai_endpoint,
        ad_token_provider=get_azure_token_provider(),
        api_version=settings.azure_openai_api_version,
        deployment_name=settings.agent_model,
    )
    agent = ChatAgent(
        chat_client=client,
        instructions=RESPONDER_SYSTEM_PROMPT,
        name="Review Responder",
    )
    return AgentExecutor(agent, id="response_agent")
