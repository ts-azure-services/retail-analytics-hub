"""Pydantic settings for agent infrastructure."""

from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache
from typing import Callable

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from pydantic_settings import BaseSettings
from pydantic import Field

_REPO_ROOT = Path(__file__).resolve().parents[2]

# ── Azure AD token provider (cached at module level) ─────────────
_credential: DefaultAzureCredential | None = None
_token_provider: Callable[[], str] | None = None


def get_azure_token_provider() -> Callable[[], str]:
    """Return a cached callable that yields Azure AD bearer tokens
    scoped to Azure OpenAI (cognitiveservices)."""
    global _credential, _token_provider
    if _token_provider is None:
        _credential = DefaultAzureCredential()
        _token_provider = get_bearer_token_provider(
            _credential,
            "https://cognitiveservices.azure.com/.default",
        )
    return _token_provider


class Settings(BaseSettings):
    """Centralised configuration loaded from environment / local.env."""

    model_config = {
        "env_file": str(_REPO_ROOT / "local.env"),
        "extra": "ignore",
    }

    # ── Azure OpenAI ──────────────────────────────────────────────
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2024-12-01-preview"

    # ── Model defaults (overridden per-agent via env) ─────────────
    agent_model: str = "gpt-4o-mini"
    agent_temperature: float = 0.3

    # ── Deployment names (from Terraform / local.env) ─────────────
    gpt_4o_mini_deployment: str = "gpt-4o-mini"
    gpt_5_2_deployment: str = "gpt-5-2"

    # ── Fabric SQL endpoint (cloud — empty means local DuckDB) ───
    fabric_sql_endpoint: str = ""

    # ── Fabric KQL endpoint (cloud — empty means local DuckDB for reviews) ──
    fabric_kql_cluster_uri: str = ""
    fabric_kql_database: str = ""
    fabric_kql_table: str = ""

    # ── DuckDB paths ──────────────────────────────────────────────
    local_postgres_db: str = Field(
        default_factory=lambda: os.environ.get(
            "LOCAL_POSTGRES_DB", str(_REPO_ROOT / "local_postgres.duckdb")
        )
    )
    local_cosmos_db: str = Field(
        default_factory=lambda: os.environ.get(
            "LOCAL_COSMOS_DB", str(_REPO_ROOT / "local_cosmos.duckdb")
        )
    )

    # ── Event Hubs DB (customer reviews table) ─────────────────────
    customer_reviews_db: str = Field(
        default_factory=lambda: os.environ.get(
            "EVENT_HUBS_DB", str(_REPO_ROOT / "event_hubs.duckdb")
        )
    )

    # ── Safety limits ─────────────────────────────────────────────
    query_row_limit: int = 1000
    query_timeout_seconds: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
