"""FastAPI backend for Agent 3 — Customer Sentiment Analysis (port 8003).

In **local mode** the agent reads from / writes to DuckDB and exposes the
``/analyze`` endpoint for on-demand processing.

In **cloud mode** (when ``EVENTHUB_RAW_NAME`` is set) the agent also spins
up a background consumer that listens on the ``raw-reviews`` EventHub,
processes each event through the sentiment pipeline, and publishes the
result to the ``processed-reviews`` EventHub.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agents.shared.config import get_settings
from agents.shared.models import (
    HealthResponse,
    ReviewRequest,
    ReviewResponse,
    ReviewStatus,
)
from agents.agent3_sentiment import db
from agents.agent3_sentiment.workflow_manager import analyze_review
from agents.shared.telemetry import configure_telemetry

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

_retry_task: asyncio.Task | None = None
_consumer_task: asyncio.Task | None = None


def _is_cloud_consumer_enabled() -> bool:
    """Return True when EventHub consumer env vars are configured."""
    settings = get_settings()
    return bool(settings.eventhub_namespace and settings.eventhub_raw_name and settings.eventhub_processed_name)


# ---------------------------------------------------------------------------
# Background: local processing loop (DuckDB — polls raw_reviews table)
# ---------------------------------------------------------------------------

async def _background_local_loop() -> None:
    """Poll raw_reviews for new entries, process them, then retry failures.

    Cycle:
      1. Fetch unconsumed rows from raw_reviews.
      2. For each: run the sentiment pipeline → writes to customer_reviews.
      3. Mark the raw_review row as consumed.
      4. Retry any failed customer_reviews (incomplete processing).
    Runs every 10 seconds.
    """
    while True:
        await asyncio.sleep(10)
        try:
            # Phase 1 — process new raw reviews
            pending = db.get_pending_raw_reviews(limit=20)
            if pending:
                logger.info("Local poller: %d raw review(s) to process", len(pending))
            for row in pending:
                try:
                    db.insert_review(row["id"], row["review_text"])
                    await analyze_review(row["id"], row["review_text"])
                    db.mark_raw_review_consumed(row["id"])
                except Exception as exc:
                    logger.warning("Processing failed for raw review %s: %s", row["id"], exc)
                    db.mark_error(row["id"], str(exc))
                    db.mark_raw_review_consumed(row["id"])

            # Phase 2 — retry previously failed customer_reviews
            retryable = db.get_retryable_reviews(max_retries=3)
            for row in retryable:
                try:
                    await analyze_review(row["id"], row["review_text"])
                except Exception as exc:
                    logger.warning("Retry failed for review %s: %s", row["id"], exc)
                    db.mark_error(row["id"], str(exc))
        except Exception as exc:
            logger.error("Local processing loop error: %s", exc)


# ---------------------------------------------------------------------------
# Background: cloud EventHub consumer loop
# ---------------------------------------------------------------------------

async def _eventhub_consumer_loop() -> None:
    """Consume raw review events from EventHub, process, and publish results."""
    from agents.agent3_sentiment.eventhub import (
        create_consumer,
        publish_processed_event,
        close_producer,
    )
    from datetime import datetime, timezone

    loop = asyncio.get_running_loop()
    # The workflow is a singleton that rejects concurrent runs,
    # so serialise calls to analyze_review across partition threads.
    process_lock = asyncio.Lock()

    def on_event(partition_context, event):
        """Callback invoked per event by the EventHub SDK (runs in a thread)."""
        if event is None:
            return
        try:
            body = event.body_as_str()
            payload = json.loads(body)
            review_id = payload.get("id")
            review_text = payload.get("review_text", "")

            if not review_text:
                logger.warning("Skipping event with empty review_text: %s", body[:200])
                partition_context.update_checkpoint(event)
                return

            logger.info("Received raw review %s from partition %s", review_id, partition_context.partition_id)

            async def _process():
                async with process_lock:
                    return await analyze_review(review_id, review_text)

            # Run the async pipeline from this sync callback
            result = asyncio.run_coroutine_threadsafe(
                _process(), loop
            ).result(timeout=120)

            # Enrich result with original event data
            result["review_text"] = review_text
            result["created_at"] = payload.get("created_at", datetime.now(timezone.utc).isoformat())

            publish_processed_event(result)
            partition_context.update_checkpoint(event)

        except Exception as exc:
            logger.error("Error processing EventHub event: %s", exc, exc_info=True)
            # Publish a failure event so the dashboard shows the error
            try:
                publish_processed_event({
                    "review_id": payload.get("id") if "payload" in dir() else None,
                    "review_text": payload.get("review_text", "") if "payload" in dir() else "",
                    "status": "incomplete processing",
                    "error_message": str(exc),
                    "retry_count": 0,
                })
            except Exception:
                logger.error("Failed to publish error event", exc_info=True)

    def on_error(partition_context, error):
        logger.error(
            "EventHub consumer error on partition %s: %s",
            partition_context.partition_id if partition_context else "N/A",
            error,
        )

    logger.info("Starting EventHub consumer for raw-reviews…")
    # Discover partitions, then create one consumer per partition so that
    # each receive() call owns its own client (the SDK only supports one
    # active receive() per EventHubConsumerClient).
    probe = create_consumer()
    partition_ids = probe.get_eventhub_properties()["partition_ids"]
    probe.close()
    logger.info("EventHub partitions: %s", partition_ids)

    consumers = [create_consumer() for _ in partition_ids]
    try:
        futures = []
        for consumer, pid in zip(consumers, partition_ids):
            fut = loop.run_in_executor(
                None,
                lambda c=consumer, p=pid: c.receive(
                    on_event=on_event,
                    on_error=on_error,
                    starting_position="-1",
                    partition_id=p,
                    max_wait_time=60,
                ),
            )
            futures.append(fut)

        await asyncio.gather(*futures)
    except asyncio.CancelledError:
        logger.info("EventHub consumer loop cancelled, closing…")
    finally:
        for c in consumers:
            c.close()
        close_producer()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB schema and start background tasks."""
    cloud_mode = _is_cloud_consumer_enabled()

    if not cloud_mode:
        db.init_schema()
        logger.info("DuckDB schema initialized (local mode)")

    global _retry_task, _consumer_task

    if cloud_mode:
        logger.info("Cloud mode detected — starting EventHub consumer")
        _consumer_task = asyncio.create_task(_eventhub_consumer_loop())
    else:
        logger.info("Local mode — starting raw_reviews poller")
        _retry_task = asyncio.create_task(_background_local_loop())

    yield

    for task in (_retry_task, _consumer_task):
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="Agent 3 — Customer Sentiment Analysis",
    version="0.1.0",
    lifespan=lifespan,
)

configure_telemetry(app, service_name="agent3-sentiment")
logging.getLogger().setLevel(logging.INFO)  # OTEL LoggingInstrumentor resets root to WARNING

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
