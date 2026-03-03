"""Planner sub-agent for Agent 1 — calls MCP tools and analyzes data."""

from __future__ import annotations

import os

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient
from autogen_ext.tools.mcp import StdioServerParams, mcp_server_tools

from agents.shared.config import get_settings
from ..prompts import PLANNER_SYSTEM_PROMPT


async def create_planner_agent() -> AssistantAgent:
    """Create the planner agent with MCP tools loaded."""
    settings = get_settings()

    model_client = AzureOpenAIChatCompletionClient(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
        model="gpt-4o-mini",
        temperature=0.3,
    )

    # Load MCP tools from the server subprocess
    # Explicitly pass environment so subprocess can find DuckDB files
    server_params = StdioServerParams(
        command="uv",
        args=["run", "python", "-m", "agents.mcp_server.server"],
        env={**os.environ},
    )
    tools = await mcp_server_tools(server_params)

    return AssistantAgent(
        name="data_planner",
        system_message=PLANNER_SYSTEM_PROMPT,
        model_client=model_client,
        tools=tools,
    )
