"""
Export customer_reviews from event_hubs.duckdb to NDJSON.
"""

import json
import os
import duckdb
from sync.config import EVENT_HUBS_DB, STAGING_DIR

OUTDIR = STAGING_DIR / "eventhub"


def export_eventhub() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(EVENT_HUBS_DB, read_only=True)

    # Check table exists
    tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    if "customer_reviews" not in tables:
        print("No customer_reviews table found in event_hubs.duckdb")
        conn.close()
        return

    dest = OUTDIR / "reviews.ndjson"
    columns = [
        col[0]
        for col in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'customer_reviews' ORDER BY ordinal_position"
        ).fetchall()
    ]

    rows = conn.execute("SELECT * FROM customer_reviews").fetchall()
    with open(dest, "w") as f:
        for row in rows:
            doc = dict(zip(columns, row))
            f.write(json.dumps(doc, default=str) + "\n")

    file_size = os.path.getsize(dest)
    print(f"Exported customer_reviews: {len(rows):,} rows  {file_size:,} bytes")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    export_eventhub()
