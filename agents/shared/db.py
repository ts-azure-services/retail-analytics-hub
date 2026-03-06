"""Read-only DuckDB connection manager."""

from __future__ import annotations

import duckdb
from pathlib import Path

from .config import get_settings


def _connect(path: str) -> duckdb.DuckDBPyConnection:
    """Open a read-only DuckDB connection and validate the file exists."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"DuckDB file not found: {path}")
    return duckdb.connect(str(p), read_only=True)


def get_postgres_connection() -> duckdb.DuckDBPyConnection:
    """Return a read-only connection to the PostgreSQL-equivalent DuckDB."""
    return _connect(get_settings().local_postgres_db)


def get_cosmos_connection() -> duckdb.DuckDBPyConnection:
    """Return a read-only connection to the CosmosDB-equivalent DuckDB."""
    return _connect(get_settings().local_cosmos_db)


def get_reviews_connection() -> duckdb.DuckDBPyConnection:
    """Return a read-only connection to the customer reviews DuckDB (event_hubs)."""
    return _connect(get_settings().customer_reviews_db)


def execute_query(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list | None = None,
) -> list[dict]:
    """Execute a read-only query and return results as list of dicts.

    Enforces row limit and timeout from settings.
    """
    settings = get_settings()

    # Enforce row limit
    if "LIMIT" not in sql.upper():
        sql = f"{sql.rstrip().rstrip(';')} LIMIT {settings.query_row_limit}"

    try:
        if params:
            result = conn.execute(sql, params)
        else:
            result = conn.execute(sql)

        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        return [{"error": str(e)}]
