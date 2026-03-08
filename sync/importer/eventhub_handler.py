"""
Publish NDJSON events to Azure Event Hub.

Downloads NDJSON from blob, parses each line, and batch-publishes
via the EventHubProducerClient.
"""

import json
import os

from azure.eventhub import EventHubProducerClient, EventData

EVENTHUB_NAMESPACE = os.environ.get("EVENTHUB_NAMESPACE", "")
EVENTHUB_NAME = os.environ.get("EVENTHUB_NAME", "")


def publish_events(blob_name: str, blob_data: bytes, credential) -> None:
    """Publish NDJSON lines as events to Azure Event Hub."""
    producer = EventHubProducerClient(
        fully_qualified_namespace=EVENTHUB_NAMESPACE,
        eventhub_name=EVENTHUB_NAME,
        credential=credential,
    )

    lines = blob_data.decode("utf-8").strip().split("\n")
    sent = 0

    try:
        batch = producer.create_batch()
        for line in lines:
            if not line.strip():
                continue
            event = EventData(line)
            try:
                batch.add(event)
            except ValueError:
                # Batch is full, send it and start a new one
                producer.send_batch(batch)
                sent += batch.size_in_bytes
                batch = producer.create_batch()
                batch.add(event)

        # Send remaining events
        if batch:
            producer.send_batch(batch)

        print(f"    {blob_name}: {len(lines):,} events published")
    except Exception as e:
        print(f"    {blob_name}: ERROR - {e}")
    finally:
        producer.close()
