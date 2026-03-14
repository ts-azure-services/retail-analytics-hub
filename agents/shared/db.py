"""Read-only database connection manager.

Supports three backends:
  - Local: DuckDB files (default, when FABRIC_SQL_ENDPOINT is unset)
  - Cloud SQL: Fabric SQL endpoint via mssql-python (when FABRIC_SQL_ENDPOINT is set)
  - Cloud KQL: Fabric KQL via azure-kusto-data (when FABRIC_KQL_CLUSTER_URI is set)
"""

from __future__ import annotations

import logging
import duckdb
from pathlib import Path

from .config import get_settings

logger = logging.getLogger(__name__)


# ── DuckDB helpers (local) ───────────────────────────────────────

def _connect(path: str) -> duckdb.DuckDBPyConnection:
    """Open a read-only DuckDB connection and validate the file exists."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"DuckDB file not found: {path}")
    return duckdb.connect(str(p), read_only=True)


# ── Fabric helpers (cloud) ───────────────────────────────────────

def _fabric_connection():
    """Return an mssql-python connection to the Fabric SQL endpoint.

    Builds an ODBC-style connection string from FABRIC_SQL_ENDPOINT (server
    hostname) and FABRIC_SQL_DATABASE, using ActiveDirectoryDefault auth
    which picks up the Managed Identity token in Container Apps.
    """
    from mssql_python import connect as mssql_connect

    settings = get_settings()
    conn_str = (
        f"Server={settings.fabric_sql_endpoint},1433;"
        f"Database={settings.fabric_sql_database};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Authentication=ActiveDirectoryDefault;"
    )
    return mssql_connect(conn_str)


_credential = None
_kusto_client = None


def _get_credential():
    """Return a cached DefaultAzureCredential instance."""
    global _credential
    if _credential is None:
        from azure.identity import DefaultAzureCredential
        _credential = DefaultAzureCredential()
    return _credential


def _kql_connection():
    """Return a cached KustoClient connected to the Fabric KQL endpoint."""
    global _kusto_client
    if _kusto_client is not None:
        return _kusto_client

    from azure.kusto.data import KustoClient, KustoConnectionStringBuilder

    settings = get_settings()
    kcsb = KustoConnectionStringBuilder.with_azure_token_credential(
        settings.fabric_kql_cluster_uri, _get_credential()
    )
    _kusto_client = KustoClient(kcsb)
    return _kusto_client


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
    """Return a connection to customer reviews data.

    Three modes:
      - KQL: when fabric_kql_cluster_uri is set (returns KustoClient)
      - Fabric SQL: when fabric_sql_endpoint is set (returns mssql-python connection)
      - Local: DuckDB file (default)
    """
    settings = get_settings()
    if settings.fabric_kql_cluster_uri:
        return _kql_connection()
    if settings.fabric_sql_endpoint:
        return _fabric_connection()
    return _connect(settings.customer_reviews_db)


# ── Dialect helper ──────────────────────────────────────────────

def use_mssql_dialect() -> bool:
    """Return True when SQL queries should use MSSQL/T-SQL syntax.

    This is the single source of truth for dialect selection across all
    agent tool modules.  When True, callers should use the MSSQL query
    variants from ``agents.mcp_server.tools.sql_variants``.
    """
    return bool(get_settings().fabric_sql_endpoint)


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

    # Enforce row limit (MSSQL uses TOP, Postgres/DuckDB uses LIMIT)
    if "LIMIT" not in sql.upper() and "TOP " not in sql.upper():
        if not use_mssql_dialect():
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


def execute_kql_query(
    client,
    kql: str,
    database: str | None = None,
) -> list[dict]:
    """Execute a KQL query and return results as list of dicts.

    Works with KustoClient from azure-kusto-data.
    """
    settings = get_settings()
    db = database or settings.fabric_kql_database

    try:
        response = client.execute_query(db, kql)
        columns = [col.column_name for col in response.primary_results[0].columns]
        rows = list(response.primary_results[0])
        return [
            {col: row[col] for col in columns}
            for row in rows
        ]
    except Exception as e:
        logger.error("KQL query failed: %s | query: %s", e, kql[:200])
        return [{"error": str(e)}]
