"""
Export all tables from local_cosmos.duckdb to NDJSON files.

Each Cosmos table has columns (id, partition_key, data). The NDJSON line is
the parsed `data` field with `id` and `partition_key` preserved at the top level.
"""

import json
import os
import duckdb
from sync.config import LOCAL_COSMOS_DB, STAGING_DIR

OUTDIR = STAGING_DIR / "cosmos"

# Expected Cosmos containers (tables) — export all that exist
EXPECTED_TABLES = [
    "Customers", "Carts", "WorkflowEvents",
    "FulfillmentState", "InventoryEvents", "EngagementEvents",
]


def export_cosmos() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(LOCAL_COSMOS_DB, read_only=True)

    all_tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    tables = [t for t in EXPECTED_TABLES if t in all_tables]
    # Also export any extra tables not in the expected list
    extras = sorted(all_tables - set(EXPECTED_TABLES))
    tables.extend(extras)

    if not tables:
        print("No tables found in local_cosmos.duckdb")
        conn.close()
        return

    print(f"Exporting {len(tables)} containers from local_cosmos.duckdb")
    for table in tables:
        dest = OUTDIR / f"{table}.ndjson"
        rows = conn.execute(
            f'SELECT id, partition_key, data FROM "{table}"'
        ).fetchall()

        with open(dest, "w") as f:
            for row_id, partition_key, data_json in rows:
                doc = json.loads(data_json) if isinstance(data_json, str) else data_json
                doc["id"] = row_id
                f.write(json.dumps(doc, default=str) + "\n")

        file_size = os.path.getsize(dest)
        print(f"  {table:40s}  {len(rows):>8,} docs  {file_size:>10,} bytes")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    export_cosmos()
