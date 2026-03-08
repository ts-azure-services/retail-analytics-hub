"""
Export all tables from local_postgres.duckdb to Parquet files.

Uses DuckDB's native COPY ... TO ... (FORMAT PARQUET) — no pandas needed.
"""

import os
import duckdb
from sync.config import LOCAL_POSTGRES_DB, STAGING_DIR

OUTDIR = STAGING_DIR / "postgres"


def export_postgres() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(LOCAL_POSTGRES_DB, read_only=True)

    tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    if not tables:
        print("No tables found in local_postgres.duckdb")
        conn.close()
        return

    print(f"Exporting {len(tables)} tables from local_postgres.duckdb")
    for table in tables:
        dest = OUTDIR / f"{table}.parquet"
        row_count = conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        conn.execute(
            f"COPY \"{table}\" TO '{dest}' (FORMAT PARQUET)"
        )
        file_size = os.path.getsize(dest)
        print(f"  {table:40s}  {row_count:>8,} rows  {file_size:>10,} bytes")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    export_postgres()
