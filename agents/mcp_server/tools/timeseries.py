"""MCP tools for hourly demand time-series queries.

Table: hourly_demand
"""

from __future__ import annotations

from mcp.types import Tool

from agents.shared.db import get_postgres_connection, execute_query, use_mssql_dialect


def _get_hourly_demand_trend(hours: int = 24, channel: str | None = None) -> dict:
    """Get hourly demand trend for the last N hours."""
    conn = get_postgres_connection()
    try:
        if use_mssql_dialect():
            from agents.mcp_server.tools.sql_variants import get_mssql_hourly_demand_sql
            sql = get_mssql_hourly_demand_sql(hours, channel)
        else:
            where_clause = ""
            if channel:
                where_clause = f"WHERE channel = '{channel}'"
            sql = f"""
                SELECT
                    hour_of_simulation,
                    hour_of_day,
                    day_of_week,
                    channel,
                    arrival_count,
                    order_count,
                    abandonment_count,
                    revenue,
                    avg_basket_size
                FROM hourly_demand
                {where_clause}
                ORDER BY hour_of_simulation DESC
                LIMIT {min(hours, 1000)}
            """
        rows = execute_query(conn, sql)
        return {"trend": rows, "hours_requested": hours, "channel_filter": channel}
    finally:
        conn.close()


def _get_demand_by_hour_of_day() -> dict:
    """Get demand patterns aggregated by hour of day (0-23)."""
    conn = get_postgres_connection()
    try:
        if use_mssql_dialect():
            from agents.mcp_server.tools.sql_variants import get_mssql_demand_by_hour_sql
            sql = get_mssql_demand_by_hour_sql()
        else:
            sql = """
                SELECT
                    hour_of_day,
                    AVG(arrival_count) AS avg_arrivals,
                    AVG(order_count) AS avg_orders,
                    AVG(abandonment_count) AS avg_abandonments,
                    AVG(revenue) AS avg_revenue,
                    COUNT(*) AS data_points
                FROM hourly_demand
                GROUP BY hour_of_day
                ORDER BY hour_of_day
            """
        rows = execute_query(conn, sql)
        return {"hourly_pattern": rows}
    finally:
        conn.close()


def get_tools():
    return [
        (
            Tool(
                name="get_hourly_demand_trend",
                description="Get hourly demand trend data including arrivals, orders, abandonments, and revenue. Optionally filter by channel.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "hours": {
                            "type": "integer",
                            "description": "Number of recent hours to retrieve (default 24, max 1000)",
                            "default": 24,
                        },
                        "channel": {
                            "type": "string",
                            "description": "Optional channel filter (online, in_store, bopis)",
                            "enum": ["online", "in_store", "bopis"],
                        },
                    },
                    "required": [],
                },
            ),
            _get_hourly_demand_trend,
        ),
        (
            Tool(
                name="get_demand_by_hour_of_day",
                description="Get demand patterns aggregated by hour of day (0-23). Shows average arrivals, orders, abandonments, and revenue per hour across all simulation days.",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            _get_demand_by_hour_of_day,
        ),
    ]
