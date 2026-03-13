"""MCP tools for the Main dashboard tab (6 metrics).

Metrics: revenue, customers, conversion, aov, clv, return-rate
Tables: customer_journeys, customer_snapshots, order_metrics, order_items
"""

from __future__ import annotations

import json
from mcp.types import Tool

from agents.shared.db import get_postgres_connection, execute_query, use_mssql_dialect

# ── Metric SQL definitions (from metric-registry.ts) ─────────────

_METRIC_SQL = {
    "revenue": {
        "label": "Total Revenue",
        "sql": "SELECT SUM(total_amount) AS value FROM customer_journeys WHERE completed = TRUE",
        "previous_sql": "SELECT SUM(total_amount) AS value FROM customer_journeys WHERE completed = TRUE",
        "format": "currency",
    },
    "customers": {
        "label": "Total Customers",
        "sql": "SELECT COUNT(DISTINCT customer_id) AS value FROM customer_snapshots",
        "previous_sql": "SELECT COUNT(DISTINCT customer_id) AS value FROM customer_snapshots",
        "format": "number",
    },
    "conversion": {
        "label": "Conversion Rate",
        "sql": "SELECT COUNT(CASE WHEN completed THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_journeys",
        "previous_sql": "SELECT COUNT(CASE WHEN completed THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_journeys",
        "format": "percentage",
    },
    "aov": {
        "label": "Average Order Value",
        "sql": "SELECT AVG(total_amount) AS value FROM customer_journeys WHERE completed = TRUE",
        "previous_sql": "SELECT AVG(total_amount) AS value FROM customer_journeys WHERE completed = TRUE",
        "format": "currency",
    },
    "clv": {
        "label": "Customer Lifetime Value",
        "sql": "SELECT AVG(total_spend) AS value FROM customer_snapshots WHERE total_spend > 0",
        "previous_sql": "SELECT AVG(total_spend) AS value FROM customer_snapshots WHERE total_spend > 0",
        "format": "currency",
    },
    "return-rate": {
        "label": "Return Rate",
        "sql": "SELECT COUNT(CASE WHEN returned THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM order_metrics",
        "previous_sql": "SELECT COUNT(CASE WHEN returned THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM order_metrics",
        "format": "percentage",
    },
}

# ── Driver SQL queries ────────────────────────────────────────────

_DRIVER_SQL = {
    "revenue": [
        ("Order Volume", "SELECT COUNT(*) AS value FROM customer_journeys WHERE completed = TRUE"),
        ("Average Order Value", "SELECT AVG(total_amount) AS value FROM customer_journeys WHERE completed = TRUE"),
        ("Basket Size", "SELECT AVG(basket_size) AS value FROM customer_journeys WHERE completed = TRUE"),
        ("Average Unit Price", "SELECT SUM(total_amount) / NULLIF(SUM(basket_size), 0) AS value FROM customer_journeys WHERE completed = TRUE"),
        ("Channel Mix", "SELECT channel, SUM(total_amount) AS revenue, COUNT(*) AS orders FROM customer_journeys WHERE completed = TRUE GROUP BY channel ORDER BY revenue DESC"),
    ],
    "customers": [
        ("Active Customers", "SELECT COUNT(*) AS value FROM customer_snapshots WHERE activity_state = 'active'"),
        ("Lapsed Customers", "SELECT COUNT(*) AS value FROM customer_snapshots WHERE activity_state = 'lapsed'"),
        ("Churned Customers", "SELECT COUNT(*) AS value FROM customer_snapshots WHERE churned = TRUE"),
        ("By Value Tier", "SELECT value_tier, COUNT(*) AS count FROM customer_snapshots GROUP BY value_tier ORDER BY count DESC"),
    ],
    "conversion": [
        ("Cart Abandonment Rate", "SELECT COUNT(CASE WHEN abandoned THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_journeys"),
        ("Abandonment by Reason", "SELECT abandonment_reason, COUNT(*) AS count FROM customer_journeys WHERE abandoned = TRUE GROUP BY abandonment_reason ORDER BY count DESC"),
        ("Payment Failure Rate", "SELECT COUNT(CASE WHEN payment_failed THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_journeys"),
        ("Queue Balk Rate", "SELECT COUNT(CASE WHEN abandonment_reason = 'queue_too_long' THEN 1 END) * 100.0 / NULLIF(COUNT(CASE WHEN channel = 'in_store' THEN 1 END), 0) AS value FROM customer_journeys"),
        ("Browsing Duration", "SELECT AVG(browsing_duration) AS value FROM customer_journeys"),
    ],
    "aov": [
        ("Basket Size", "SELECT AVG(basket_size) AS value FROM customer_journeys WHERE completed = TRUE"),
        ("Unit Price Distribution", "SELECT AVG(unit_price) AS value FROM order_items"),
        ("Product Mix", "SELECT product_id, SUM(subtotal) AS revenue, SUM(quantity) AS units FROM order_items GROUP BY product_id ORDER BY revenue DESC"),
        ("Channel Effect", "SELECT channel, AVG(total_amount) AS avg_aov FROM customer_journeys WHERE completed = TRUE GROUP BY channel ORDER BY avg_aov DESC"),
    ],
    "clv": [
        ("Purchase Frequency", "SELECT AVG(purchase_count) AS value FROM customer_snapshots"),
        ("Average Order Value", "SELECT AVG(avg_order_value) AS value FROM customer_snapshots"),
        ("Customer Tenure", "SELECT AVG(days_since_join) AS value FROM customer_snapshots"),
        ("Loyalty Points Balance", "SELECT AVG(loyalty_points) AS value FROM customer_snapshots"),
        ("Churn Risk Score", "SELECT AVG(churn_risk_score) AS value FROM customer_snapshots"),
    ],
    "return-rate": [
        ("Returns by Channel", "SELECT channel, COUNT(CASE WHEN returned THEN 1 END) AS returns, COUNT(*) AS total, COUNT(CASE WHEN returned THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS return_rate FROM order_metrics GROUP BY channel ORDER BY return_rate DESC"),
        ("Late Delivery Effect", "SELECT on_time, COUNT(CASE WHEN returned THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS return_rate FROM order_metrics GROUP BY on_time"),
        ("Fulfillment Duration Effect", "SELECT returned, AVG(fulfillment_duration) AS avg_fulfillment FROM order_metrics GROUP BY returned"),
    ],
}


def _get_metrics_summary() -> dict:
    """Fetch all 6 Main tab metrics."""
    conn = get_postgres_connection()
    try:
        if use_mssql_dialect():
            from agents.mcp_server.tools.sql_variants import get_mssql_metric_sql
            metric_sql = get_mssql_metric_sql("main")
        else:
            metric_sql = _METRIC_SQL
        results = {}
        for metric_id, meta in metric_sql.items():
            rows = execute_query(conn, meta["sql"])
            value = rows[0]["value"] if rows and "value" in rows[0] else None
            results[metric_id] = {
                "label": meta["label"],
                "value": value,
                "format": meta["format"],
            }
        return {"tab": "main", "metrics": results}
    finally:
        conn.close()


def _get_metric_drivers(metric_id: str) -> dict:
    """Fetch driver data for a specific Main tab metric."""
    if use_mssql_dialect():
        from agents.mcp_server.tools.sql_variants import get_mssql_driver_sql
        driver_sql = get_mssql_driver_sql("main")
    else:
        driver_sql = _DRIVER_SQL

    if metric_id not in driver_sql:
        return {"error": f"Unknown metric_id: {metric_id}. Valid: {list(driver_sql.keys())}"}

    conn = get_postgres_connection()
    try:
        drivers = []
        for label, sql in driver_sql[metric_id]:
            rows = execute_query(conn, sql)
            drivers.append({"label": label, "data": rows})
        return {"metric_id": metric_id, "tab": "main", "drivers": drivers}
    finally:
        conn.close()


# ── Tool registration ─────────────────────────────────────────────

def get_tools():
    return [
        (
            Tool(
                name="get_main_metrics_summary",
                description="Get all 6 Main tab metrics: revenue, customers, conversion rate, AOV, CLV, return rate. Returns current values from the simulation database.",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            _get_metrics_summary,
        ),
        (
            Tool(
                name="get_main_metric_drivers",
                description="Get driver analysis for a specific Main tab metric. Returns detailed breakdown data for the metric's key drivers.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "metric_id": {
                            "type": "string",
                            "description": "The metric to analyze",
                            "enum": list(_METRIC_SQL.keys()),
                        }
                    },
                    "required": ["metric_id"],
                },
            ),
            _get_metric_drivers,
        ),
    ]
