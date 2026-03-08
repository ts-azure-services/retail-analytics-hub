"""
Upload sync/staging/ files to Azure Blob Storage.

Uses the azure-storage-blob SDK with a connection string from sync/config.py.
Overwrites existing blobs (idempotent).
"""

import os
import sys
from pathlib import Path

from azure.storage.blob import BlobServiceClient

from sync.config import (
    STAGING_DIR,
    STAGING_STORAGE_CONN_STRING,
    STAGING_CONTAINER_POSTGRES,
    STAGING_CONTAINER_COSMOS,
    STAGING_CONTAINER_EVENTHUB,
)

# Map local staging subdirectory to blob container name
_MAPPING = {
    "postgres": STAGING_CONTAINER_POSTGRES,
    "cosmos": STAGING_CONTAINER_COSMOS,
    "eventhub": STAGING_CONTAINER_EVENTHUB,
}


def upload() -> None:
    if not STAGING_STORAGE_CONN_STRING:
        print(
            "ERROR: STAGING_STORAGE_CONN_STRING is not set.\n"
            "Run 'make tf' to provision cloud infrastructure and generate infra/.env"
        )
        sys.exit(1)

    client = BlobServiceClient.from_connection_string(STAGING_STORAGE_CONN_STRING)

    total = 0
    for subdir, container_name in _MAPPING.items():
        local_dir = STAGING_DIR / subdir
        if not local_dir.exists():
            print(f"  Skipping {subdir}/ (not found)")
            continue

        container_client = client.get_container_client(container_name)
        files = sorted(local_dir.iterdir())
        if not files:
            print(f"  Skipping {subdir}/ (empty)")
            continue

        print(f"Uploading {len(files)} file(s) to container '{container_name}'")
        for fp in files:
            if not fp.is_file():
                continue
            blob_name = fp.name
            file_size = os.path.getsize(fp)
            with open(fp, "rb") as data:
                container_client.upload_blob(
                    name=blob_name, data=data, overwrite=True
                )
            print(f"  {blob_name:40s}  {file_size:>10,} bytes")
            total += 1

    print(f"\nUploaded {total} file(s) total.")


if __name__ == "__main__":
    upload()
