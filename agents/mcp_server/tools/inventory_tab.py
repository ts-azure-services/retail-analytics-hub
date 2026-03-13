"""MCP tools for the Inventory Replenishment dashboard tab (8 metrics).

Metrics: qty-on-hand, below-reorder, stockout-count, fill-rate,
         supplier-ontime, avg-lead-time, turnover, shrinkage-rate
Tables: inventory, inventory_events, inventory_snapshots, supplier_deliveries,
        purchase_order_lines
"""

from __future__ import annotations

from mcp.types import Tool

from agents.shared.db import get_postgres_connection, execute_query, use_mssql_dialect

_METRIC_SQL = {
    "ir-qty-on-hand": {
        "label": "Total Qty on Hand",
        "sql": "SELECT SUM(quantity_on_hand) AS value FROM inventory",
        "format": "number",
    },
    "ir-below-reorder": {
        "label": "Items Below Reorder Point",
        "sql": "SELECT COUNT(*) AS value FROM inventory WHERE quantity_on_hand <= reorder_point",
        "format": "number",
    },
    "ir-stockout-count": {
        "label": "Stockout Count",
        "sql": "SELECT COUNT(*) AS value FROM inventory_events WHERE stockout_occurred = TRUE",
        "format": "number",
    },
    "ir-fill-rate": {
        "label": "Fill Rate",
        "sql": """SELECT (1.0 - COUNT(CASE WHEN stockout_occurred THEN 1 END) * 1.0 /
                  NULLIF(COUNT(CASE WHEN event_type = 'SALE' THEN 1 END), 0)) * 100 AS value
                  FROM inventory_events""",
        "format": "percentage",
    },
    "ir-supplier-ontime": {
        "label": "Supplier On-Time %",
        "sql": "SELECT COUNT(CASE WHEN on_time THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM supplier_deliveries",
        "format": "percentage",
    },
    "ir-avg-lead-time": {
        "label": "Avg Lead Time",
        "sql": "SELECT AVG(actual_lead_time_days) AS value FROM supplier_deliveries",
        "format": "number",
    },
    "ir-turnover": {
        "label": "Inventory Turnover",
        "sql": """SELECT
                    CASE WHEN AVG(quantity_on_hand) > 0
                         THEN SUM(daily_demand) * 365.0 / AVG(quantity_on_hand)
                         ELSE 0 END AS value
                  FROM inventory_snapshots""",
        "format": "number",
    },
    "ir-shrinkage-rate": {
        "label": "Shrinkage Rate",
        "sql": """SELECT
                    SUM(CASE WHEN event_type = 'SHRINKAGE' THEN ABS(quantity_change) ELSE 0 END) * 100.0 /
                    NULLIF((SELECT SUM(quantity_on_hand) FROM inventory), 0) AS value
                  FROM inventory_events""",
        "format": "percentage",
    },
}

_DRIVER_SQL = {
    "ir-qty-on-hand": [
        ("Quantity by Location", "SELECT location_id, SUM(quantity_on_hand) AS qty FROM inventory GROUP BY location_id ORDER BY qty DESC"),
        ("Reserved Inventory", "SELECT SUM(quantity_reserved) AS value FROM inventory"),
        ("On-Order Inventory", "SELECT SUM(on_order_qty) AS value FROM inventory"),
        ("Days of Supply", "SELECT AVG(CASE WHEN daily_demand > 0 THEN quantity_on_hand * 1.0 / daily_demand ELSE NULL END) AS value FROM inventory_snapshots"),
    ],
    "ir-below-reorder": [
        ("Demand Spikes", "SELECT COUNT(*) AS value FROM inventory_snapshots WHERE daily_demand > 2 * (SELECT AVG(daily_demand) FROM inventory_snapshots)"),
        ("Slow Supplier Deliveries", "SELECT AVG(actual_lead_time_days - expected_lead_time_days) AS avg_delay FROM supplier_deliveries WHERE actual_lead_time_days > expected_lead_time_days"),
        ("Items Below Reorder Detail", "SELECT sku, location_id, quantity_on_hand, reorder_point FROM inventory WHERE quantity_on_hand <= reorder_point ORDER BY quantity_on_hand ASC"),
    ],
    "ir-stockout-count": [
        ("Demand Rate", "SELECT AVG(daily_demand) AS value FROM inventory_snapshots"),
        ("Supplier Lead Time", "SELECT AVG(actual_lead_time_days) AS value FROM supplier_deliveries"),
        ("Shrinkage Events", "SELECT COUNT(*) AS value FROM inventory_events WHERE event_type = 'SHRINKAGE'"),
        ("Supplier Reliability", "SELECT COUNT(CASE WHEN on_time THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS on_time_pct, COUNT(CASE WHEN short_shipped THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS short_ship_pct FROM supplier_deliveries"),
    ],
    "ir-fill-rate": [
        ("Stockout Rate", "SELECT COUNT(CASE WHEN stockout_occurred THEN 1 END) * 100.0 / NULLIF(COUNT(CASE WHEN event_type = 'SALE' THEN 1 END), 0) AS value FROM inventory_events"),
        ("Stockout by SKU", "SELECT sku, COUNT(*) AS stockouts FROM inventory_events WHERE stockout_occurred = TRUE GROUP BY sku ORDER BY stockouts DESC"),
    ],
    "ir-supplier-ontime": [
        ("Lead Time Variance", "SELECT STDDEV(actual_lead_time_days) AS value FROM supplier_deliveries"),
        ("Lead Time Accuracy", "SELECT AVG(actual_lead_time_days - expected_lead_time_days) AS value FROM supplier_deliveries"),
        ("Short Shipment Rate", "SELECT COUNT(CASE WHEN short_shipped THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM supplier_deliveries"),
    ],
    "ir-avg-lead-time": [
        ("By Supplier", "SELECT supplier_id, AVG(actual_lead_time_days) AS avg_lead_time, COUNT(*) AS deliveries FROM supplier_deliveries GROUP BY supplier_id ORDER BY avg_lead_time DESC"),
        ("Order Quantity Effect", "SELECT CORR(order_quantity, actual_lead_time_days) AS correlation FROM supplier_deliveries"),
        ("Received vs Ordered", "SELECT SUM(received_quantity) * 100.0 / NULLIF(SUM(order_quantity), 0) AS fill_rate FROM supplier_deliveries"),
    ],
    "ir-turnover": [
        ("Reorder Trigger Rate", "SELECT COUNT(CASE WHEN reorder_triggered THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM inventory_snapshots"),
        ("Demand Trend", "SELECT snapshot_day, SUM(daily_demand) AS total_demand FROM inventory_snapshots GROUP BY snapshot_day ORDER BY snapshot_day"),
    ],
    "ir-shrinkage-rate": [
        ("Shrinkage Events", "SELECT COUNT(*) AS total_events, SUM(ABS(quantity_change)) AS total_units FROM inventory_events WHERE event_type = 'SHRINKAGE'"),
        ("Shrinkage by SKU", "SELECT sku, SUM(ABS(quantity_change)) AS shrinkage_units FROM inventory_events WHERE event_type = 'SHRINKAGE' GROUP BY sku ORDER BY shrinkage_units DESC"),
    ],
}


def _get_metrics_summary() -> dict:
    conn = get_postgres_connection()
    try:
        if use_mssql_dialect():
            from agents.mcp_server.tools.sql_variants import get_mssql_metric_sql
            metric_sql = get_mssql_metric_sql("inventory-replenishment")
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
        return {"tab": "inventory-replenishment", "metrics": results}
    finally:
        conn.close()


def _get_metric_drivers(metric_id: str) -> dict:
    if use_mssql_dialect():
        from agents.mcp_server.tools.sql_variants import get_mssql_driver_sql
        driver_sql = get_mssql_driver_sql("inventory-replenishment")
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
        return {"metric_id": metric_id, "tab": "inventory-replenishment", "drivers": drivers}
    finally:
        conn.close()


def _get_sku_analysis() -> dict:
    """Analyze inventory health at the SKU level — summarised to avoid token overflow."""
    conn = get_postgres_connection()
    try:
        if use_mssql_dialect():
            from agents.mcp_server.tools.sql_variants import (
                _INVENTORY_SKU_SUMMARY_SQL,
                _INVENTORY_CRITICAL_SKUS_SQL,
            )
            summary_sql = _INVENTORY_SKU_SUMMARY_SQL
            critical_sql = _INVENTORY_CRITICAL_SKUS_SQL
        else:
            # High-level summary: counts and averages by reorder status
            summary_sql = """
                SELECT
                    CASE WHEN quantity_on_hand <= reorder_point THEN 'below_reorder' ELSE 'above_reorder' END AS status,
                    COUNT(*) AS sku_count,
                    ROUND(AVG(quantity_on_hand), 1) AS avg_qty_on_hand,
                    ROUND(AVG(quantity_reserved), 1) AS avg_qty_reserved,
                    ROUND(AVG(on_order_qty), 1) AS avg_on_order,
                    SUM(CASE WHEN quantity_on_hand = 0 THEN 1 ELSE 0 END) AS zero_stock_count
                FROM inventory
                GROUP BY status
            """
            # Top 20 most critical SKUs (lowest stock relative to reorder point)
            critical_sql = """
                SELECT
                    i.sku,
                    i.location_id,
                    i.quantity_on_hand,
                    i.quantity_reserved,
                    i.on_order_qty,
                    i.reorder_point,
                    CASE WHEN i.quantity_on_hand <= i.reorder_point THEN TRUE ELSE FALSE END AS below_reorder
                FROM inventory i
                ORDER BY (i.quantity_on_hand - i.reorder_point) ASC
                LIMIT 20
            """
        summary_rows = execute_query(conn, summary_sql)
        critical_rows = execute_query(conn, critical_sql)
        return {"summary": summary_rows, "critical_skus": critical_rows}
    finally:
        conn.close()


def get_tools():
    return [
        (
            Tool(
                name="get_inventory_metrics_summary",
                description="Get all 8 Inventory Replenishment tab metrics: qty on hand, below reorder, stockouts, fill rate, supplier on-time, lead time, turnover, shrinkage.",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            _get_metrics_summary,
        ),
        (
            Tool(
                name="get_inventory_metric_drivers",
                description="Get driver analysis for a specific Inventory Replenishment metric.",
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
                name="get_sku_analysis",
                description="Analyze inventory health at the SKU level. Returns quantity on hand, reserved, on order, reorder point status for each SKU.",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            _get_sku_analysis,
        ),
    ]
