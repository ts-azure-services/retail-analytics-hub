"""MCP tools for the Customer Reviews dashboard tab.

Metrics: avg sentiment score, sentiment distribution, review volume,
         processing status, response rate
Table: customer_reviews (in event_hubs.duckdb locally, KQL in cloud)
"""

from __future__ import annotations

from mcp.types import Tool

from agents.shared.config import get_settings
from agents.shared.db import get_reviews_connection, execute_query, execute_kql_query

# ── SQL queries (Postgres/DuckDB — local) ─────────────────────────

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

# ── KQL queries (Fabric Real-Time Intelligence — cloud) ──────────


def _kql_table() -> str:
    return get_settings().fabric_kql_table or "CustomerReviews"


_METRIC_KQL = {
    "cr-avg-sentiment": {
        "label": "Average Sentiment Score",
        "kql": lambda t: f"{t} | where isnotnull(sentiment_score) | summarize value = avg(sentiment_score)",
        "format": "number",
    },
    "cr-review-volume": {
        "label": "Total Reviews",
        "kql": lambda t: f"{t} | count | project value = Count",
        "format": "number",
    },
    "cr-positive-rate": {
        "label": "Positive Review Rate",
        "kql": lambda t: f"{t} | summarize total = count(), pos = countif(sentiment_category in ('positive', 'very_positive')) | project value = pos * 100.0 / total",
        "format": "percentage",
    },
    "cr-negative-rate": {
        "label": "Negative Review Rate",
        "kql": lambda t: f"{t} | summarize total = count(), neg = countif(sentiment_category in ('negative', 'very_negative')) | project value = neg * 100.0 / total",
        "format": "percentage",
    },
    "cr-response-rate": {
        "label": "Chatbot Response Rate",
        "kql": lambda t: f"{t} | summarize total = count(), responded = countif(isnotnull(chatbot_statement)) | project value = responded * 100.0 / total",
        "format": "percentage",
    },
}

_DRIVER_KQL = {
    "cr-avg-sentiment": [
        ("Sentiment Distribution", lambda t: f"{t} | summarize count = count(), avg_score = avg(sentiment_score) by sentiment_category | order by avg_score desc"),
        ("Lowest Scored Reviews", lambda t: f"{t} | where isnotnull(sentiment_score) | top 5 by sentiment_score asc | project id, review_text, sentiment_score, sentiment_category"),
    ],
    "cr-review-volume": [
        ("Reviews by Status", lambda t: f"{t} | summarize count = count() by status | order by count desc"),
        ("Reviews by Sentiment", lambda t: f"{t} | summarize count = count() by sentiment_category | order by count desc"),
    ],
    "cr-positive-rate": [
        ("Positive Reviews Detail", lambda t: f"{t} | where sentiment_category in ('positive', 'very_positive') | top 5 by sentiment_score desc | project id, review_text, sentiment_score"),
        ("Sentiment Distribution", lambda t: f"{t} | summarize count = count() by sentiment_category | order by count desc"),
    ],
    "cr-negative-rate": [
        ("Negative Reviews Detail", lambda t: f"{t} | where sentiment_category in ('negative', 'very_negative') | top 5 by sentiment_score asc | project id, review_text, sentiment_score"),
        ("Unresolved Negative Reviews", lambda t: f"{t} | where sentiment_category in ('negative', 'very_negative') and isnull(chatbot_statement) | order by sentiment_score asc | project id, review_text, sentiment_score, status"),
    ],
    "cr-response-rate": [
        ("Pending Reviews", lambda t: f"{t} | where isnull(chatbot_statement) | order by created_at desc | project id, review_text, status, error_message"),
        ("Response Status Breakdown", lambda t: f"{t} | summarize count = count(), responded = countif(isnotnull(chatbot_statement)) by status | order by count desc"),
    ],
}


# ── Helpers ──────────────────────────────────────────────────────

def _use_kql() -> bool:
    """Return True if KQL should be used (cloud mode with RTI configured)."""
    return bool(get_settings().fabric_kql_cluster_uri)


# ── Tool implementations ─────────────────────────────────────────

def _get_metrics_summary() -> dict:
    if _use_kql():
        return _get_metrics_summary_kql()

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


def _get_metrics_summary_kql() -> dict:
    client = get_reviews_connection()
    table = _kql_table()
    try:
        results = {}
        for metric_id, meta in _METRIC_KQL.items():
            kql = meta["kql"](table)
            rows = execute_kql_query(client, kql)
            if rows and "error" in rows[0]:
                results[metric_id] = {
                    "label": meta["label"],
                    "value": None,
                    "format": meta["format"],
                    "error": rows[0]["error"],
                }
            else:
                value = rows[0].get("value") if rows and "value" in rows[0] else None
                results[metric_id] = {
                    "label": meta["label"],
                    "value": value,
                    "format": meta["format"],
                }
        return {"tab": "customer-reviews", "metrics": results}
    finally:
        client.close()


def _get_metric_drivers(metric_id: str) -> dict:
    if _use_kql():
        return _get_metric_drivers_kql(metric_id)

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


def _get_metric_drivers_kql(metric_id: str) -> dict:
    if metric_id not in _DRIVER_KQL:
        return {"error": f"Unknown metric_id: {metric_id}. Valid: {list(_DRIVER_KQL.keys())}"}

    client = get_reviews_connection()
    table = _kql_table()
    try:
        drivers = []
        for label, kql_fn in _DRIVER_KQL[metric_id]:
            rows = execute_kql_query(client, kql_fn(table))
            drivers.append({"label": label, "data": rows})
        return {"metric_id": metric_id, "tab": "customer-reviews", "drivers": drivers}
    finally:
        client.close()


def _get_review_analysis() -> dict:
    """Provide an overview of all reviews with sentiment and response status."""
    if _use_kql():
        return _get_review_analysis_kql()

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


def _get_review_analysis_kql() -> dict:
    client = get_reviews_connection()
    table = _kql_table()
    try:
        kql = (
            f"{table}"
            " | summarize review_count = count(),"
            " avg_score = avg(sentiment_score),"
            " responded = countif(isnotnull(chatbot_statement)),"
            " pending_response = countif(isnull(chatbot_statement))"
            " by sentiment_category"
            " | order by avg_score desc"
        )
        rows = execute_kql_query(client, kql)
        return {"review_analysis": rows}
    finally:
        client.close()


# ── Tool registration ─────────────────────────────────────────────

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
