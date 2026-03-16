"""EventHub consumer and producer helpers for Agent 3 cloud mode.

In cloud mode Agent 3 consumes raw review events from the ``raw-reviews``
EventHub, processes them through the sentiment pipeline, and publishes the
processed result to the ``processed-reviews`` EventHub.  The processed
event matches the ``customer_reviews`` table schema so that Fabric
Eventstream can land the data directly into the KQL table.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from azure.eventhub import EventHubConsumerClient, EventHubProducerClient, EventData
from azure.identity import DefaultAzureCredential

from agents.shared.config import get_settings

logger = logging.getLogger(__name__)


def _fqns(namespace: str) -> str:
    """Ensure fully-qualified namespace string."""
    if ".servicebus.windows.net" in namespace:
        return namespace
    return f"{namespace}.servicebus.windows.net"


# ---------------------------------------------------------------------------
# Producer — publish processed results to the processed-reviews hub
# ---------------------------------------------------------------------------

_producer: EventHubProducerClient | None = None


def get_producer() -> EventHubProducerClient:
    """Lazily create and cache an EventHub producer for the processed-reviews hub."""
    global _producer
    if _producer is not None:
        return _producer

    settings = get_settings()
    _producer = EventHubProducerClient(
        fully_qualified_namespace=_fqns(settings.eventhub_namespace),
        eventhub_name=settings.eventhub_processed_name,
        credential=DefaultAzureCredential(),
    )
    return _producer


def publish_processed_event(result: dict) -> None:
    """Publish a single processed review event to the processed-reviews hub.

    The event payload matches the ``customer_reviews`` table schema:
        id, review_text, sentiment_category, sentiment_score, status,
        chatbot_statement, created_at, processed_at, error_message,
        retry_count, last_retry_at
    """
    producer = get_producer()

    event_body = {
        "id": result.get("review_id"),
        "review_text": result.get("review_text", ""),
        "sentiment_category": result.get("sentiment_category", ""),
        "sentiment_score": result.get("sentiment_score", 0.0),
        "status": result.get("status", "processed for response"),
        "chatbot_statement": result.get("chatbot_statement"),
        "created_at": result.get("created_at", datetime.now(timezone.utc).isoformat()),
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "error_message": result.get("error_message"),
        "retry_count": result.get("retry_count", 0),
        "last_retry_at": result.get("last_retry_at"),
    }

    batch = producer.create_batch()
    batch.add(EventData(json.dumps(event_body)))
    producer.send_batch(batch)
    logger.info(
        "Published processed event for review %s → %s",
        event_body["id"],
        event_body["status"],
    )


# ---------------------------------------------------------------------------
# Consumer — receive raw review events from the raw-reviews hub
# ---------------------------------------------------------------------------


def create_consumer() -> EventHubConsumerClient:
    """Create an EventHub consumer for the raw-reviews hub."""
    settings = get_settings()
    return EventHubConsumerClient(
        fully_qualified_namespace=_fqns(settings.eventhub_namespace),
        eventhub_name=settings.eventhub_raw_name,
        consumer_group=settings.eventhub_consumer_group,
        credential=DefaultAzureCredential(),
    )


def close_producer() -> None:
    """Gracefully close the cached producer (call on shutdown)."""
    global _producer
    if _producer is not None:
        _producer.close()
        _producer = None
