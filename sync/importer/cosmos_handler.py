"""
Import NDJSON files into Azure Cosmos DB.

Downloads NDJSON from blob, parses each line, and upserts into the
corresponding Cosmos DB container.
"""

import json
import os

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


def import_container(blob_name: str, blob_data: bytes, credential) -> None:
    """Import an NDJSON file into a Cosmos DB container."""
    # e.g. "Customers.ndjson" -> "Customers"
    container_name = blob_name.rsplit(".", 1)[0]

    client = CosmosClient(url=COSMOSDB_ENDPOINT, credential=credential)
    database = client.get_database_client(COSMOSDB_DB_NAME)

    pk_path = PARTITION_KEYS.get(container_name, DEFAULT_PARTITION_KEY)
    container = database.create_container_if_not_exists(
        id=container_name,
        partition_key=PartitionKey(path=pk_path),
    )

    lines = blob_data.decode("utf-8").strip().split("\n")
    success = 0
    errors = 0

    for line in lines:
        if not line.strip():
            continue
        doc = json.loads(line)
        try:
            container.upsert_item(doc)
            success += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"    {container_name}: upsert error - {e}")
            if errors == 6:
                print(f"    {container_name}: (suppressing further errors)")

    print(f"    {container_name}: {success:,} upserted, {errors} errors")
    if success == 0 and errors > 0:
        print(f"    {container_name}: WARNING - all upserts failed, check partition key and document structure")
