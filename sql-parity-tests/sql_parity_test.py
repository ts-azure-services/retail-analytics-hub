"""SQL Parity Test: Postgres/DuckDB vs MSSQL (azure-sql-edge).

Validates that all MSSQL query translations produce equivalent results
to the original Postgres/DuckDB queries.

Usage:
    make sql-parity-test          # runs end-to-end
    python sql-parity-tests/sql_parity_test.py  # manual (assumes sql-edge is running + loaded)

Steps:
  1. Connect to DuckDB (local_postgres.duckdb, event_hubs.duckdb)
  2. Connect to azure-sql-edge (localhost:1433)
  3. Export DuckDB tables → azure-sql-edge (if tables are empty)
  4. Run each Postgres query against DuckDB, capture result
  5. Run the corresponding MSSQL query against azure-sql-edge, capture result
  6. Compare (within tolerance for floats), report pass/fail
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import duckdb
import pymssql

# ── Configuration ────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[1]

# Allow imports from the project root
sys.path.insert(0, str(REPO_ROOT))

POSTGRES_DB = str(REPO_ROOT / "local_postgres.duckdb")
EVENTHUB_DB = str(REPO_ROOT / "event_hubs.duckdb")

MSSQL_HOST = "localhost"
MSSQL_PORT = 1433
MSSQL_USER = "sa"
MSSQL_PASSWORD = "DevPass#2026!"
MSSQL_DATABASE = "parity_test"

# Tolerance for float comparison (0.01 = 1%)
FLOAT_TOLERANCE = 0.01

# Tables to export from local_postgres.duckdb
POSTGRES_TABLES = [
    "customer_journeys",
    "customer_snapshots",
    "order_metrics",
    "order_items",
    "hourly_demand",
    "campaign_interactions",
    "loyalty_account",
    "points_transactions",
    "support_tickets",
    "inventory",
    "inventory_events",
    "inventory_snapshots",
    "supplier_deliveries",
    "payments",
]

# Tables to export from event_hubs.duckdb
EVENTHUB_TABLES = [
    "customer_reviews",
]


# ── Dashboard Postgres queries (from metric-queries.ts) ──────────

DASHBOARD_POSTGRES_QUERIES = {
    "main": {
        "revenue": "SELECT SUM(total_amount) AS value FROM customer_journeys WHERE completed = TRUE",
        "customers": "SELECT COUNT(DISTINCT customer_id) AS value FROM customer_snapshots",
        "conversion": "SELECT COUNT(*) FILTER (WHERE completed) * 100.0 / COUNT(*) AS value FROM customer_journeys",
        "aov": "SELECT AVG(total_amount) AS value FROM customer_journeys WHERE completed = TRUE",
        "clv": "SELECT AVG(total_spend) AS value FROM customer_snapshots WHERE total_spend > 0",
        "return-rate": "SELECT COUNT(*) FILTER (WHERE returned) * 100.0 / COUNT(*) AS value FROM order_metrics",
    },
    "omnichannel": {
        "omni-arrival-rate": "SELECT COUNT(*) * 1.0 / NULLIF(MAX(arrival_time) - MIN(arrival_time), 0) AS value FROM customer_journeys",
        "omni-conversion": "SELECT COUNT(*) FILTER (WHERE completed) * 100.0 / COUNT(*) AS value FROM customer_journeys",
        "omni-cart-abandon": "SELECT COUNT(*) FILTER (WHERE abandoned) * 100.0 / COUNT(*) AS value FROM customer_journeys",
        "omni-avg-journey": "SELECT AVG(total_journey_time) AS value FROM customer_journeys",
        "omni-total-orders": "SELECT COUNT(*) AS value FROM order_metrics",
        "omni-ontime": "SELECT COUNT(*) FILTER (WHERE on_time) * 100.0 / COUNT(*) AS value FROM order_metrics",
        "omni-fulfillment-dur": "SELECT AVG(fulfillment_duration) AS value FROM order_metrics",
        "omni-payment-success": "SELECT COUNT(*) FILTER (WHERE NOT payment_failed) * 100.0 / COUNT(*) AS value FROM customer_journeys WHERE completed = TRUE OR payment_failed = TRUE",
    },
    "customer-engagement": {
        "ce-active-rate": "SELECT COUNT(*) FILTER (WHERE activity_state = 'active') * 100.0 / COUNT(*) AS value FROM customer_snapshots",
        "ce-churn-rate": "SELECT COUNT(*) FILTER (WHERE churned = TRUE) * 100.0 / COUNT(*) AS value FROM customer_snapshots",
        "ce-open-rate": "SELECT COUNT(*) FILTER (WHERE opened) * 100.0 / COUNT(*) AS value FROM campaign_interactions",
        "ce-campaign-ctr": "SELECT COUNT(*) FILTER (WHERE clicked) * 100.0 / COUNT(*) AS value FROM campaign_interactions",
        "ce-enrollment-rate": "SELECT COUNT(DISTINCT la.customer_id) * 100.0 / NULLIF(COUNT(DISTINCT cs.customer_id), 0) AS value FROM customer_snapshots cs LEFT JOIN loyalty_account la ON cs.customer_id = la.customer_id",
        "ce-redemption-rate": "SELECT SUM(CASE WHEN points_change < 0 THEN ABS(points_change) ELSE 0 END) * 100.0 / NULLIF(SUM(CASE WHEN points_change > 0 THEN points_change ELSE 0 END), 0) AS value FROM points_transactions",
        "ce-resolution-rate": "SELECT COUNT(*) FILTER (WHERE status = 'resolved') * 100.0 / COUNT(*) AS value FROM support_tickets",
        "ce-satisfaction": "SELECT AVG(satisfaction_rating) AS value FROM support_tickets WHERE satisfaction_rating IS NOT NULL",
    },
    "inventory-replenishment": {
        "ir-qty-on-hand": "SELECT SUM(quantity_on_hand) AS value FROM inventory",
        "ir-below-reorder": "SELECT COUNT(*) FILTER (WHERE quantity_on_hand <= reorder_point) AS value FROM inventory",
        "ir-stockout-count": "SELECT COUNT(*) FILTER (WHERE stockout_occurred = TRUE) AS value FROM inventory_events",
        "ir-fill-rate": "SELECT (1.0 - (COUNT(*) FILTER (WHERE stockout_occurred = TRUE) * 1.0 / NULLIF(COUNT(*), 0))) * 100.0 AS value FROM inventory_events",
        "ir-supplier-ontime": "SELECT COUNT(*) FILTER (WHERE on_time) * 100.0 / COUNT(*) AS value FROM supplier_deliveries",
        "ir-avg-lead-time": "SELECT AVG(actual_lead_time_days) AS value FROM supplier_deliveries",
        "ir-turnover": "SELECT AVG(daily_demand) * 365.0 / NULLIF(AVG(quantity_on_hand), 0) AS value FROM inventory_snapshots",
        "ir-shrinkage-rate": "SELECT SUM(CASE WHEN event_type = 'SHRINKAGE' THEN ABS(quantity_change) ELSE 0 END) * 100.0 / NULLIF(SUM(CASE WHEN event_type = 'SALE' THEN ABS(quantity_change) ELSE 0 END) + SUM(CASE WHEN event_type = 'SHRINKAGE' THEN ABS(quantity_change) ELSE 0 END), 0) AS value FROM inventory_events",
    },
    "customer-reviews": {
        "cr-total-reviews": "SELECT COUNT(*) AS value FROM customer_reviews",
        "cr-positive-pct": "SELECT COUNT(*) FILTER (WHERE sentiment_category IN ('positive','very_positive')) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_reviews",
        "cr-negative-pct": "SELECT COUNT(*) FILTER (WHERE sentiment_category IN ('negative','very_negative')) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_reviews",
        "cr-avg-score": "SELECT AVG(sentiment_score) AS value FROM customer_reviews WHERE sentiment_score IS NOT NULL",
        "cr-needs-review": "SELECT COUNT(*) AS value FROM customer_reviews WHERE status = 'Needing human review'",
        "cr-processed-pct": "SELECT COUNT(*) FILTER (WHERE status = 'processed for response') * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_reviews",
    },
}


# ── Dashboard MSSQL queries ──────────────────────────────────────

DASHBOARD_MSSQL_QUERIES = {
    "main": {
        "revenue": "SELECT SUM(total_amount) AS value FROM customer_journeys WHERE completed = 1",
        "customers": "SELECT COUNT(DISTINCT customer_id) AS value FROM customer_snapshots",
        "conversion": "SELECT COUNT(CASE WHEN completed = 1 THEN 1 END) * 100.0 / COUNT(*) AS value FROM customer_journeys",
        "aov": "SELECT AVG(total_amount) AS value FROM customer_journeys WHERE completed = 1",
        "clv": "SELECT AVG(total_spend) AS value FROM customer_snapshots WHERE total_spend > 0",
        "return-rate": "SELECT COUNT(CASE WHEN returned = 1 THEN 1 END) * 100.0 / COUNT(*) AS value FROM order_metrics",
    },
    "omnichannel": {
        "omni-arrival-rate": "SELECT COUNT(*) * 1.0 / NULLIF(MAX(arrival_time) - MIN(arrival_time), 0) AS value FROM customer_journeys",
        "omni-conversion": "SELECT COUNT(CASE WHEN completed = 1 THEN 1 END) * 100.0 / COUNT(*) AS value FROM customer_journeys",
        "omni-cart-abandon": "SELECT COUNT(CASE WHEN abandoned = 1 THEN 1 END) * 100.0 / COUNT(*) AS value FROM customer_journeys",
        "omni-avg-journey": "SELECT AVG(total_journey_time) AS value FROM customer_journeys",
        "omni-total-orders": "SELECT COUNT(*) AS value FROM order_metrics",
        "omni-ontime": "SELECT COUNT(CASE WHEN on_time = 1 THEN 1 END) * 100.0 / COUNT(*) AS value FROM order_metrics",
        "omni-fulfillment-dur": "SELECT AVG(fulfillment_duration) AS value FROM order_metrics",
        "omni-payment-success": "SELECT COUNT(CASE WHEN payment_failed = 0 THEN 1 END) * 100.0 / COUNT(*) AS value FROM customer_journeys WHERE completed = 1 OR payment_failed = 1",
    },
    "customer-engagement": {
        "ce-active-rate": "SELECT COUNT(CASE WHEN activity_state = 'active' THEN 1 END) * 100.0 / COUNT(*) AS value FROM customer_snapshots",
        "ce-churn-rate": "SELECT COUNT(CASE WHEN churned = 1 THEN 1 END) * 100.0 / COUNT(*) AS value FROM customer_snapshots",
        "ce-open-rate": "SELECT COUNT(CASE WHEN opened = 1 THEN 1 END) * 100.0 / COUNT(*) AS value FROM campaign_interactions",
        "ce-campaign-ctr": "SELECT COUNT(CASE WHEN clicked = 1 THEN 1 END) * 100.0 / COUNT(*) AS value FROM campaign_interactions",
        "ce-enrollment-rate": "SELECT COUNT(DISTINCT la.customer_id) * 100.0 / NULLIF(COUNT(DISTINCT cs.customer_id), 0) AS value FROM customer_snapshots cs LEFT JOIN loyalty_account la ON cs.customer_id = la.customer_id",
        "ce-redemption-rate": "SELECT SUM(CASE WHEN points_change < 0 THEN ABS(points_change) ELSE 0 END) * 100.0 / NULLIF(SUM(CASE WHEN points_change > 0 THEN points_change ELSE 0 END), 0) AS value FROM points_transactions",
        "ce-resolution-rate": "SELECT COUNT(CASE WHEN status = 'resolved' THEN 1 END) * 100.0 / COUNT(*) AS value FROM support_tickets",
        "ce-satisfaction": "SELECT AVG(CAST(satisfaction_rating AS FLOAT)) AS value FROM support_tickets WHERE satisfaction_rating IS NOT NULL",
    },
    "inventory-replenishment": {
        "ir-qty-on-hand": "SELECT SUM(quantity_on_hand) AS value FROM inventory",
        "ir-below-reorder": "SELECT COUNT(CASE WHEN quantity_on_hand <= reorder_point THEN 1 END) AS value FROM inventory",
        "ir-stockout-count": "SELECT COUNT(CASE WHEN stockout_occurred = 1 THEN 1 END) AS value FROM inventory_events",
        "ir-fill-rate": "SELECT (1.0 - (COUNT(CASE WHEN stockout_occurred = 1 THEN 1 END) * 1.0 / NULLIF(COUNT(*), 0))) * 100.0 AS value FROM inventory_events",
        "ir-supplier-ontime": "SELECT COUNT(CASE WHEN on_time = 1 THEN 1 END) * 100.0 / COUNT(*) AS value FROM supplier_deliveries",
        "ir-avg-lead-time": "SELECT AVG(actual_lead_time_days) AS value FROM supplier_deliveries",
        "ir-turnover": "SELECT AVG(CAST(daily_demand AS FLOAT)) * 365.0 / NULLIF(AVG(CAST(quantity_on_hand AS FLOAT)), 0) AS value FROM inventory_snapshots",
        "ir-shrinkage-rate": "SELECT SUM(CASE WHEN event_type = 'SHRINKAGE' THEN ABS(quantity_change) ELSE 0 END) * 100.0 / NULLIF(SUM(CASE WHEN event_type = 'SALE' THEN ABS(quantity_change) ELSE 0 END) + SUM(CASE WHEN event_type = 'SHRINKAGE' THEN ABS(quantity_change) ELSE 0 END), 0) AS value FROM inventory_events",
    },
    "customer-reviews": {
        "cr-total-reviews": "SELECT COUNT(*) AS value FROM customer_reviews",
        "cr-positive-pct": "SELECT COUNT(CASE WHEN sentiment_category IN ('positive','very_positive') THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_reviews",
        "cr-negative-pct": "SELECT COUNT(CASE WHEN sentiment_category IN ('negative','very_negative') THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_reviews",
        "cr-avg-score": "SELECT AVG(sentiment_score) AS value FROM customer_reviews WHERE sentiment_score IS NOT NULL",
        "cr-needs-review": "SELECT COUNT(*) AS value FROM customer_reviews WHERE status = 'Needing human review'",
        "cr-processed-pct": "SELECT COUNT(CASE WHEN status = 'processed for response' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_reviews",
    },
}


# ── Agent driver queries (Postgres/DuckDB) ───────────────────────
# Copied from agent tab modules — these are the canonical Postgres versions.

AGENT_DRIVER_POSTGRES = {
    "main": {
        "revenue": [
            ("Order Volume", "SELECT COUNT(*) AS value FROM customer_journeys WHERE completed = TRUE"),
            ("Average Order Value", "SELECT AVG(total_amount) AS value FROM customer_journeys WHERE completed = TRUE"),
            ("Basket Size", "SELECT AVG(basket_size) AS value FROM customer_journeys WHERE completed = TRUE"),
            ("Average Unit Price", "SELECT SUM(total_amount) / NULLIF(SUM(basket_size), 0) AS value FROM customer_journeys WHERE completed = TRUE"),
        ],
        "customers": [
            ("Active Customers", "SELECT COUNT(*) AS value FROM customer_snapshots WHERE activity_state = 'active'"),
            ("Lapsed Customers", "SELECT COUNT(*) AS value FROM customer_snapshots WHERE activity_state = 'lapsed'"),
            ("Churned Customers", "SELECT COUNT(*) AS value FROM customer_snapshots WHERE churned = TRUE"),
        ],
        "conversion": [
            ("Cart Abandonment Rate", "SELECT COUNT(CASE WHEN abandoned THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_journeys"),
            ("Payment Failure Rate", "SELECT COUNT(CASE WHEN payment_failed THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_journeys"),
            ("Queue Balk Rate", "SELECT COUNT(CASE WHEN abandonment_reason = 'queue_too_long' THEN 1 END) * 100.0 / NULLIF(COUNT(CASE WHEN channel = 'in_store' THEN 1 END), 0) AS value FROM customer_journeys"),
            ("Browsing Duration", "SELECT AVG(browsing_duration) AS value FROM customer_journeys"),
        ],
        "aov": [
            ("Basket Size", "SELECT AVG(basket_size) AS value FROM customer_journeys WHERE completed = TRUE"),
            ("Unit Price Distribution", "SELECT AVG(unit_price) AS value FROM order_items"),
        ],
        "clv": [
            ("Purchase Frequency", "SELECT AVG(purchase_count) AS value FROM customer_snapshots"),
            ("Average Order Value", "SELECT AVG(avg_order_value) AS value FROM customer_snapshots"),
            ("Customer Tenure", "SELECT AVG(days_since_join) AS value FROM customer_snapshots"),
            ("Loyalty Points Balance", "SELECT AVG(loyalty_points) AS value FROM customer_snapshots"),
            ("Churn Risk Score", "SELECT AVG(churn_risk_score) AS value FROM customer_snapshots"),
        ],
    },
    "omnichannel": {
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
            ("Avg Basket Size", "SELECT AVG(basket_size) AS value FROM customer_journeys WHERE completed = TRUE"),
        ],
        "omni-ontime": [
            ("Late Orders", "SELECT COUNT(*) AS value FROM order_metrics WHERE on_time = FALSE"),
            ("Return Rate", "SELECT COUNT(CASE WHEN returned THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM order_metrics"),
        ],
        "omni-fulfillment-dur": [
            ("On-Time Delivery %", "SELECT COUNT(CASE WHEN on_time THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM order_metrics"),
            ("Late Orders", "SELECT COUNT(*) AS value FROM order_metrics WHERE on_time = FALSE"),
        ],
        "omni-conversion": [
            ("Payment Failure Rate", "SELECT COUNT(CASE WHEN payment_failed THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_journeys"),
            ("Queue Balk Rate", "SELECT COUNT(CASE WHEN abandonment_reason = 'queue_too_long' THEN 1 END) * 100.0 / NULLIF(COUNT(CASE WHEN channel = 'in_store' THEN 1 END), 0) AS value FROM customer_journeys"),
        ],
        "omni-payment-success": [
            ("Conversion Impact", "SELECT COUNT(CASE WHEN payment_failed THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_journeys"),
        ],
    },
    "customer-engagement": {
        "ce-active-rate": [
            ("Lapsed Customer Rate", "SELECT COUNT(CASE WHEN activity_state = 'lapsed' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_snapshots"),
            ("Retention Rate", "SELECT (1 - COUNT(CASE WHEN churned THEN 1 END) * 1.0 / NULLIF(COUNT(*), 0)) * 100 AS value FROM customer_snapshots"),
        ],
        "ce-churn-rate": [
            ("Days Since Last Purchase", "SELECT AVG(days_since_last_purchase) AS value FROM customer_snapshots"),
            ("Unresponsive Count", "SELECT AVG(unresponsive_count) AS value FROM customer_snapshots"),
        ],
        "ce-open-rate": [
            ("Campaign Fatigue", "SELECT AVG(unresponsive_count) AS avg_unresponsive FROM customer_snapshots"),
        ],
        "ce-campaign-ctr": [
            ("Click-to-Open Rate", "SELECT COUNT(CASE WHEN clicked THEN 1 END) * 100.0 / NULLIF(COUNT(CASE WHEN opened THEN 1 END), 0) AS value FROM campaign_interactions"),
            ("Campaign Conversion Rate", "SELECT COUNT(CASE WHEN converted THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM campaign_interactions"),
        ],
        "ce-enrollment-rate": [
            ("Avg Points Balance", "SELECT AVG(current_points) AS value FROM loyalty_account"),
            ("Lifetime Points Earned", "SELECT SUM(lifetime_points) AS value FROM loyalty_account"),
        ],
        "ce-redemption-rate": [
            ("Points Issued", "SELECT SUM(points_change) AS value FROM points_transactions WHERE points_change > 0"),
            ("Points Redeemed", "SELECT SUM(ABS(points_change)) AS value FROM points_transactions WHERE points_change < 0"),
        ],
        "ce-resolution-rate": [
            ("Open Tickets", "SELECT COUNT(*) AS value FROM support_tickets WHERE status = 'open'"),
        ],
        "ce-satisfaction": [
            ("Total Tickets", "SELECT COUNT(*) AS value FROM support_tickets"),
        ],
    },
    "inventory-replenishment": {
        "ir-qty-on-hand": [
            ("Reserved Inventory", "SELECT SUM(quantity_reserved) AS value FROM inventory"),
            ("On-Order Inventory", "SELECT SUM(on_order_qty) AS value FROM inventory"),
            ("Days of Supply", "SELECT AVG(CASE WHEN daily_demand > 0 THEN quantity_on_hand * 1.0 / daily_demand ELSE NULL END) AS value FROM inventory_snapshots"),
        ],
        "ir-below-reorder": [
            ("Demand Spikes", "SELECT COUNT(*) AS value FROM inventory_snapshots WHERE daily_demand > 2 * (SELECT AVG(daily_demand) FROM inventory_snapshots)"),
            ("Slow Supplier Deliveries", "SELECT AVG(actual_lead_time_days - expected_lead_time_days) AS avg_delay FROM supplier_deliveries WHERE actual_lead_time_days > expected_lead_time_days"),
        ],
        "ir-stockout-count": [
            ("Demand Rate", "SELECT AVG(daily_demand) AS value FROM inventory_snapshots"),
            ("Supplier Lead Time", "SELECT AVG(actual_lead_time_days) AS value FROM supplier_deliveries"),
            ("Shrinkage Events", "SELECT COUNT(*) AS value FROM inventory_events WHERE event_type = 'SHRINKAGE'"),
        ],
        "ir-fill-rate": [
            ("Stockout Rate", "SELECT COUNT(CASE WHEN stockout_occurred THEN 1 END) * 100.0 / NULLIF(COUNT(CASE WHEN event_type = 'SALE' THEN 1 END), 0) AS value FROM inventory_events"),
        ],
        "ir-supplier-ontime": [
            ("Lead Time Variance", "SELECT STDDEV(actual_lead_time_days) AS value FROM supplier_deliveries"),
            ("Lead Time Accuracy", "SELECT AVG(actual_lead_time_days - expected_lead_time_days) AS value FROM supplier_deliveries"),
            ("Short Shipment Rate", "SELECT COUNT(CASE WHEN short_shipped THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM supplier_deliveries"),
        ],
        "ir-avg-lead-time": [
            ("Order Quantity Effect", "SELECT CORR(order_quantity, actual_lead_time_days) AS correlation FROM supplier_deliveries"),
            ("Received vs Ordered", "SELECT SUM(received_quantity) * 100.0 / NULLIF(SUM(order_quantity), 0) AS fill_rate FROM supplier_deliveries"),
        ],
        "ir-turnover": [
            ("Reorder Trigger Rate", "SELECT COUNT(CASE WHEN reorder_triggered THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM inventory_snapshots"),
        ],
        "ir-shrinkage-rate": [
            ("Shrinkage Events", "SELECT COUNT(*) AS total_events, SUM(ABS(quantity_change)) AS total_units FROM inventory_events WHERE event_type = 'SHRINKAGE'"),
        ],
    },
}


# ── Agent driver queries (MSSQL) ────────────────────────────────
# Imported from sql_variants and [_public]. prefix stripped for local testing.

from agents.mcp_server.tools.sql_variants import (
    _MAIN_DRIVER_SQL,
    _OMNI_DRIVER_SQL,
    _ENGAGEMENT_DRIVER_SQL,
    _INVENTORY_DRIVER_SQL,
    _AGGREGATED_HEALTH_CHECK,
)


def _strip_fabric_prefix(sql: str) -> str:
    """Remove [_public]. schema prefix used by Fabric-mirrored tables."""
    return sql.replace("[_public].", "")


def _strip_driver_dict(driver_dict: dict) -> dict:
    """Strip [_public]. from all SQL in a driver dict."""
    result = {}
    for metric_id, drivers in driver_dict.items():
        result[metric_id] = [
            (label, _strip_fabric_prefix(sql)) for label, sql in drivers
        ]
    return result


AGENT_DRIVER_MSSQL = {
    "main": _strip_driver_dict(_MAIN_DRIVER_SQL),
    "omnichannel": _strip_driver_dict(_OMNI_DRIVER_SQL),
    "customer-engagement": _strip_driver_dict(_ENGAGEMENT_DRIVER_SQL),
    "inventory-replenishment": _strip_driver_dict(_INVENTORY_DRIVER_SQL),
}

# Aggregated health check queries (single-value, like dashboard metrics)
AGGREGATED_MSSQL_QUERIES = {
    key: _strip_fabric_prefix(sql)
    for key, sql in _AGGREGATED_HEALTH_CHECK.items()
}

AGGREGATED_POSTGRES_QUERIES = {
    "revenue": "SELECT SUM(total_amount) AS value FROM customer_journeys WHERE completed = TRUE",
    "total_customers": "SELECT COUNT(DISTINCT customer_id) AS value FROM customer_snapshots",
    "conversion_rate": "SELECT COUNT(CASE WHEN completed THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_journeys",
    "total_orders": "SELECT COUNT(*) AS value FROM order_metrics",
    "ontime_delivery": "SELECT COUNT(CASE WHEN on_time THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM order_metrics",
    "avg_fulfillment": "SELECT AVG(fulfillment_duration) AS value FROM order_metrics",
    "active_rate": "SELECT COUNT(CASE WHEN activity_state = 'active' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_snapshots",
    "churn_rate": "SELECT COUNT(CASE WHEN churned THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_snapshots",
    "fill_rate": "SELECT (1.0 - COUNT(CASE WHEN stockout_occurred THEN 1 END) * 1.0 / NULLIF(COUNT(CASE WHEN event_type = 'SALE' THEN 1 END), 0)) * 100 AS value FROM inventory_events",
    "stockout_count": "SELECT COUNT(*) AS value FROM inventory_events WHERE stockout_occurred = TRUE",
    "supplier_ontime": "SELECT COUNT(CASE WHEN on_time THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM supplier_deliveries",
}


# ── Helpers ──────────────────────────────────────────────────────

def _connect_duckdb(path: str) -> duckdb.DuckDBPyConnection:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"DuckDB file not found: {path}")
    return duckdb.connect(str(p), read_only=True)


def _connect_mssql() -> pymssql.Connection:
    return pymssql.connect(
        server=MSSQL_HOST,
        port=MSSQL_PORT,
        user=MSSQL_USER,
        password=MSSQL_PASSWORD,
        database=MSSQL_DATABASE,
    )


def _ensure_database() -> None:
    """Create the parity_test database if it doesn't exist."""
    conn = pymssql.connect(
        server=MSSQL_HOST, port=MSSQL_PORT,
        user=MSSQL_USER, password=MSSQL_PASSWORD,
        autocommit=True,
    )
    cursor = conn.cursor()
    cursor.execute(f"IF DB_ID('{MSSQL_DATABASE}') IS NULL CREATE DATABASE [{MSSQL_DATABASE}]")
    conn.close()


def _run_query(conn, sql: str) -> float | None:
    """Run a query and return the 'value' column from the first row."""
    try:
        result = conn.execute(sql)
        if hasattr(result, "fetchone"):
            row = result.fetchone()
        else:
            row = result.fetchone()
        if row is None:
            return None
        # DuckDB returns tuples, pymssql returns tuples
        val = row[0]
        return float(val) if val is not None else None
    except Exception as e:
        print(f"  ERROR running query: {e}")
        print(f"  SQL: {sql[:200]}")
        return None


def _run_duckdb_query(conn: duckdb.DuckDBPyConnection, sql: str) -> float | None:
    try:
        result = conn.execute(sql)
        row = result.fetchone()
        if row is None:
            return None
        return float(row[0]) if row[0] is not None else None
    except Exception as e:
        print(f"  ERROR (DuckDB): {e}")
        print(f"  SQL: {sql[:200]}")
        return None


def _run_mssql_query(conn: pymssql.Connection, sql: str) -> float | None:
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        row = cursor.fetchone()
        if row is None:
            return None
        return float(row[0]) if row[0] is not None else None
    except Exception as e:
        print(f"  ERROR (MSSQL): {e}")
        print(f"  SQL: {sql[:200]}")
        return None


def _values_match(pg_val: float | None, ms_val: float | None) -> bool:
    """Compare two values within tolerance."""
    if pg_val is None and ms_val is None:
        return True
    if pg_val is None or ms_val is None:
        return False
    if pg_val == 0 and ms_val == 0:
        return True
    if pg_val == 0:
        return abs(ms_val) < FLOAT_TOLERANCE
    return abs(pg_val - ms_val) / abs(pg_val) < FLOAT_TOLERANCE


def _run_duckdb_multi(conn: duckdb.DuckDBPyConnection, sql: str) -> list[tuple] | None:
    """Run a query and return all rows as tuples (for multi-row comparison)."""
    try:
        result = conn.execute(sql)
        return result.fetchall()
    except Exception as e:
        print(f"  ERROR (DuckDB): {e}")
        print(f"  SQL: {sql[:200]}")
        return None


def _run_mssql_multi(conn: pymssql.Connection, sql: str) -> list[tuple] | None:
    """Run a query and return all rows as tuples (for multi-row comparison)."""
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        return cursor.fetchall()
    except Exception as e:
        print(f"  ERROR (MSSQL): {e}")
        print(f"  SQL: {sql[:200]}")
        return None


def _driver_results_match(pg_rows: list[tuple] | None, ms_rows: list[tuple] | None) -> tuple[bool, str]:
    """Compare multi-row driver results. Returns (match, reason)."""
    if pg_rows is None and ms_rows is None:
        return True, "both None"
    if pg_rows is None:
        return False, "Postgres query failed"
    if ms_rows is None:
        return False, "MSSQL query failed"
    if len(pg_rows) != len(ms_rows):
        return False, f"row count mismatch: pg={len(pg_rows)} mssql={len(ms_rows)}"
    # For single-value results, also compare the value
    if len(pg_rows) == 1 and len(pg_rows[0]) == 1:
        pg_val = float(pg_rows[0][0]) if pg_rows[0][0] is not None else None
        ms_val = float(ms_rows[0][0]) if ms_rows[0][0] is not None else None
        if not _values_match(pg_val, ms_val):
            return False, f"value mismatch: pg={pg_val} mssql={ms_val}"
    return True, f"rows={len(pg_rows)}"


# ── Table export: DuckDB → MSSQL ────────────────────────────────

def _get_duckdb_schema(conn: duckdb.DuckDBPyConnection, table: str) -> list[tuple[str, str]]:
    """Get column names and types for a DuckDB table."""
    result = conn.execute(f"PRAGMA table_info('{table}')")
    rows = result.fetchall()
    columns = []
    for row in rows:
        col_name = row[1]
        col_type = row[2].upper()
        columns.append((col_name, col_type))
    return columns


def _duckdb_type_to_mssql(dtype: str) -> str:
    """Map DuckDB types to MSSQL types."""
    dtype = dtype.upper()
    if "BIGINT" in dtype:
        return "BIGINT"
    if "INTEGER" in dtype or "INT" in dtype:
        return "INT"
    if "DOUBLE" in dtype or "FLOAT" in dtype or "REAL" in dtype:
        return "FLOAT"
    if "DECIMAL" in dtype or "NUMERIC" in dtype:
        return "DECIMAL(18,6)"
    if "BOOLEAN" in dtype or "BOOL" in dtype:
        return "BIT"
    if "VARCHAR" in dtype or "TEXT" in dtype or "STRING" in dtype:
        return "NVARCHAR(MAX)"
    if "TIMESTAMP" in dtype or "DATETIME" in dtype:
        return "DATETIME2"
    if "DATE" in dtype:
        return "DATE"
    if "TIME" in dtype:
        return "TIME"
    if "HUGEINT" in dtype:
        return "DECIMAL(38,0)"
    return "NVARCHAR(MAX)"


def _escape_val(val) -> str:
    """Escape a Python value for a T-SQL VALUES literal."""
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "1" if val else "0"
    if isinstance(val, (int, float)):
        return str(val)
    # String — escape single quotes
    s = str(val).replace("'", "''")
    return f"N'{s}'"


def _export_table(
    duck_conn: duckdb.DuckDBPyConnection,
    ms_conn: pymssql.Connection,
    table: str,
) -> int:
    """Export a DuckDB table to MSSQL. Returns row count."""
    columns = _get_duckdb_schema(duck_conn, table)
    if not columns:
        print(f"  WARNING: Table {table} has no columns, skipping.")
        return 0

    # Check if table already has correct row count
    duck_count_result = duck_conn.execute(f"SELECT COUNT(*) FROM {table}")
    duck_count = duck_count_result.fetchone()[0]

    cursor = ms_conn.cursor()
    try:
        cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
        ms_count = cursor.fetchone()[0]
        if ms_count == duck_count and ms_count > 0:
            print(f"  {table}: already has {ms_count} rows (matches DuckDB), skipping.")
            return ms_count
        if ms_count > 0 and ms_count != duck_count:
            print(f"  {table}: row count mismatch (DuckDB={duck_count}, MSSQL={ms_count}), re-exporting...")
    except Exception:
        pass  # Table doesn't exist yet

    # Create table
    col_defs = ", ".join(
        f"[{name}] {_duckdb_type_to_mssql(dtype)}" for name, dtype in columns
    )
    cursor.execute(f"IF OBJECT_ID('{table}', 'U') IS NOT NULL DROP TABLE [{table}]")
    cursor.execute(f"CREATE TABLE [{table}] ({col_defs})")
    ms_conn.commit()

    # Export data using multi-row INSERT VALUES (much faster than executemany)
    col_names_sql = ", ".join(f"[{c[0]}]" for c in columns)
    batch_size = 5000  # rows per INSERT statement (MSSQL limit is ~1000 per VALUES, but we chunk)
    insert_batch = 900  # max rows per single INSERT VALUES (safe under MSSQL 1000-row limit)
    total = 0

    # Stream all rows from DuckDB at once (avoids repeated OFFSET scans)
    result = duck_conn.execute(f"SELECT * FROM {table}")

    while True:
        rows = result.fetchmany(batch_size)
        if not rows:
            break

        # Send in sub-batches of insert_batch rows via multi-row INSERT
        for i in range(0, len(rows), insert_batch):
            chunk = rows[i:i + insert_batch]
            values_clauses = []
            for row in chunk:
                vals = ", ".join(_escape_val(v) for v in row)
                values_clauses.append(f"({vals})")

            sql = f"INSERT INTO [{table}] ({col_names_sql}) VALUES {', '.join(values_clauses)}"
            cursor.execute(sql)

        ms_conn.commit()
        total += len(rows)

    print(f"  {table}: exported {total} rows")
    return total


# ── Main test runner ─────────────────────────────────────────────

def run_parity_test() -> bool:
    """Run the full parity test. Returns True if all tests pass."""
    print("=" * 70)
    print("SQL Parity Test: Postgres/DuckDB vs MSSQL (azure-sql-edge)")
    print("=" * 70)

    # Step 1: Connect to DuckDB
    print("\n[1/4] Connecting to DuckDB...")
    try:
        pg_conn = _connect_duckdb(POSTGRES_DB)
        eh_conn = _connect_duckdb(EVENTHUB_DB)
        print(f"  Connected to {POSTGRES_DB}")
        print(f"  Connected to {EVENTHUB_DB}")
    except FileNotFoundError as e:
        print(f"  FATAL: {e}")
        return False

    # Step 2: Connect to MSSQL and ensure database
    print("\n[2/4] Connecting to azure-sql-edge...")
    try:
        _ensure_database()
        ms_conn = _connect_mssql()
        print(f"  Connected to {MSSQL_HOST}:{MSSQL_PORT}/{MSSQL_DATABASE}")
    except Exception as e:
        print(f"  FATAL: Cannot connect to MSSQL: {e}")
        print("  Is azure-sql-edge running? Try: docker compose -f sql-parity-tests/docker-compose-sqlserver.yml up -d")
        return False

    # Step 3: Export tables
    print("\n[3/4] Exporting DuckDB tables to MSSQL...")
    for table in POSTGRES_TABLES:
        _export_table(pg_conn, ms_conn, table)
    for table in EVENTHUB_TABLES:
        _export_table(eh_conn, ms_conn, table)

    # Step 4: Run parity tests
    print("\n[4/4] Running parity tests...")
    passed = 0
    failed = 0
    errors = []

    for tab, queries in DASHBOARD_POSTGRES_QUERIES.items():
        print(f"\n  --- {tab} ---")
        mssql_queries = DASHBOARD_MSSQL_QUERIES.get(tab, {})

        for metric_id, pg_sql in queries.items():
            ms_sql = mssql_queries.get(metric_id)
            if not ms_sql:
                print(f"  SKIP  {metric_id}: no MSSQL query defined")
                continue

            # Choose the right DuckDB connection
            duck = eh_conn if tab == "customer-reviews" else pg_conn

            pg_val = _run_duckdb_query(duck, pg_sql)
            ms_val = _run_mssql_query(ms_conn, ms_sql)

            if _values_match(pg_val, ms_val):
                print(f"  PASS  {metric_id}: pg={pg_val} mssql={ms_val}")
                passed += 1
            else:
                print(f"  FAIL  {metric_id}: pg={pg_val} mssql={ms_val}")
                failed += 1
                errors.append({
                    "tab": tab,
                    "metric": metric_id,
                    "postgres_value": pg_val,
                    "mssql_value": ms_val,
                    "postgres_sql": pg_sql,
                    "mssql_sql": ms_sql,
                })

    # Step 5: Driver query parity tests
    print("\n[5/6] Running driver query parity tests...")
    driver_passed = 0
    driver_failed = 0
    driver_errors = []

    for tab, metrics in AGENT_DRIVER_POSTGRES.items():
        print(f"\n  --- {tab} drivers ---")
        ms_tab = AGENT_DRIVER_MSSQL.get(tab, {})

        for metric_id, pg_drivers in metrics.items():
            ms_drivers = ms_tab.get(metric_id, [])
            if not ms_drivers:
                print(f"  SKIP  {metric_id}: no MSSQL drivers defined")
                continue

            # Build lookup by label for matching
            ms_by_label = {label: sql for label, sql in ms_drivers}

            for label, pg_sql in pg_drivers:
                ms_sql = ms_by_label.get(label)
                if not ms_sql:
                    print(f"  SKIP  {metric_id}/{label}: no matching MSSQL driver")
                    continue

                pg_rows = _run_duckdb_multi(pg_conn, pg_sql)
                ms_rows = _run_mssql_multi(ms_conn, ms_sql)

                match, reason = _driver_results_match(pg_rows, ms_rows)
                if match:
                    print(f"  PASS  {metric_id}/{label}: {reason}")
                    driver_passed += 1
                else:
                    print(f"  FAIL  {metric_id}/{label}: {reason}")
                    driver_failed += 1
                    driver_errors.append({
                        "tab": tab,
                        "metric": metric_id,
                        "driver": label,
                        "reason": reason,
                        "postgres_sql": pg_sql,
                        "mssql_sql": ms_sql,
                    })

    # Step 6: Aggregated health check parity
    print("\n[6/6] Running aggregated health check parity tests...")
    agg_passed = 0
    agg_failed = 0
    agg_errors = []

    print("\n  --- aggregated health check ---")
    for key, pg_sql in AGGREGATED_POSTGRES_QUERIES.items():
        ms_sql = AGGREGATED_MSSQL_QUERIES.get(key)
        if not ms_sql:
            print(f"  SKIP  {key}: no MSSQL query defined")
            continue

        pg_val = _run_duckdb_query(pg_conn, pg_sql)
        ms_val = _run_mssql_query(ms_conn, ms_sql)

        if _values_match(pg_val, ms_val):
            print(f"  PASS  {key}: pg={pg_val} mssql={ms_val}")
            agg_passed += 1
        else:
            print(f"  FAIL  {key}: pg={pg_val} mssql={ms_val}")
            agg_failed += 1
            agg_errors.append({
                "tab": "aggregated",
                "metric": key,
                "postgres_value": pg_val,
                "mssql_value": ms_val,
                "postgres_sql": pg_sql,
                "mssql_sql": ms_sql,
            })

    # Summary
    total_passed = passed + driver_passed + agg_passed
    total_failed = failed + driver_failed + agg_failed
    all_errors = errors + driver_errors + agg_errors

    print("\n" + "=" * 70)
    print(f"Dashboard metrics: {passed} passed, {failed} failed")
    print(f"Agent drivers:     {driver_passed} passed, {driver_failed} failed")
    print(f"Aggregated:        {agg_passed} passed, {agg_failed} failed")
    print(f"TOTAL:             {total_passed} passed, {total_failed} failed, {total_passed + total_failed} total")
    print("=" * 70)

    if all_errors:
        print("\nFailed queries:")
        for err in all_errors:
            label = err.get("driver", err.get("metric", ""))
            print(f"  [{err['tab']}] {label}:")
            if "postgres_value" in err:
                print(f"    Postgres: {err['postgres_value']}")
                print(f"    MSSQL:    {err['mssql_value']}")
            elif "reason" in err:
                print(f"    Reason: {err['reason']}")

    # Write report
    report_path = REPO_ROOT / "tests" / "parity-report.json"
    report = {
        "dashboard_metrics": {"passed": passed, "failed": failed},
        "agent_drivers": {"passed": driver_passed, "failed": driver_failed},
        "aggregated": {"passed": agg_passed, "failed": agg_failed},
        "total_passed": total_passed,
        "total_failed": total_failed,
        "total": total_passed + total_failed,
        "errors": all_errors,
        "status": "PASS" if total_failed == 0 else "FAIL",
    }
    report_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nReport written to {report_path}")

    # Cleanup
    pg_conn.close()
    eh_conn.close()
    ms_conn.close()

    return total_failed == 0


if __name__ == "__main__":
    success = run_parity_test()
    sys.exit(0 if success else 1)
