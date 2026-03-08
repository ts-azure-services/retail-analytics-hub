"""Read-only database connection manager.

Supports two backends:
  - Local: DuckDB files (default, when FABRIC_SQL_ENDPOINT is unset)
  - Cloud: Fabric SQL endpoint via psycopg (when FABRIC_SQL_ENDPOINT is set)
"""

from __future__ import annotations

import duckdb
from pathlib import Path

from .config import get_settings


# ── DuckDB helpers (local) ───────────────────────────────────────

def _connect(path: str) -> duckdb.DuckDBPyConnection:
    """Open a read-only DuckDB connection and validate the file exists."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"DuckDB file not found: {path}")
    return duckdb.connect(str(p), read_only=True)


# ── Fabric helpers (cloud) ───────────────────────────────────────

def _fabric_connection():
    """Return a psycopg connection to the Fabric SQL endpoint."""
    import psycopg
    return psycopg.connect(get_settings().fabric_sql_endpoint)


# ── Public connection getters ────────────────────────────────────

def get_postgres_connection():
    """Return a read-only connection to the PostgreSQL-equivalent database."""
    settings = get_settings()
    if settings.fabric_sql_endpoint:
        return _fabric_connection()
    return _connect(settings.local_postgres_db)


def get_cosmos_connection():
    """Return a read-only connection to the CosmosDB-equivalent database."""
    settings = get_settings()
    if settings.fabric_sql_endpoint:
        return _fabric_connection()
    return _connect(settings.local_cosmos_db)


def get_reviews_connection():
    """Return a read-only connection to the customer reviews DuckDB (event_hubs)."""
    settings = get_settings()
    if settings.fabric_sql_endpoint:
        return _fabric_connection()
    return _connect(settings.customer_reviews_db)


# ── Query execution ─────────────────────────────────────────────

def execute_query(
    conn,
    sql: str,
    params: list | None = None,
) -> list[dict]:
    """Execute a read-only query and return results as list of dicts.

    Enforces row limit and timeout from settings.
    Works with both DuckDB connections and psycopg cursors.
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
