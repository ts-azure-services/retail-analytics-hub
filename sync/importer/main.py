"""
Container App Job entry point — imports staged data from Azure Blob Storage
into Azure Postgres, Cosmos DB, and Event Hub.

Triggered ad-hoc via `az containerapp job start`. Reads all blobs from the
staging storage account and routes them to the appropriate handler based on
the blob container prefix.

Environment variables (set by Terraform on the Container App Job):
  STORAGE_ACCOUNT_NAME  - staging blob storage account
  POSTGRES_FQDN         - Azure Postgres server FQDN
  POSTGRES_DB_NAME      - database name
  COSMOSDB_ENDPOINT     - Cosmos DB account endpoint
  COSMOSDB_DB_NAME      - Cosmos DB database name
  EVENTHUB_NAMESPACE    - Event Hub namespace FQDN
  EVENTHUB_NAME         - Event Hub name
"""

import os
import sys

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

import postgres_handler
import cosmos_handler
import eventhub_handler

STORAGE_ACCOUNT_NAME = os.environ.get("STORAGE_ACCOUNT_NAME", "")

# Container names in staging storage
CONTAINERS = {
    "postgres": postgres_handler.import_table,
    "cosmos": cosmos_handler.import_container,
    "eventhub": eventhub_handler.publish_events,
}


def main() -> None:
    if not STORAGE_ACCOUNT_NAME:
        print("ERROR: STORAGE_ACCOUNT_NAME not set")
        sys.exit(1)

    credential = DefaultAzureCredential()
    account_url = f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
    blob_service = BlobServiceClient(account_url=account_url, credential=credential)

    for container_name, handler_fn in CONTAINERS.items():
        print(f"\n--- Processing container: {container_name} ---")
        container_client = blob_service.get_container_client(container_name)

        try:
            blobs = list(container_client.list_blobs())
        except Exception as e:
            print(f"  Could not list blobs in '{container_name}': {e}")
            continue

        if not blobs:
            print(f"  No blobs found in '{container_name}'")
            continue

        for blob in blobs:
            print(f"  Processing: {blob.name}")
            blob_client = container_client.get_blob_client(blob.name)
            blob_data = blob_client.download_blob().readall()
            handler_fn(blob.name, blob_data, credential)

    print("\nImport complete.")


if __name__ == "__main__":
    main()
