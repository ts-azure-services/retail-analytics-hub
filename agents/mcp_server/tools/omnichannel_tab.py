"""MCP tools for the Omnichannel dashboard tab (8 metrics).

Metrics: arrival-rate, conversion, cart-abandon, avg-journey, total-orders,
         ontime, fulfillment-dur, payment-success
Tables: customer_journeys, order_metrics, hourly_demand, payments
"""

from __future__ import annotations

from mcp.types import Tool

from agents.shared.db import get_postgres_connection, execute_query

_METRIC_SQL = {
    "omni-arrival-rate": {
        "label": "Arrival Rate",
        "sql": """SELECT COUNT(*) * 1.0 /
                  NULLIF((SELECT MAX(hour_of_simulation) FROM hourly_demand), 0) AS value
                  FROM customer_journeys""",
        "format": "number",
    },
    "omni-conversion": {
        "label": "Conversion Rate",
        "sql": "SELECT COUNT(CASE WHEN completed THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_journeys",
        "format": "percentage",
    },
    "omni-cart-abandon": {
        "label": "Cart Abandonment Rate",
        "sql": "SELECT COUNT(CASE WHEN abandoned THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_journeys",
        "format": "percentage",
    },
    "omni-avg-journey": {
        "label": "Avg Journey Time",
        "sql": "SELECT AVG(total_journey_time) AS value FROM customer_journeys",
        "format": "number",
    },
    "omni-total-orders": {
        "label": "Total Orders",
        "sql": "SELECT COUNT(*) AS value FROM order_metrics",
        "format": "number",
    },
    "omni-ontime": {
        "label": "On-Time Delivery %",
        "sql": "SELECT COUNT(CASE WHEN on_time THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM order_metrics",
        "format": "percentage",
    },
    "omni-fulfillment-dur": {
        "label": "Avg Fulfillment Duration",
        "sql": "SELECT AVG(fulfillment_duration) AS value FROM order_metrics",
        "format": "number",
    },
    "omni-payment-success": {
        "label": "Payment Success Rate",
        "sql": "SELECT COUNT(CASE WHEN status = 'authorized' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM payments",
        "format": "percentage",
    },
}

_DRIVER_SQL = {
    "omni-arrival-rate": [
        ("Hourly Arrival Count", "SELECT hour_of_simulation, AVG(arrival_count) AS avg_arrivals FROM hourly_demand GROUP BY hour_of_simulation ORDER BY hour_of_simulation"),
        ("Hourly Revenue", "SELECT hour_of_simulation, AVG(revenue) AS avg_revenue FROM hourly_demand GROUP BY hour_of_simulation ORDER BY hour_of_simulation"),
        ("Hourly Order Count", "SELECT hour_of_simulation, AVG(order_count) AS avg_orders FROM hourly_demand GROUP BY hour_of_simulation ORDER BY hour_of_simulation"),
        ("Hourly Abandonment", "SELECT hour_of_simulation, AVG(abandonment_count) AS avg_abandons FROM hourly_demand GROUP BY hour_of_simulation ORDER BY hour_of_simulation"),
    ],
    "omni-conversion": [
        ("Conversion by Channel", "SELECT channel, COUNT(CASE WHEN completed THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS conversion_rate, COUNT(*) AS total FROM customer_journeys GROUP BY channel ORDER BY conversion_rate DESC"),
        ("Payment Failure Rate", "SELECT COUNT(CASE WHEN payment_failed THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_journeys"),
        ("Queue Balk Rate", "SELECT COUNT(CASE WHEN abandonment_reason = 'queue_too_long' THEN 1 END) * 100.0 / NULLIF(COUNT(CASE WHEN channel = 'in_store' THEN 1 END), 0) AS value FROM customer_journeys"),
    ],
    "omni-cart-abandon": [
        ("Price Sensitivity", "SELECT COUNT(*) AS value FROM customer_journeys WHERE abandonment_reason = 'price'"),
        ("Queue Too Long", "SELECT COUNT(*) AS value FROM customer_journeys WHERE abandonment_reason = 'queue_too_long'"),
        ("Browsing Fatigue", "SELECT COUNT(*) AS value FROM customer_journeys WHERE abandonment_reason = 'browsing_fatigue'"),
    ],
    "omni-avg-journey": [
        ("Avg Browsing Duration", "SELECT AVG(browsing_duration) AS value FROM customer_journeys"),
        ("Avg Queue Wait Time", "SELECT AVG(queue_wait_time) AS value FROM customer_journeys"),
        ("Avg Checkout Time", "SELECT AVG(checkout_time) AS value FROM customer_journeys"),
    ],
    "omni-total-orders": [
        ("Orders by Channel", "SELECT channel, COUNT(*) AS orders FROM order_metrics GROUP BY channel ORDER BY orders DESC"),
        ("Avg Basket Size", "SELECT AVG(basket_size) AS value FROM customer_journeys WHERE completed = TRUE"),
        ("Payment Method Distribution", "SELECT payment_method, COUNT(*) AS count FROM payments GROUP BY payment_method ORDER BY count DESC"),
    ],
    "omni-ontime": [
        ("Late Orders", "SELECT COUNT(*) AS value FROM order_metrics WHERE on_time = FALSE"),
        ("Fulfillment by Channel", "SELECT channel, AVG(fulfillment_duration) AS avg_duration FROM order_metrics GROUP BY channel ORDER BY avg_duration DESC"),
        ("Return Rate", "SELECT COUNT(CASE WHEN returned THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM order_metrics"),
    ],
    "omni-fulfillment-dur": [
        ("Duration by Channel", "SELECT channel, AVG(fulfillment_duration) AS avg_duration FROM order_metrics GROUP BY channel ORDER BY avg_duration DESC"),
        ("On-Time Delivery %", "SELECT COUNT(CASE WHEN on_time THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM order_metrics"),
        ("Late Orders", "SELECT COUNT(*) AS value FROM order_metrics WHERE on_time = FALSE"),
    ],
    "omni-payment-success": [
        ("By Payment Method", "SELECT payment_method, COUNT(CASE WHEN status = 'authorized' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS success_rate FROM payments GROUP BY payment_method ORDER BY success_rate DESC"),
        ("Gateway Reliability", "SELECT COUNT(CASE WHEN status != 'authorized' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS failure_rate FROM payments"),
        ("Conversion Impact", "SELECT COUNT(CASE WHEN payment_failed THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_journeys"),
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
        return {"tab": "omnichannel", "metrics": results}
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
        return {"metric_id": metric_id, "tab": "omnichannel", "drivers": drivers}
    finally:
        conn.close()


def _get_channel_comparison() -> dict:
    """Compare key metrics across channels."""
    conn = get_postgres_connection()
    try:
        sql = """
            SELECT
                channel,
                COUNT(*) AS total_journeys,
                COUNT(CASE WHEN completed THEN 1 END) AS completed_orders,
                COUNT(CASE WHEN completed THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS conversion_rate,
                AVG(CASE WHEN completed THEN total_amount END) AS avg_order_value,
                AVG(total_journey_time) AS avg_journey_time,
                COUNT(CASE WHEN abandoned THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS abandonment_rate
            FROM customer_journeys
            GROUP BY channel
            ORDER BY completed_orders DESC
        """
        rows = execute_query(conn, sql)
        return {"comparison": rows}
    finally:
        conn.close()


def get_tools():
    return [
        (
            Tool(
                name="get_omnichannel_metrics_summary",
                description="Get all 8 Omnichannel tab metrics: arrival rate, conversion, cart abandonment, avg journey time, total orders, on-time delivery, fulfillment duration, payment success rate.",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            _get_metrics_summary,
        ),
        (
            Tool(
                name="get_omnichannel_metric_drivers",
                description="Get driver analysis for a specific Omnichannel tab metric.",
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
                name="get_channel_comparison",
                description="Compare conversion rate, AOV, journey time, and abandonment across channels (online, in_store, BOPIS).",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            _get_channel_comparison,
        ),
    ]
