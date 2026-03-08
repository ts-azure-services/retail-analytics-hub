"""
Import NDJSON files into Azure Cosmos DB using concurrent upserts.

Downloads NDJSON from blob, parses all lines, and upserts into the
corresponding Cosmos DB container using a thread pool for throughput.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from azure.cosmos import CosmosClient, PartitionKey

COSMOSDB_ENDPOINT = os.environ.get("COSMOSDB_ENDPOINT", "")
COSMOSDB_DB_NAME = os.environ.get("COSMOSDB_DB_NAME", "")

# Default partition key paths per container
PARTITION_KEYS = {
    "Customers": "/customerId",
    "Carts": "/cartId",
    "WorkflowEvents": "/orderId",
    "FulfillmentState": "/orderId",
    "InventoryEvents": "/sku",
    "EngagementEvents": "/customerId",
}
DEFAULT_PARTITION_KEY = "/id"

# Concurrent upsert threads
MAX_WORKERS = 20


def import_container(blob_name: str, blob_data: bytes, credential) -> None:
    """Import an NDJSON file into a Cosmos DB container."""
    container_name = blob_name.rsplit(".", 1)[0]

    client = CosmosClient(url=COSMOSDB_ENDPOINT, credential=credential)
    database = client.get_database_client(COSMOSDB_DB_NAME)

    pk_path = PARTITION_KEYS.get(container_name, DEFAULT_PARTITION_KEY)
    container = database.create_container_if_not_exists(
        id=container_name,
        partition_key=PartitionKey(path=pk_path),
    )

    lines = blob_data.decode("utf-8").strip().split("\n")
    docs = [json.loads(line) for line in lines if line.strip()]
    total = len(docs)

    if total == 0:
        print(f"    {container_name}: empty, skipping")
        return

    print(f"    {container_name}: {total:,} docs to upsert ({MAX_WORKERS} threads)")

    success = 0
    errors = 0
    error_samples = []

    def _upsert(doc):
        container.upsert_item(doc)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_upsert, doc): doc for doc in docs}
        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            try:
                future.result()
                success += 1
            except Exception as e:
                errors += 1
                if len(error_samples) < 3:
                    error_samples.append(str(e)[:200])

            if done_count % 10000 == 0:
                print(f"    {container_name}: {done_count:,}/{total:,} processed")

    print(f"    {container_name}: {success:,} upserted, {errors} errors")
    for sample in error_samples:
        print(f"      error: {sample}")
