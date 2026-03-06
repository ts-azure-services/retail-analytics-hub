"""MCP tools for the Customer Reviews dashboard tab.

Metrics: avg sentiment score, sentiment distribution, review volume,
         processing status, response rate
Table: customer_reviews (in event_hubs.duckdb)
"""

from __future__ import annotations

from mcp.types import Tool

from agents.shared.db import get_reviews_connection, execute_query

_METRIC_SQL = {
    "cr-avg-sentiment": {
        "label": "Average Sentiment Score",
        "sql": "SELECT AVG(sentiment_score) AS value FROM customer_reviews WHERE sentiment_score IS NOT NULL",
        "format": "number",
    },
    "cr-review-volume": {
        "label": "Total Reviews",
        "sql": "SELECT COUNT(*) AS value FROM customer_reviews",
        "format": "number",
    },
    "cr-positive-rate": {
        "label": "Positive Review Rate",
        "sql": """SELECT COUNT(CASE WHEN sentiment_category IN ('positive', 'very_positive') THEN 1 END) * 100.0
                  / NULLIF(COUNT(*), 0) AS value FROM customer_reviews""",
        "format": "percentage",
    },
    "cr-negative-rate": {
        "label": "Negative Review Rate",
        "sql": """SELECT COUNT(CASE WHEN sentiment_category IN ('negative', 'very_negative') THEN 1 END) * 100.0
                  / NULLIF(COUNT(*), 0) AS value FROM customer_reviews""",
        "format": "percentage",
    },
    "cr-response-rate": {
        "label": "Chatbot Response Rate",
        "sql": """SELECT COUNT(CASE WHEN chatbot_statement IS NOT NULL THEN 1 END) * 100.0
                  / NULLIF(COUNT(*), 0) AS value FROM customer_reviews""",
        "format": "percentage",
    },
}

_DRIVER_SQL = {
    "cr-avg-sentiment": [
        ("Sentiment Distribution", "SELECT sentiment_category, COUNT(*) AS count, AVG(sentiment_score) AS avg_score FROM customer_reviews GROUP BY sentiment_category ORDER BY avg_score DESC"),
        ("Lowest Scored Reviews", "SELECT id, review_text, sentiment_score, sentiment_category FROM customer_reviews WHERE sentiment_score IS NOT NULL ORDER BY sentiment_score ASC LIMIT 5"),
    ],
    "cr-review-volume": [
        ("Reviews by Status", "SELECT status, COUNT(*) AS count FROM customer_reviews GROUP BY status ORDER BY count DESC"),
        ("Reviews by Sentiment", "SELECT sentiment_category, COUNT(*) AS count FROM customer_reviews GROUP BY sentiment_category ORDER BY count DESC"),
    ],
    "cr-positive-rate": [
        ("Positive Reviews Detail", "SELECT id, review_text, sentiment_score FROM customer_reviews WHERE sentiment_category IN ('positive', 'very_positive') ORDER BY sentiment_score DESC LIMIT 5"),
        ("Sentiment Distribution", "SELECT sentiment_category, COUNT(*) AS count FROM customer_reviews GROUP BY sentiment_category ORDER BY count DESC"),
    ],
    "cr-negative-rate": [
        ("Negative Reviews Detail", "SELECT id, review_text, sentiment_score FROM customer_reviews WHERE sentiment_category IN ('negative', 'very_negative') ORDER BY sentiment_score ASC LIMIT 5"),
        ("Unresolved Negative Reviews", "SELECT id, review_text, sentiment_score, status FROM customer_reviews WHERE sentiment_category IN ('negative', 'very_negative') AND chatbot_statement IS NULL ORDER BY sentiment_score ASC"),
    ],
    "cr-response-rate": [
        ("Pending Reviews", "SELECT id, review_text, status, error_message FROM customer_reviews WHERE chatbot_statement IS NULL ORDER BY created_at DESC"),
        ("Response Status Breakdown", "SELECT status, COUNT(*) AS count, COUNT(CASE WHEN chatbot_statement IS NOT NULL THEN 1 END) AS responded FROM customer_reviews GROUP BY status ORDER BY count DESC"),
    ],
}


def _get_metrics_summary() -> dict:
    conn = get_reviews_connection()
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
        return {"tab": "customer-reviews", "metrics": results}
    finally:
        conn.close()


def _get_metric_drivers(metric_id: str) -> dict:
    if metric_id not in _DRIVER_SQL:
        return {"error": f"Unknown metric_id: {metric_id}. Valid: {list(_DRIVER_SQL.keys())}"}

    conn = get_reviews_connection()
    try:
        drivers = []
        for label, sql in _DRIVER_SQL[metric_id]:
            rows = execute_query(conn, sql)
            drivers.append({"label": label, "data": rows})
        return {"metric_id": metric_id, "tab": "customer-reviews", "drivers": drivers}
    finally:
        conn.close()


def _get_review_analysis() -> dict:
    """Provide an overview of all reviews with sentiment and response status."""
    conn = get_reviews_connection()
    try:
        summary_sql = """
            SELECT
                sentiment_category,
                COUNT(*) AS review_count,
                AVG(sentiment_score) AS avg_score,
                COUNT(CASE WHEN chatbot_statement IS NOT NULL THEN 1 END) AS responded,
                COUNT(CASE WHEN chatbot_statement IS NULL THEN 1 END) AS pending_response
            FROM customer_reviews
            GROUP BY sentiment_category
            ORDER BY avg_score DESC
        """
        rows = execute_query(conn, summary_sql)
        return {"review_analysis": rows}
    finally:
        conn.close()


def get_tools():
    return [
        (
            Tool(
                name="get_reviews_metrics_summary",
                description="Get all Customer Reviews tab metrics: avg sentiment score, review volume, positive rate, negative rate, response rate.",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            _get_metrics_summary,
        ),
        (
            Tool(
                name="get_reviews_metric_drivers",
                description="Get driver analysis for a specific Customer Reviews metric.",
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
                name="get_review_analysis",
                description="Analyze customer reviews by sentiment category with response status breakdown.",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            _get_review_analysis,
        ),
    ]
