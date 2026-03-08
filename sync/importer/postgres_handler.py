"""
Import Parquet files into Azure PostgreSQL.

Downloads Parquet from blob, reads with pyarrow, and bulk-inserts into
the target table via psycopg2 COPY FROM. Creates tables from Parquet
schema if they don't exist. No pandas dependency.
"""

import csv
import io
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import psycopg2

POSTGRES_FQDN = os.environ.get("POSTGRES_FQDN", "")
POSTGRES_DB_NAME = os.environ.get("POSTGRES_DB_NAME", "")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "psqladmin")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")

# Arrow type → Postgres type mapping
_TYPE_MAP = {
    pa.int8(): "SMALLINT",
    pa.int16(): "SMALLINT",
    pa.int32(): "INTEGER",
    pa.int64(): "BIGINT",
    pa.uint8(): "SMALLINT",
    pa.uint16(): "INTEGER",
    pa.uint32(): "BIGINT",
    pa.uint64(): "BIGINT",
    pa.float16(): "REAL",
    pa.float32(): "REAL",
    pa.float64(): "DOUBLE PRECISION",
    pa.bool_(): "BOOLEAN",
    pa.date32(): "DATE",
    pa.date64(): "DATE",
}


def _pg_type(arrow_type) -> str:
    """Map an Arrow type to a Postgres column type."""
    if arrow_type in _TYPE_MAP:
        return _TYPE_MAP[arrow_type]
    if pa.types.is_timestamp(arrow_type):
        return "TIMESTAMP"
    if pa.types.is_decimal(arrow_type):
        return f"NUMERIC({arrow_type.precision},{arrow_type.scale})"
    if pa.types.is_large_string(arrow_type) or pa.types.is_string(arrow_type):
        return "TEXT"
    if pa.types.is_binary(arrow_type) or pa.types.is_large_binary(arrow_type):
        return "BYTEA"
    # Fallback
    return "TEXT"


def _get_connection():
    """Connect to Azure Postgres."""
    conn_str = (
        f"host={POSTGRES_FQDN} dbname={POSTGRES_DB_NAME} "
        f"user={POSTGRES_USER} password={POSTGRES_PASSWORD} sslmode=require"
    )
    return psycopg2.connect(conn_str)


def _ensure_table(cur, table_name: str, schema: pa.Schema) -> None:
    """CREATE TABLE IF NOT EXISTS from the Parquet arrow schema."""
    col_defs = []
    for field in schema:
        col_defs.append(f'"{field.name}" {_pg_type(field.type)}')
    ddl = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(col_defs)})'
    cur.execute(ddl)


def import_table(blob_name: str, blob_data: bytes, credential) -> None:
    """Import a single Parquet file into the corresponding Postgres table."""
    table_name = Path(blob_name).stem  # e.g. "customers.parquet" -> "customers"

    # Read Parquet from bytes
    parquet_buf = io.BytesIO(blob_data)
    arrow_table = pq.read_table(parquet_buf)

    if arrow_table.num_rows == 0:
        print(f"    {table_name}: empty, skipping")
        return

    # Convert to CSV via pyarrow (no pandas needed)
    columns = arrow_table.column_names
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    for batch in arrow_table.to_batches():
        col_data = [batch.column(i).to_pylist() for i in range(batch.num_columns)]
        for row_idx in range(batch.num_rows):
            writer.writerow(
                "\\N" if col_data[col_idx][row_idx] is None else col_data[col_idx][row_idx]
                for col_idx in range(len(col_data))
            )
    csv_buf.seek(0)

    conn = _get_connection()
    cur = conn.cursor()

    try:
        # Create table from Parquet schema if it doesn't exist
        _ensure_table(cur, table_name, arrow_table.schema)

        # Truncate and re-insert (idempotent)
        cur.execute(f'TRUNCATE "{table_name}" CASCADE')

        col_list = ", ".join(f'"{c}"' for c in columns)
        cur.copy_expert(
            f"COPY \"{table_name}\" ({col_list}) FROM STDIN WITH CSV NULL '\\N'",
            csv_buf,
        )

        conn.commit()
        print(f"    {table_name}: {arrow_table.num_rows:,} rows imported")
    except Exception as e:
        conn.rollback()
        print(f"    {table_name}: ERROR - {e}")
    finally:
        cur.close()
        conn.close()
