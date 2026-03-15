"""FastAPI app for Agent 2 — Business Narrative.

Runs on port 8002. Provides /narrative, /chat, and /health endpoints.
"""

from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from agents.shared.models import (
    ChatRequest, ChatResponse,
    NarrativeRequest, NarrativeResponse,
    HealthResponse,
)
from .workflow_manager import run_narrative_pipeline, run_chat_pipeline, stream_chat_pipeline

app = FastAPI(
    title="Agent 2 — Business Narrative",
    description="Deep business analysis and executive narratives using multi-agent pipeline",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/narrative", response_model=NarrativeResponse)
async def narrative(request: NarrativeRequest) -> NarrativeResponse:
    """Generate a comprehensive business narrative."""
    response_text = await run_narrative_pipeline(request)

    # Parse structured sections from the narrative text
    key_findings = []
    recommendations = []
    risk_flags = []
    summary = response_text

    lines = response_text.split("\n")
    current_section = "summary"
    summary_lines = []

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()

        if "key findings" in lower or "key insight" in lower:
            current_section = "findings"
            continue
        elif "recommendation" in lower:
            current_section = "recommendations"
            continue
        elif "risk" in lower and ("flag" in lower or "alert" in lower):
            current_section = "risks"
            continue
        elif "executive summary" in lower or "summary" in lower and stripped.startswith("#"):
            current_section = "summary"
            continue

        if stripped.startswith(("- ", "* ", "1.", "2.", "3.", "4.", "5.")):
            clean = stripped.lstrip("-*0123456789. ")
            if current_section == "findings":
                key_findings.append(clean)
            elif current_section == "recommendations":
                recommendations.append(clean)
            elif current_section == "risks":
                risk_flags.append(clean)
            elif current_section == "summary":
                summary_lines.append(stripped)
        elif current_section == "summary" and stripped:
            summary_lines.append(stripped)

    if summary_lines:
        summary = " ".join(summary_lines[:3])

    return NarrativeResponse(
        summary=summary,
        key_findings=key_findings,
        recommendations=recommendations,
        risk_flags=risk_flags,
        narrative=response_text,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Handle interactive follow-up questions with narrative depth."""
    response_text = await run_chat_pipeline(request)
    return ChatResponse(
        response=response_text,
        agent="narrative",
        metadata={
            "active_tab": request.active_tab,
            "current_view": request.current_view,
        },
    )


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """Stream a chat response via Server-Sent Events."""
    return EventSourceResponse(stream_chat_pipeline(request))


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="healthy", agent="narrative", version="0.1.0")
