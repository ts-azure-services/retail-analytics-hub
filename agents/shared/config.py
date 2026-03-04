"""Pydantic settings for agent infrastructure."""

from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings
from pydantic import Field

_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Centralised configuration loaded from environment / .env file."""

    model_config = {"env_file": str(_REPO_ROOT / "agents" / ".env"), "extra": "ignore"}

    # ── Azure OpenAI ──────────────────────────────────────────────
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_api_version: str = "2024-12-01-preview"

    # ── Model defaults (overridden per-agent via env) ─────────────
    agent_model: str = "gpt-4o-mini"
    agent_temperature: float = 0.3

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
