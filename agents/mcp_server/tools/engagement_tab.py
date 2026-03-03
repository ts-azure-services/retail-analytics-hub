"""MCP tools for the Customer Engagement dashboard tab (8 metrics).

Metrics: active-rate, churn-rate, open-rate, campaign-ctr, enrollment-rate,
         redemption-rate, resolution-rate, satisfaction
Tables: customer_snapshots, campaign_interactions, loyalty_account,
        points_transactions, support_tickets
"""

from __future__ import annotations

from mcp.types import Tool

from agents.shared.db import get_postgres_connection, execute_query

_METRIC_SQL = {
    "ce-active-rate": {
        "label": "Active Customer Rate",
        "sql": "SELECT COUNT(CASE WHEN activity_state = 'active' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_snapshots",
        "format": "percentage",
    },
    "ce-churn-rate": {
        "label": "Churn Rate",
        "sql": "SELECT COUNT(CASE WHEN churned = TRUE THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_snapshots",
        "format": "percentage",
    },
    "ce-open-rate": {
        "label": "Campaign Open Rate",
        "sql": "SELECT COUNT(CASE WHEN opened THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM campaign_interactions",
        "format": "percentage",
    },
    "ce-campaign-ctr": {
        "label": "Campaign CTR",
        "sql": "SELECT COUNT(CASE WHEN clicked THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM campaign_interactions",
        "format": "percentage",
    },
    "ce-enrollment-rate": {
        "label": "Loyalty Enrollment Rate",
        "sql": """SELECT COUNT(DISTINCT la.customer_id) * 100.0 /
                  NULLIF((SELECT COUNT(DISTINCT customer_id) FROM customer_snapshots), 0) AS value
                  FROM loyalty_account la""",
        "format": "percentage",
    },
    "ce-redemption-rate": {
        "label": "Points Redemption Rate",
        "sql": """SELECT
                    SUM(CASE WHEN points_change < 0 THEN ABS(points_change) ELSE 0 END) * 100.0 /
                    NULLIF(SUM(CASE WHEN points_change > 0 THEN points_change ELSE 0 END), 0) AS value
                  FROM points_transactions""",
        "format": "percentage",
    },
    "ce-resolution-rate": {
        "label": "Ticket Resolution Rate",
        "sql": "SELECT COUNT(CASE WHEN status = 'resolved' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM support_tickets",
        "format": "percentage",
    },
    "ce-satisfaction": {
        "label": "Avg Satisfaction Rating",
        "sql": "SELECT AVG(satisfaction_rating) AS value FROM support_tickets",
        "format": "number",
    },
}

_DRIVER_SQL = {
    "ce-active-rate": [
        ("Lapsed Customer Rate", "SELECT COUNT(CASE WHEN activity_state = 'lapsed' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_snapshots"),
        ("Retention Rate", "SELECT (1 - COUNT(CASE WHEN churned THEN 1 END) * 1.0 / NULLIF(COUNT(*), 0)) * 100 AS value FROM customer_snapshots"),
        ("Lifecycle State Distribution", "SELECT activity_state, COUNT(*) AS count FROM customer_snapshots GROUP BY activity_state ORDER BY count DESC"),
    ],
    "ce-churn-rate": [
        ("Days Since Last Purchase", "SELECT AVG(days_since_last_purchase) AS value FROM customer_snapshots"),
        ("Unresponsive Count", "SELECT AVG(unresponsive_count) AS value FROM customer_snapshots"),
        ("Churn by Value Tier", "SELECT value_tier, COUNT(CASE WHEN churned THEN 1 END) AS churned, COUNT(*) AS total FROM customer_snapshots GROUP BY value_tier ORDER BY churned DESC"),
    ],
    "ce-open-rate": [
        ("Response by Campaign Type", "SELECT campaign_type, COUNT(CASE WHEN opened THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS open_rate, COUNT(*) AS total FROM campaign_interactions GROUP BY campaign_type ORDER BY open_rate DESC"),
        ("Campaign Fatigue", "SELECT AVG(unresponsive_count) AS avg_unresponsive FROM customer_snapshots"),
    ],
    "ce-campaign-ctr": [
        ("Click-to-Open Rate", "SELECT COUNT(CASE WHEN clicked THEN 1 END) * 100.0 / NULLIF(COUNT(CASE WHEN opened THEN 1 END), 0) AS value FROM campaign_interactions"),
        ("Campaign Conversion Rate", "SELECT COUNT(CASE WHEN converted THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM campaign_interactions"),
        ("CTR by Campaign Type", "SELECT campaign_type, COUNT(CASE WHEN clicked THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS ctr FROM campaign_interactions GROUP BY campaign_type ORDER BY ctr DESC"),
    ],
    "ce-enrollment-rate": [
        ("Avg Points Balance", "SELECT AVG(current_points) AS value FROM loyalty_account"),
        ("Tier Distribution", "SELECT tier, COUNT(*) AS count FROM loyalty_account GROUP BY tier ORDER BY count DESC"),
        ("Lifetime Points Earned", "SELECT SUM(lifetime_points) AS value FROM loyalty_account"),
    ],
    "ce-redemption-rate": [
        ("Points Issued", "SELECT SUM(points_change) AS value FROM points_transactions WHERE points_change > 0"),
        ("Points Redeemed", "SELECT SUM(ABS(points_change)) AS value FROM points_transactions WHERE points_change < 0"),
        ("Transaction Reasons", "SELECT reason, COUNT(*) AS count FROM points_transactions GROUP BY reason ORDER BY count DESC"),
    ],
    "ce-resolution-rate": [
        ("Open Tickets", "SELECT COUNT(*) AS value FROM support_tickets WHERE status = 'open'"),
        ("Tickets by Issue Type", "SELECT issue_type, COUNT(*) AS count FROM support_tickets GROUP BY issue_type ORDER BY count DESC"),
    ],
    "ce-satisfaction": [
        ("Satisfaction by Issue Type", "SELECT issue_type, AVG(satisfaction_rating) AS avg_rating, COUNT(*) AS count FROM support_tickets GROUP BY issue_type ORDER BY avg_rating DESC"),
        ("Total Tickets", "SELECT COUNT(*) AS value FROM support_tickets"),
    ],
}


def _get_metrics_summary() -> dict:
    conn = get_postgres_connection()
    try:
        results = {}
        for metric_id, meta in _METRIC_SQL.items():
            rows = execute_query(conn, meta["sql"])
            value = rows[0]["value"] if rows and "value" in rows[0] else None
            results[metric_id] = {
                "label": meta["label"],
                "value": value,
                "format": meta["format"],
            }
        return {"tab": "customer-engagement", "metrics": results}
    finally:
        conn.close()


def _get_metric_drivers(metric_id: str) -> dict:
    if metric_id not in _DRIVER_SQL:
        return {"error": f"Unknown metric_id: {metric_id}. Valid: {list(_DRIVER_SQL.keys())}"}

    conn = get_postgres_connection()
    try:
        drivers = []
        for label, sql in _DRIVER_SQL[metric_id]:
            rows = execute_query(conn, sql)
            drivers.append({"label": label, "data": rows})
        return {"metric_id": metric_id, "tab": "customer-engagement", "drivers": drivers}
    finally:
        conn.close()


def _get_segment_analysis() -> dict:
    """Analyze customer segments by value tier and activity state."""
    conn = get_postgres_connection()
    try:
        sql = """
            SELECT
                value_tier,
                activity_state,
                COUNT(*) AS customers,
                AVG(total_spend) AS avg_spend,
                AVG(purchase_count) AS avg_purchases,
                AVG(churn_risk_score) AS avg_churn_risk,
                AVG(loyalty_points) AS avg_loyalty_points
            FROM customer_snapshots
            GROUP BY value_tier, activity_state
            ORDER BY value_tier, activity_state
        """
        rows = execute_query(conn, sql)
        return {"segment_analysis": rows}
    finally:
        conn.close()


def get_tools():
    return [
        (
            Tool(
                name="get_engagement_metrics_summary",
                description="Get all 8 Customer Engagement tab metrics: active rate, churn rate, open rate, CTR, enrollment rate, redemption rate, resolution rate, satisfaction.",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            _get_metrics_summary,
        ),
        (
            Tool(
                name="get_engagement_metric_drivers",
                description="Get driver analysis for a specific Customer Engagement metric.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "metric_id": {
                            "type": "string",
                            "enum": list(_METRIC_SQL.keys()),
                        }
                    },
                    "required": ["metric_id"],
                },
            ),
            _get_metric_drivers,
        ),
        (
            Tool(
                name="get_segment_analysis",
                description="Analyze customer segments by value tier and activity state. Returns avg spend, purchases, churn risk, and loyalty points per segment.",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            _get_segment_analysis,
        ),
    ]
