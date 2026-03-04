"""FastAPI app for Agent 1 — Dashboard Explainer.

Runs on port 8001. Provides /chat and /health endpoints.
"""

from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agents.shared.models import ChatRequest, ChatResponse, HealthResponse
from .workflow_manager import run_explainer_pipeline

app = FastAPI(
    title="Agent 1 — Dashboard Explainer",
    description="Answers tab-level questions about retail metrics using multi-agent pipeline",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Handle a chat message from the dashboard."""
    response_text = await run_explainer_pipeline(request)
    return ChatResponse(
        response=response_text,
        agent="explainer",
        metadata={
            "active_tab": request.active_tab,
            "current_view": request.current_view,
            "selected_metric_id": request.selected_metric_id,
        },
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="healthy", agent="explainer", version="0.1.0")
