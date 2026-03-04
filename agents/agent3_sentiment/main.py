"""FastAPI backend for Agent 3 — Customer Sentiment Analysis (port 8003)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agents.shared.models import (
    HealthResponse,
    ReviewRequest,
    ReviewResponse,
    ReviewStatus,
)
from agents.agent3_sentiment import db
from agents.agent3_sentiment.workflow_manager import analyze_review

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

_retry_task: asyncio.Task | None = None


async def _background_retry_loop() -> None:
    """Periodically retry incomplete / unprocessed reviews (every 10 minutes)."""
    while True:
        await asyncio.sleep(600)  # 10 minutes
        try:
            rows = db.get_retryable_reviews(max_retries=3)
            if rows:
                logger.info("Background retry: %d review(s) to process", len(rows))
            for row in rows:
                try:
                    await analyze_review(row["id"], row["review_text"])
                except Exception as exc:
                    logger.warning("Retry failed for review %s: %s", row["id"], exc)
                    db.mark_error(row["id"], str(exc))
        except Exception as exc:
            logger.error("Background retry loop error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB schema and start background retry task."""
    db.init_schema()
    logger.info("DuckDB schema initialized")

    global _retry_task
    _retry_task = asyncio.create_task(_background_retry_loop())

    yield

    if _retry_task:
        _retry_task.cancel()
        try:
            await _retry_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Agent 3 — Customer Sentiment Analysis",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/analyze", response_model=ReviewResponse)
async def analyze(request: ReviewRequest) -> ReviewResponse:
    """Analyze a single review through the sentiment pipeline."""
    try:
        result = await analyze_review(request.review_id, request.review_text)
        return ReviewResponse(
            review_id=result.get("review_id", request.review_id),
            sentiment_category=result.get("sentiment_category", ""),
            sentiment_score=result.get("sentiment_score", 0.0),
            status=result.get("status", ReviewStatus.INCOMPLETE_PROCESSING.value),
            chatbot_statement=result.get("chatbot_statement"),
            needs_human_review=result.get("needs_human_review", False),
        )
    except Exception as exc:
        logger.error("Pipeline error for review %s: %s", request.review_id, exc)
        db.mark_error(request.review_id, str(exc))
        return ReviewResponse(
            review_id=request.review_id,
            sentiment_category="",
            sentiment_score=0.0,
            status=ReviewStatus.INCOMPLETE_PROCESSING.value,
            needs_human_review=False,
        )


@app.post("/retry")
async def retry() -> dict:
    """Re-process all retryable reviews (incomplete processing, retry_count < 3)."""
    rows = db.get_retryable_reviews(max_retries=3)
    results = {"total": len(rows), "succeeded": 0, "failed": 0}
    for row in rows:
        try:
            await analyze_review(row["id"], row["review_text"])
            results["succeeded"] += 1
        except Exception as exc:
            logger.warning("Retry failed for review %s: %s", row["id"], exc)
            db.mark_error(row["id"], str(exc))
            results["failed"] += 1
    return results


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="healthy", agent="agent3-sentiment")
