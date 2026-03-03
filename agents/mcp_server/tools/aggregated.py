"""MCP tools for cross-tab health checks and correlation analysis.

Used primarily by Agent 2 (Business Narrative) for comprehensive analysis.
"""

from __future__ import annotations

from mcp.types import Tool

from agents.shared.db import get_postgres_connection, execute_query


def _get_cross_tab_health_check() -> dict:
    """Run a health check across all tabs, returning key metrics from each."""
    conn = get_postgres_connection()
    try:
        checks = {}

        # Main tab
        checks["revenue"] = execute_query(conn, "SELECT SUM(total_amount) AS value FROM customer_journeys WHERE completed = TRUE")
        checks["total_customers"] = execute_query(conn, "SELECT COUNT(DISTINCT customer_id) AS value FROM customer_snapshots")
        checks["conversion_rate"] = execute_query(conn, "SELECT COUNT(CASE WHEN completed THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_journeys")

        # Omnichannel
        checks["total_orders"] = execute_query(conn, "SELECT COUNT(*) AS value FROM order_metrics")
        checks["ontime_delivery"] = execute_query(conn, "SELECT COUNT(CASE WHEN on_time THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM order_metrics")
        checks["avg_fulfillment"] = execute_query(conn, "SELECT AVG(fulfillment_duration) AS value FROM order_metrics")

        # Customer engagement
        checks["active_rate"] = execute_query(conn, "SELECT COUNT(CASE WHEN activity_state = 'active' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_snapshots")
        checks["churn_rate"] = execute_query(conn, "SELECT COUNT(CASE WHEN churned THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_snapshots")

        # Inventory
        checks["fill_rate"] = execute_query(conn, """
            SELECT (1.0 - COUNT(CASE WHEN stockout_occurred THEN 1 END) * 1.0 /
                   NULLIF(COUNT(CASE WHEN event_type = 'SALE' THEN 1 END), 0)) * 100 AS value
            FROM inventory_events
        """)
        checks["stockout_count"] = execute_query(conn, "SELECT COUNT(*) AS value FROM inventory_events WHERE stockout_occurred = TRUE")
        checks["supplier_ontime"] = execute_query(conn, "SELECT COUNT(CASE WHEN on_time THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM supplier_deliveries")

        # Flatten results
        summary = {}
        for key, rows in checks.items():
            if rows and "value" in rows[0]:
                summary[key] = rows[0]["value"]
            else:
                summary[key] = None

        return {"health_check": summary}
    finally:
        conn.close()


def _get_correlation_analysis(metric_a: str, metric_b: str) -> dict:
    """Analyze relationship between two cross-tab metrics using channel-level data."""
    conn = get_postgres_connection()
    try:
        # Channel-level breakdown that allows cross-metric comparison
        sql = """
            SELECT
                cj.channel,
                COUNT(CASE WHEN cj.completed THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS conversion_rate,
                AVG(CASE WHEN cj.completed THEN cj.total_amount END) AS avg_order_value,
                COUNT(*) AS total_journeys,
                COUNT(CASE WHEN cj.completed THEN 1 END) AS completed_orders,
                AVG(cj.total_journey_time) AS avg_journey_time,
                COUNT(CASE WHEN cj.abandoned THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS abandonment_rate,
                SUM(CASE WHEN cj.completed THEN cj.total_amount ELSE 0 END) AS total_revenue
            FROM customer_journeys cj
            GROUP BY cj.channel
        """
        channel_data = execute_query(conn, sql)

        # Order-level cross-metrics
        order_sql = """
            SELECT
                channel,
                AVG(fulfillment_duration) AS avg_fulfillment,
                COUNT(CASE WHEN on_time THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS ontime_rate,
                COUNT(CASE WHEN returned THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS return_rate
            FROM order_metrics
            GROUP BY channel
        """
        order_data = execute_query(conn, order_sql)

        # Customer-level cross-metrics
        customer_sql = """
            SELECT
                activity_state,
                COUNT(*) AS customers,
                AVG(total_spend) AS avg_spend,
                AVG(churn_risk_score) AS avg_churn_risk,
                AVG(purchase_count) AS avg_purchases
            FROM customer_snapshots
            GROUP BY activity_state
        """
        customer_data = execute_query(conn, customer_sql)

        return {
            "metric_a": metric_a,
            "metric_b": metric_b,
            "channel_breakdown": channel_data,
            "order_metrics_by_channel": order_data,
            "customer_metrics_by_state": customer_data,
        }
    finally:
        conn.close()


def get_tools():
    return [
        (
            Tool(
                name="get_cross_tab_health_check",
                description="Get a health check across all 4 dashboard tabs. Returns key metrics: revenue, customers, conversion, orders, on-time delivery, fulfillment, active rate, churn rate, fill rate, stockouts, supplier on-time.",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            _get_cross_tab_health_check,
        ),
        (
            Tool(
                name="get_correlation_analysis",
                description="Analyze cross-tab relationships between metrics. Returns channel-level, order-level, and customer-level breakdowns to identify correlations.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "metric_a": {
                            "type": "string",
                            "description": "First metric to correlate (e.g. 'conversion', 'fulfillment', 'churn')",
                        },
                        "metric_b": {
                            "type": "string",
                            "description": "Second metric to correlate (e.g. 'revenue', 'satisfaction', 'stockouts')",
                        },
                    },
                    "required": ["metric_a", "metric_b"],
                },
            ),
            _get_correlation_analysis,
        ),
    ]
