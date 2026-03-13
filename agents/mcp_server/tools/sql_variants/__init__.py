"""MSSQL (Microsoft SQL Server) variants of all agent SQL queries.

Used when FABRIC_SQL_ENDPOINT is set (cloud mode with Fabric SQL endpoint).
All tables are prefixed with [_public]. for Fabric-mirrored Postgres tables.

Customer reviews queries are NOT included — they use KQL in cloud mode.
"""

from __future__ import annotations

# ── Main tab ─────────────────────────────────────────────────────

_MAIN_METRIC_SQL = {
    "revenue": {
        "label": "Total Revenue",
        "sql": "SELECT SUM(total_amount) AS value FROM [_public].customer_journeys WHERE completed = 1",
        "previous_sql": "SELECT SUM(total_amount) AS value FROM [_public].customer_journeys WHERE completed = 1",
        "format": "currency",
    },
    "customers": {
        "label": "Total Customers",
        "sql": "SELECT COUNT(DISTINCT customer_id) AS value FROM [_public].customer_snapshots",
        "previous_sql": "SELECT COUNT(DISTINCT customer_id) AS value FROM [_public].customer_snapshots",
        "format": "number",
    },
    "conversion": {
        "label": "Conversion Rate",
        "sql": "SELECT COUNT(CASE WHEN completed = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].customer_journeys",
        "previous_sql": "SELECT COUNT(CASE WHEN completed = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].customer_journeys",
        "format": "percentage",
    },
    "aov": {
        "label": "Average Order Value",
        "sql": "SELECT AVG(total_amount) AS value FROM [_public].customer_journeys WHERE completed = 1",
        "previous_sql": "SELECT AVG(total_amount) AS value FROM [_public].customer_journeys WHERE completed = 1",
        "format": "currency",
    },
    "clv": {
        "label": "Customer Lifetime Value",
        "sql": "SELECT AVG(total_spend) AS value FROM [_public].customer_snapshots WHERE total_spend > 0",
        "previous_sql": "SELECT AVG(total_spend) AS value FROM [_public].customer_snapshots WHERE total_spend > 0",
        "format": "currency",
    },
    "return-rate": {
        "label": "Return Rate",
        "sql": "SELECT COUNT(CASE WHEN returned = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].order_metrics",
        "previous_sql": "SELECT COUNT(CASE WHEN returned = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].order_metrics",
        "format": "percentage",
    },
}

_MAIN_DRIVER_SQL = {
    "revenue": [
        ("Order Volume", "SELECT COUNT(*) AS value FROM [_public].customer_journeys WHERE completed = 1"),
        ("Average Order Value", "SELECT AVG(total_amount) AS value FROM [_public].customer_journeys WHERE completed = 1"),
        ("Basket Size", "SELECT AVG(CAST(basket_size AS FLOAT)) AS value FROM [_public].customer_journeys WHERE completed = 1"),
        ("Average Unit Price", "SELECT SUM(total_amount) / NULLIF(SUM(basket_size), 0) AS value FROM [_public].customer_journeys WHERE completed = 1"),
        ("Channel Mix", "SELECT channel, SUM(total_amount) AS revenue, COUNT(*) AS orders FROM [_public].customer_journeys WHERE completed = 1 GROUP BY channel ORDER BY revenue DESC"),
    ],
    "customers": [
        ("Active Customers", "SELECT COUNT(*) AS value FROM [_public].customer_snapshots WHERE activity_state = 'active'"),
        ("Lapsed Customers", "SELECT COUNT(*) AS value FROM [_public].customer_snapshots WHERE activity_state = 'lapsed'"),
        ("Churned Customers", "SELECT COUNT(*) AS value FROM [_public].customer_snapshots WHERE churned = 1"),
        ("By Value Tier", "SELECT value_tier, COUNT(*) AS count FROM [_public].customer_snapshots GROUP BY value_tier ORDER BY count DESC"),
    ],
    "conversion": [
        ("Cart Abandonment Rate", "SELECT COUNT(CASE WHEN abandoned = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].customer_journeys"),
        ("Abandonment by Reason", "SELECT abandonment_reason, COUNT(*) AS count FROM [_public].customer_journeys WHERE abandoned = 1 GROUP BY abandonment_reason ORDER BY count DESC"),
        ("Payment Failure Rate", "SELECT COUNT(CASE WHEN payment_failed = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].customer_journeys"),
        ("Queue Balk Rate", "SELECT COUNT(CASE WHEN abandonment_reason = 'queue_too_long' THEN 1 END) * 100.0 / NULLIF(COUNT(CASE WHEN channel = 'in_store' THEN 1 END), 0) AS value FROM [_public].customer_journeys"),
        ("Browsing Duration", "SELECT AVG(browsing_duration) AS value FROM [_public].customer_journeys"),
    ],
    "aov": [
        ("Basket Size", "SELECT AVG(CAST(basket_size AS FLOAT)) AS value FROM [_public].customer_journeys WHERE completed = 1"),
        ("Unit Price Distribution", "SELECT AVG(unit_price) AS value FROM [_public].order_items"),
        ("Product Mix", "SELECT product_id, SUM(subtotal) AS revenue, SUM(quantity) AS units FROM [_public].order_items GROUP BY product_id ORDER BY revenue DESC"),
        ("Channel Effect", "SELECT channel, AVG(total_amount) AS avg_aov FROM [_public].customer_journeys WHERE completed = 1 GROUP BY channel ORDER BY avg_aov DESC"),
    ],
    "clv": [
        ("Purchase Frequency", "SELECT AVG(CAST(purchase_count AS FLOAT)) AS value FROM [_public].customer_snapshots"),
        ("Average Order Value", "SELECT AVG(avg_order_value) AS value FROM [_public].customer_snapshots"),
        ("Customer Tenure", "SELECT AVG(days_since_join) AS value FROM [_public].customer_snapshots"),
        ("Loyalty Points Balance", "SELECT AVG(CAST(loyalty_points AS FLOAT)) AS value FROM [_public].customer_snapshots"),
        ("Churn Risk Score", "SELECT AVG(churn_risk_score) AS value FROM [_public].customer_snapshots"),
    ],
    "return-rate": [
        ("Returns by Channel", "SELECT channel, COUNT(CASE WHEN returned = 1 THEN 1 END) AS returns, COUNT(*) AS total, COUNT(CASE WHEN returned = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS return_rate FROM [_public].order_metrics GROUP BY channel ORDER BY return_rate DESC"),
        ("Late Delivery Effect", "SELECT on_time, COUNT(CASE WHEN returned = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS return_rate FROM [_public].order_metrics GROUP BY on_time"),
        ("Fulfillment Duration Effect", "SELECT returned, AVG(fulfillment_duration) AS avg_fulfillment FROM [_public].order_metrics GROUP BY returned"),
    ],
}

# ── Omnichannel tab ──────────────────────────────────────────────

_OMNI_METRIC_SQL = {
    "omni-arrival-rate": {
        "label": "Arrival Rate",
        "sql": "SELECT COUNT(*) * 1.0 / NULLIF((SELECT MAX(hour_of_simulation) FROM [_public].hourly_demand), 0) AS value FROM [_public].customer_journeys",
        "format": "number",
    },
    "omni-conversion": {
        "label": "Conversion Rate",
        "sql": "SELECT COUNT(CASE WHEN completed = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].customer_journeys",
        "format": "percentage",
    },
    "omni-cart-abandon": {
        "label": "Cart Abandonment Rate",
        "sql": "SELECT COUNT(CASE WHEN abandoned = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].customer_journeys",
        "format": "percentage",
    },
    "omni-avg-journey": {
        "label": "Avg Journey Time",
        "sql": "SELECT AVG(total_journey_time) AS value FROM [_public].customer_journeys",
        "format": "number",
    },
    "omni-total-orders": {
        "label": "Total Orders",
        "sql": "SELECT COUNT(*) AS value FROM [_public].order_metrics",
        "format": "number",
    },
    "omni-ontime": {
        "label": "On-Time Delivery %",
        "sql": "SELECT COUNT(CASE WHEN on_time = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].order_metrics",
        "format": "percentage",
    },
    "omni-fulfillment-dur": {
        "label": "Avg Fulfillment Duration",
        "sql": "SELECT AVG(fulfillment_duration) AS value FROM [_public].order_metrics",
        "format": "number",
    },
    "omni-payment-success": {
        "label": "Payment Success Rate",
        "sql": "SELECT COUNT(CASE WHEN status = 'authorized' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].payments",
        "format": "percentage",
    },
}

_OMNI_DRIVER_SQL = {
    "omni-arrival-rate": [
        ("Hourly Arrival Count", "SELECT hour_of_simulation, AVG(arrival_count) AS avg_arrivals FROM [_public].hourly_demand GROUP BY hour_of_simulation ORDER BY hour_of_simulation"),
        ("Hourly Revenue", "SELECT hour_of_simulation, AVG(revenue) AS avg_revenue FROM [_public].hourly_demand GROUP BY hour_of_simulation ORDER BY hour_of_simulation"),
        ("Hourly Order Count", "SELECT hour_of_simulation, AVG(order_count) AS avg_orders FROM [_public].hourly_demand GROUP BY hour_of_simulation ORDER BY hour_of_simulation"),
        ("Hourly Abandonment", "SELECT hour_of_simulation, AVG(abandonment_count) AS avg_abandons FROM [_public].hourly_demand GROUP BY hour_of_simulation ORDER BY hour_of_simulation"),
    ],
    "omni-conversion": [
        ("Conversion by Channel", "SELECT channel, COUNT(CASE WHEN completed = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS conversion_rate, COUNT(*) AS total FROM [_public].customer_journeys GROUP BY channel ORDER BY conversion_rate DESC"),
        ("Payment Failure Rate", "SELECT COUNT(CASE WHEN payment_failed = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].customer_journeys"),
        ("Queue Balk Rate", "SELECT COUNT(CASE WHEN abandonment_reason = 'queue_too_long' THEN 1 END) * 100.0 / NULLIF(COUNT(CASE WHEN channel = 'in_store' THEN 1 END), 0) AS value FROM [_public].customer_journeys"),
    ],
    "omni-cart-abandon": [
        ("Price Sensitivity", "SELECT COUNT(*) AS value FROM [_public].customer_journeys WHERE abandonment_reason = 'price'"),
        ("Queue Too Long", "SELECT COUNT(*) AS value FROM [_public].customer_journeys WHERE abandonment_reason = 'queue_too_long'"),
        ("Browsing Fatigue", "SELECT COUNT(*) AS value FROM [_public].customer_journeys WHERE abandonment_reason = 'browsing_fatigue'"),
    ],
    "omni-avg-journey": [
        ("Avg Browsing Duration", "SELECT AVG(browsing_duration) AS value FROM [_public].customer_journeys"),
        ("Avg Queue Wait Time", "SELECT AVG(queue_wait_time) AS value FROM [_public].customer_journeys"),
        ("Avg Checkout Time", "SELECT AVG(checkout_time) AS value FROM [_public].customer_journeys"),
    ],
    "omni-total-orders": [
        ("Orders by Channel", "SELECT channel, COUNT(*) AS orders FROM [_public].order_metrics GROUP BY channel ORDER BY orders DESC"),
        ("Avg Basket Size", "SELECT AVG(CAST(basket_size AS FLOAT)) AS value FROM [_public].customer_journeys WHERE completed = 1"),
        ("Payment Method Distribution", "SELECT payment_method, COUNT(*) AS count FROM [_public].payments GROUP BY payment_method ORDER BY count DESC"),
    ],
    "omni-ontime": [
        ("Late Orders", "SELECT COUNT(*) AS value FROM [_public].order_metrics WHERE on_time = 0"),
        ("Fulfillment by Channel", "SELECT channel, AVG(fulfillment_duration) AS avg_duration FROM [_public].order_metrics GROUP BY channel ORDER BY avg_duration DESC"),
        ("Return Rate", "SELECT COUNT(CASE WHEN returned = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].order_metrics"),
    ],
    "omni-fulfillment-dur": [
        ("Duration by Channel", "SELECT channel, AVG(fulfillment_duration) AS avg_duration FROM [_public].order_metrics GROUP BY channel ORDER BY avg_duration DESC"),
        ("On-Time Delivery %", "SELECT COUNT(CASE WHEN on_time = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].order_metrics"),
        ("Late Orders", "SELECT COUNT(*) AS value FROM [_public].order_metrics WHERE on_time = 0"),
    ],
    "omni-payment-success": [
        ("By Payment Method", "SELECT payment_method, COUNT(CASE WHEN status = 'authorized' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS success_rate FROM [_public].payments GROUP BY payment_method ORDER BY success_rate DESC"),
        ("Gateway Reliability", "SELECT COUNT(CASE WHEN status != 'authorized' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS failure_rate FROM [_public].payments"),
        ("Conversion Impact", "SELECT COUNT(CASE WHEN payment_failed = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].customer_journeys"),
    ],
}

# ── Omnichannel extras ───────────────────────────────────────────

_OMNI_CHANNEL_COMPARISON_SQL = """
    SELECT
        channel,
        COUNT(*) AS total_journeys,
        COUNT(CASE WHEN completed = 1 THEN 1 END) AS completed_orders,
        COUNT(CASE WHEN completed = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS conversion_rate,
        AVG(CASE WHEN completed = 1 THEN total_amount END) AS avg_order_value,
        AVG(total_journey_time) AS avg_journey_time,
        COUNT(CASE WHEN abandoned = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS abandonment_rate
    FROM [_public].customer_journeys
    GROUP BY channel
    ORDER BY completed_orders DESC
"""

# ── Customer Engagement tab ──────────────────────────────────────

_ENGAGEMENT_METRIC_SQL = {
    "ce-active-rate": {
        "label": "Active Customer Rate",
        "sql": "SELECT COUNT(CASE WHEN activity_state = 'active' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].customer_snapshots",
        "format": "percentage",
    },
    "ce-churn-rate": {
        "label": "Churn Rate",
        "sql": "SELECT COUNT(CASE WHEN churned = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].customer_snapshots",
        "format": "percentage",
    },
    "ce-open-rate": {
        "label": "Campaign Open Rate",
        "sql": "SELECT COUNT(CASE WHEN opened = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].campaign_interactions",
        "format": "percentage",
    },
    "ce-campaign-ctr": {
        "label": "Campaign CTR",
        "sql": "SELECT COUNT(CASE WHEN clicked = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].campaign_interactions",
        "format": "percentage",
    },
    "ce-enrollment-rate": {
        "label": "Loyalty Enrollment Rate",
        "sql": "SELECT COUNT(DISTINCT la.customer_id) * 100.0 / NULLIF((SELECT COUNT(DISTINCT customer_id) FROM [_public].customer_snapshots), 0) AS value FROM [_public].loyalty_account la",
        "format": "percentage",
    },
    "ce-redemption-rate": {
        "label": "Points Redemption Rate",
        "sql": "SELECT SUM(CASE WHEN points_change < 0 THEN ABS(points_change) ELSE 0 END) * 100.0 / NULLIF(SUM(CASE WHEN points_change > 0 THEN points_change ELSE 0 END), 0) AS value FROM [_public].points_transactions",
        "format": "percentage",
    },
    "ce-resolution-rate": {
        "label": "Ticket Resolution Rate",
        "sql": "SELECT COUNT(CASE WHEN status = 'resolved' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].support_tickets",
        "format": "percentage",
    },
    "ce-satisfaction": {
        "label": "Avg Satisfaction Rating",
        "sql": "SELECT AVG(CAST(satisfaction_rating AS FLOAT)) AS value FROM [_public].support_tickets",
        "format": "number",
    },
}

_ENGAGEMENT_DRIVER_SQL = {
    "ce-active-rate": [
        ("Lapsed Customer Rate", "SELECT COUNT(CASE WHEN activity_state = 'lapsed' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].customer_snapshots"),
        ("Retention Rate", "SELECT (1 - COUNT(CASE WHEN churned = 1 THEN 1 END) * 1.0 / NULLIF(COUNT(*), 0)) * 100 AS value FROM [_public].customer_snapshots"),
        ("Lifecycle State Distribution", "SELECT activity_state, COUNT(*) AS count FROM [_public].customer_snapshots GROUP BY activity_state ORDER BY count DESC"),
    ],
    "ce-churn-rate": [
        ("Days Since Last Purchase", "SELECT AVG(days_since_last_purchase) AS value FROM [_public].customer_snapshots"),
        ("Unresponsive Count", "SELECT AVG(CAST(unresponsive_count AS FLOAT)) AS value FROM [_public].customer_snapshots"),
        ("Churn by Value Tier", "SELECT value_tier, COUNT(CASE WHEN churned = 1 THEN 1 END) AS churned, COUNT(*) AS total FROM [_public].customer_snapshots GROUP BY value_tier ORDER BY churned DESC"),
    ],
    "ce-open-rate": [
        ("Response by Campaign Type", "SELECT campaign_type, COUNT(CASE WHEN opened = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS open_rate, COUNT(*) AS total FROM [_public].campaign_interactions GROUP BY campaign_type ORDER BY open_rate DESC"),
        ("Campaign Fatigue", "SELECT AVG(CAST(unresponsive_count AS FLOAT)) AS avg_unresponsive FROM [_public].customer_snapshots"),
    ],
    "ce-campaign-ctr": [
        ("Click-to-Open Rate", "SELECT COUNT(CASE WHEN clicked = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(CASE WHEN opened = 1 THEN 1 END), 0) AS value FROM [_public].campaign_interactions"),
        ("Campaign Conversion Rate", "SELECT COUNT(CASE WHEN converted = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].campaign_interactions"),
        ("CTR by Campaign Type", "SELECT campaign_type, COUNT(CASE WHEN clicked = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS ctr FROM [_public].campaign_interactions GROUP BY campaign_type ORDER BY ctr DESC"),
    ],
    "ce-enrollment-rate": [
        ("Avg Points Balance", "SELECT AVG(current_points) AS value FROM [_public].loyalty_account"),
        ("Tier Distribution", "SELECT tier, COUNT(*) AS count FROM [_public].loyalty_account GROUP BY tier ORDER BY count DESC"),
        ("Lifetime Points Earned", "SELECT SUM(lifetime_points) AS value FROM [_public].loyalty_account"),
    ],
    "ce-redemption-rate": [
        ("Points Issued", "SELECT SUM(points_change) AS value FROM [_public].points_transactions WHERE points_change > 0"),
        ("Points Redeemed", "SELECT SUM(ABS(points_change)) AS value FROM [_public].points_transactions WHERE points_change < 0"),
        ("Transaction Reasons", "SELECT reason, COUNT(*) AS count FROM [_public].points_transactions GROUP BY reason ORDER BY count DESC"),
    ],
    "ce-resolution-rate": [
        ("Open Tickets", "SELECT COUNT(*) AS value FROM [_public].support_tickets WHERE status = 'open'"),
        ("Tickets by Issue Type", "SELECT issue_type, COUNT(*) AS count FROM [_public].support_tickets GROUP BY issue_type ORDER BY count DESC"),
    ],
    "ce-satisfaction": [
        ("Satisfaction by Issue Type", "SELECT issue_type, AVG(satisfaction_rating) AS avg_rating, COUNT(*) AS count FROM [_public].support_tickets GROUP BY issue_type ORDER BY avg_rating DESC"),
        ("Total Tickets", "SELECT COUNT(*) AS value FROM [_public].support_tickets"),
    ],
}

# ── Engagement extras ────────────────────────────────────────────

_ENGAGEMENT_SEGMENT_SQL = """
    SELECT
        value_tier,
        activity_state,
        COUNT(*) AS customers,
        AVG(total_spend) AS avg_spend,
        AVG(purchase_count) AS avg_purchases,
        AVG(churn_risk_score) AS avg_churn_risk,
        AVG(loyalty_points) AS avg_loyalty_points
    FROM [_public].customer_snapshots
    GROUP BY value_tier, activity_state
    ORDER BY value_tier, activity_state
"""

# ── Inventory Replenishment tab ──────────────────────────────────

_INVENTORY_METRIC_SQL = {
    "ir-qty-on-hand": {
        "label": "Total Qty on Hand",
        "sql": "SELECT SUM(quantity_on_hand) AS value FROM [_public].inventory",
        "format": "number",
    },
    "ir-below-reorder": {
        "label": "Items Below Reorder Point",
        "sql": "SELECT COUNT(*) AS value FROM [_public].inventory WHERE quantity_on_hand <= reorder_point",
        "format": "number",
    },
    "ir-stockout-count": {
        "label": "Stockout Count",
        "sql": "SELECT COUNT(*) AS value FROM [_public].inventory_events WHERE stockout_occurred = 1",
        "format": "number",
    },
    "ir-fill-rate": {
        "label": "Fill Rate",
        "sql": "SELECT (1.0 - COUNT(CASE WHEN stockout_occurred = 1 THEN 1 END) * 1.0 / NULLIF(COUNT(CASE WHEN event_type = 'SALE' THEN 1 END), 0)) * 100 AS value FROM [_public].inventory_events",
        "format": "percentage",
    },
    "ir-supplier-ontime": {
        "label": "Supplier On-Time %",
        "sql": "SELECT COUNT(CASE WHEN on_time = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].supplier_deliveries",
        "format": "percentage",
    },
    "ir-avg-lead-time": {
        "label": "Avg Lead Time",
        "sql": "SELECT AVG(actual_lead_time_days) AS value FROM [_public].supplier_deliveries",
        "format": "number",
    },
    "ir-turnover": {
        "label": "Inventory Turnover",
        "sql": "SELECT CASE WHEN AVG(CAST(quantity_on_hand AS FLOAT)) > 0 THEN SUM(CAST(daily_demand AS FLOAT)) * 365.0 / AVG(CAST(quantity_on_hand AS FLOAT)) ELSE 0 END AS value FROM [_public].inventory_snapshots",
        "format": "number",
    },
    "ir-shrinkage-rate": {
        "label": "Shrinkage Rate",
        "sql": "SELECT SUM(CASE WHEN event_type = 'SHRINKAGE' THEN ABS(quantity_change) ELSE 0 END) * 100.0 / NULLIF((SELECT SUM(quantity_on_hand) FROM [_public].inventory), 0) AS value FROM [_public].inventory_events",
        "format": "percentage",
    },
}

_INVENTORY_DRIVER_SQL = {
    "ir-qty-on-hand": [
        ("Quantity by Location", "SELECT location_id, SUM(quantity_on_hand) AS qty FROM [_public].inventory GROUP BY location_id ORDER BY qty DESC"),
        ("Reserved Inventory", "SELECT SUM(quantity_reserved) AS value FROM [_public].inventory"),
        ("On-Order Inventory", "SELECT SUM(on_order_qty) AS value FROM [_public].inventory"),
        ("Days of Supply", "SELECT AVG(CASE WHEN daily_demand > 0 THEN quantity_on_hand * 1.0 / daily_demand ELSE NULL END) AS value FROM [_public].inventory_snapshots"),
    ],
    "ir-below-reorder": [
        ("Demand Spikes", "SELECT COUNT(*) AS value FROM [_public].inventory_snapshots WHERE daily_demand > 2 * (SELECT AVG(daily_demand) FROM [_public].inventory_snapshots)"),
        ("Slow Supplier Deliveries", "SELECT AVG(actual_lead_time_days - expected_lead_time_days) AS avg_delay FROM [_public].supplier_deliveries WHERE actual_lead_time_days > expected_lead_time_days"),
        ("Items Below Reorder Detail", "SELECT sku, location_id, quantity_on_hand, reorder_point FROM [_public].inventory WHERE quantity_on_hand <= reorder_point ORDER BY quantity_on_hand ASC"),
    ],
    "ir-stockout-count": [
        ("Demand Rate", "SELECT AVG(CAST(daily_demand AS FLOAT)) AS value FROM [_public].inventory_snapshots"),
        ("Supplier Lead Time", "SELECT AVG(actual_lead_time_days) AS value FROM [_public].supplier_deliveries"),
        ("Shrinkage Events", "SELECT COUNT(*) AS value FROM [_public].inventory_events WHERE event_type = 'SHRINKAGE'"),
        ("Supplier Reliability", "SELECT COUNT(CASE WHEN on_time = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS on_time_pct, COUNT(CASE WHEN short_shipped = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS short_ship_pct FROM [_public].supplier_deliveries"),
    ],
    "ir-fill-rate": [
        ("Stockout Rate", "SELECT COUNT(CASE WHEN stockout_occurred = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(CASE WHEN event_type = 'SALE' THEN 1 END), 0) AS value FROM [_public].inventory_events"),
        ("Stockout by SKU", "SELECT sku, COUNT(*) AS stockouts FROM [_public].inventory_events WHERE stockout_occurred = 1 GROUP BY sku ORDER BY stockouts DESC"),
    ],
    "ir-supplier-ontime": [
        ("Lead Time Variance", "SELECT STDEV(actual_lead_time_days) AS value FROM [_public].supplier_deliveries"),
        ("Lead Time Accuracy", "SELECT AVG(actual_lead_time_days - expected_lead_time_days) AS value FROM [_public].supplier_deliveries"),
        ("Short Shipment Rate", "SELECT COUNT(CASE WHEN short_shipped = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].supplier_deliveries"),
    ],
    "ir-avg-lead-time": [
        ("By Supplier", "SELECT supplier_id, AVG(actual_lead_time_days) AS avg_lead_time, COUNT(*) AS deliveries FROM [_public].supplier_deliveries GROUP BY supplier_id ORDER BY avg_lead_time DESC"),
        ("Order Quantity Effect", "WITH pairs AS (SELECT CAST(order_quantity AS FLOAT) AS x, CAST(actual_lead_time_days AS FLOAT) AS y FROM [_public].supplier_deliveries WHERE order_quantity IS NOT NULL AND actual_lead_time_days IS NOT NULL) SELECT (AVG(x * y) - AVG(x) * AVG(y)) / NULLIF(STDEVP(x) * STDEVP(y), 0) AS correlation FROM pairs"),
        ("Received vs Ordered", "SELECT SUM(received_quantity) * 100.0 / NULLIF(SUM(order_quantity), 0) AS fill_rate FROM [_public].supplier_deliveries"),
    ],
    "ir-turnover": [
        ("Reorder Trigger Rate", "SELECT COUNT(CASE WHEN reorder_triggered = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].inventory_snapshots"),
        ("Demand Trend", "SELECT snapshot_day, SUM(daily_demand) AS total_demand FROM [_public].inventory_snapshots GROUP BY snapshot_day ORDER BY snapshot_day"),
    ],
    "ir-shrinkage-rate": [
        ("Shrinkage Events", "SELECT COUNT(*) AS total_events, SUM(ABS(quantity_change)) AS total_units FROM [_public].inventory_events WHERE event_type = 'SHRINKAGE'"),
        ("Shrinkage by SKU", "SELECT sku, SUM(ABS(quantity_change)) AS shrinkage_units FROM [_public].inventory_events WHERE event_type = 'SHRINKAGE' GROUP BY sku ORDER BY shrinkage_units DESC"),
    ],
}

# ── Inventory extras ─────────────────────────────────────────────

_INVENTORY_SKU_SUMMARY_SQL = """
    SELECT
        CASE WHEN quantity_on_hand <= reorder_point THEN 'below_reorder' ELSE 'above_reorder' END AS status,
        COUNT(*) AS sku_count,
        ROUND(AVG(quantity_on_hand), 1) AS avg_qty_on_hand,
        ROUND(AVG(quantity_reserved), 1) AS avg_qty_reserved,
        ROUND(AVG(on_order_qty), 1) AS avg_on_order,
        SUM(CASE WHEN quantity_on_hand = 0 THEN 1 ELSE 0 END) AS zero_stock_count
    FROM [_public].inventory
    GROUP BY CASE WHEN quantity_on_hand <= reorder_point THEN 'below_reorder' ELSE 'above_reorder' END
"""

_INVENTORY_CRITICAL_SKUS_SQL = """
    SELECT TOP 20
        i.sku,
        i.location_id,
        i.quantity_on_hand,
        i.quantity_reserved,
        i.on_order_qty,
        i.reorder_point,
        CASE WHEN i.quantity_on_hand <= i.reorder_point THEN 1 ELSE 0 END AS below_reorder
    FROM [_public].inventory i
    ORDER BY (i.quantity_on_hand - i.reorder_point) ASC
"""

# ── Timeseries ───────────────────────────────────────────────────

def get_mssql_hourly_demand_sql(hours: int = 24, channel: str | None = None) -> str:
    where = f"WHERE channel = '{channel}'" if channel else ""
    return f"""
        SELECT TOP {min(hours, 1000)}
            hour_of_simulation, hour_of_day, day_of_week, channel,
            arrival_count, order_count, abandonment_count, revenue, avg_basket_size
        FROM [_public].hourly_demand
        {where}
        ORDER BY hour_of_simulation DESC
    """


def get_mssql_demand_by_hour_sql() -> str:
    return """
        SELECT
            hour_of_day,
            AVG(arrival_count) AS avg_arrivals,
            AVG(order_count) AS avg_orders,
            AVG(abandonment_count) AS avg_abandonments,
            AVG(revenue) AS avg_revenue,
            COUNT(*) AS data_points
        FROM [_public].hourly_demand
        GROUP BY hour_of_day
        ORDER BY hour_of_day
    """

# ── Aggregated (cross-tab) ───────────────────────────────────────

_AGGREGATED_HEALTH_CHECK = {
    "revenue": "SELECT SUM(total_amount) AS value FROM [_public].customer_journeys WHERE completed = 1",
    "total_customers": "SELECT COUNT(DISTINCT customer_id) AS value FROM [_public].customer_snapshots",
    "conversion_rate": "SELECT COUNT(CASE WHEN completed = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].customer_journeys",
    "total_orders": "SELECT COUNT(*) AS value FROM [_public].order_metrics",
    "ontime_delivery": "SELECT COUNT(CASE WHEN on_time = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].order_metrics",
    "avg_fulfillment": "SELECT AVG(fulfillment_duration) AS value FROM [_public].order_metrics",
    "active_rate": "SELECT COUNT(CASE WHEN activity_state = 'active' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].customer_snapshots",
    "churn_rate": "SELECT COUNT(CASE WHEN churned = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].customer_snapshots",
    "fill_rate": "SELECT (1.0 - COUNT(CASE WHEN stockout_occurred = 1 THEN 1 END) * 1.0 / NULLIF(COUNT(CASE WHEN event_type = 'SALE' THEN 1 END), 0)) * 100 AS value FROM [_public].inventory_events",
    "stockout_count": "SELECT COUNT(*) AS value FROM [_public].inventory_events WHERE stockout_occurred = 1",
    "supplier_ontime": "SELECT COUNT(CASE WHEN on_time = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM [_public].supplier_deliveries",
}

_AGGREGATED_CHANNEL_SQL = """
    SELECT
        channel,
        COUNT(*) AS total_journeys,
        COUNT(CASE WHEN completed = 1 THEN 1 END) AS completed_orders,
        COUNT(CASE WHEN completed = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS conversion_rate,
        AVG(CASE WHEN completed = 1 THEN total_amount END) AS avg_order_value,
        AVG(total_journey_time) AS avg_journey_time,
        COUNT(CASE WHEN abandoned = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS abandonment_rate,
        SUM(CASE WHEN completed = 1 THEN total_amount ELSE 0 END) AS total_revenue
    FROM [_public].customer_journeys
    GROUP BY channel
"""

_AGGREGATED_ORDER_SQL = """
    SELECT
        channel,
        AVG(fulfillment_duration) AS avg_fulfillment,
        COUNT(CASE WHEN on_time = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS ontime_rate,
        COUNT(CASE WHEN returned = 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0) AS return_rate
    FROM [_public].order_metrics
    GROUP BY channel
"""

_AGGREGATED_CUSTOMER_SQL = """
    SELECT
        activity_state,
        COUNT(*) AS customers,
        AVG(total_spend) AS avg_spend,
        AVG(churn_risk_score) AS avg_churn_risk,
        AVG(purchase_count) AS avg_purchases
    FROM [_public].customer_snapshots
    GROUP BY activity_state
"""


# ── Public API ───────────────────────────────────────────────────

MSSQL_QUERIES = {
    "main": {"metrics": _MAIN_METRIC_SQL, "drivers": _MAIN_DRIVER_SQL},
    "omnichannel": {"metrics": _OMNI_METRIC_SQL, "drivers": _OMNI_DRIVER_SQL},
    "customer-engagement": {"metrics": _ENGAGEMENT_METRIC_SQL, "drivers": _ENGAGEMENT_DRIVER_SQL},
    "inventory-replenishment": {"metrics": _INVENTORY_METRIC_SQL, "drivers": _INVENTORY_DRIVER_SQL},
    "aggregated": {"health_check": _AGGREGATED_HEALTH_CHECK},
}


def get_mssql_metric_sql(tab: str) -> dict:
    """Return the MSSQL _METRIC_SQL dict for a tab."""
    return MSSQL_QUERIES.get(tab, {}).get("metrics", {})


def get_mssql_driver_sql(tab: str) -> dict:
    """Return the MSSQL _DRIVER_SQL dict for a tab."""
    return MSSQL_QUERIES.get(tab, {}).get("drivers", {})
