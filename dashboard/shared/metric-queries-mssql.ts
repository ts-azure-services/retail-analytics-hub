// MSSQL (Microsoft SQL Server) variants of dashboard metric queries.
//
// Used when FABRIC_SQL_ENDPOINT is set (cloud mode with Fabric SQL endpoint).
// All tables are prefixed with [_public]. for Fabric-mirrored Postgres tables.
// Customer reviews tab is NOT included — it uses KQL in cloud mode.

import type { MetricQuery } from './metric-queries.js'

export type MssqlTabId = 'main' | 'omnichannel' | 'customer-engagement' | 'inventory-replenishment'

// ---------------------------------------------------------------------------
// Main tab — 6 metrics
// ---------------------------------------------------------------------------

const mainQueries: MetricQuery[] = [
  {
    id: 'revenue',
    sql: 'SELECT SUM(total_amount) AS value FROM [_public].customer_journeys WHERE completed = 1',
  },
  {
    id: 'customers',
    sql: 'SELECT COUNT(DISTINCT customer_id) AS value FROM [_public].customer_snapshots',
  },
  {
    id: 'conversion',
    sql: 'SELECT COUNT(CASE WHEN completed = 1 THEN 1 END) * 100.0 / COUNT(*) AS value FROM [_public].customer_journeys',
  },
  {
    id: 'aov',
    sql: 'SELECT AVG(total_amount) AS value FROM [_public].customer_journeys WHERE completed = 1',
  },
  {
    id: 'clv',
    sql: 'SELECT AVG(total_spend) AS value FROM [_public].customer_snapshots WHERE total_spend > 0',
  },
  {
    id: 'return-rate',
    sql: 'SELECT COUNT(CASE WHEN returned = 1 THEN 1 END) * 100.0 / COUNT(*) AS value FROM [_public].order_metrics',
  },
]

// ---------------------------------------------------------------------------
// Omnichannel tab — 8 metrics
// ---------------------------------------------------------------------------

const omnichannelQueries: MetricQuery[] = [
  {
    id: 'omni-arrival-rate',
    sql: 'SELECT COUNT(*) * 1.0 / NULLIF(MAX(arrival_time) - MIN(arrival_time), 0) AS value FROM [_public].customer_journeys',
  },
  {
    id: 'omni-conversion',
    sql: 'SELECT COUNT(CASE WHEN completed = 1 THEN 1 END) * 100.0 / COUNT(*) AS value FROM [_public].customer_journeys',
  },
  {
    id: 'omni-cart-abandon',
    sql: 'SELECT COUNT(CASE WHEN abandoned = 1 THEN 1 END) * 100.0 / COUNT(*) AS value FROM [_public].customer_journeys',
  },
  {
    id: 'omni-avg-journey',
    sql: 'SELECT AVG(total_journey_time) AS value FROM [_public].customer_journeys',
  },
  {
    id: 'omni-total-orders',
    sql: 'SELECT COUNT(*) AS value FROM [_public].order_metrics',
  },
  {
    id: 'omni-ontime',
    sql: 'SELECT COUNT(CASE WHEN on_time = 1 THEN 1 END) * 100.0 / COUNT(*) AS value FROM [_public].order_metrics',
  },
  {
    id: 'omni-fulfillment-dur',
    sql: 'SELECT AVG(fulfillment_duration) AS value FROM [_public].order_metrics',
  },
  {
    id: 'omni-payment-success',
    sql: "SELECT COUNT(CASE WHEN payment_failed = 0 THEN 1 END) * 100.0 / COUNT(*) AS value FROM [_public].customer_journeys WHERE completed = 1 OR payment_failed = 1",
  },
]

// ---------------------------------------------------------------------------
// Customer Engagement tab — 8 metrics
// ---------------------------------------------------------------------------

const customerEngagementQueries: MetricQuery[] = [
  {
    id: 'ce-active-rate',
    sql: "SELECT COUNT(CASE WHEN activity_state = 'active' THEN 1 END) * 100.0 / COUNT(*) AS value FROM [_public].customer_snapshots",
  },
  {
    id: 'ce-churn-rate',
    sql: 'SELECT COUNT(CASE WHEN churned = 1 THEN 1 END) * 100.0 / COUNT(*) AS value FROM [_public].customer_snapshots',
  },
  {
    id: 'ce-open-rate',
    sql: 'SELECT COUNT(CASE WHEN opened = 1 THEN 1 END) * 100.0 / COUNT(*) AS value FROM [_public].campaign_interactions',
  },
  {
    id: 'ce-campaign-ctr',
    sql: 'SELECT COUNT(CASE WHEN clicked = 1 THEN 1 END) * 100.0 / COUNT(*) AS value FROM [_public].campaign_interactions',
  },
  {
    id: 'ce-enrollment-rate',
    sql: 'SELECT COUNT(DISTINCT la.customer_id) * 100.0 / NULLIF(COUNT(DISTINCT cs.customer_id), 0) AS value FROM [_public].customer_snapshots cs LEFT JOIN [_public].loyalty_account la ON cs.customer_id = la.customer_id',
  },
  {
    id: 'ce-redemption-rate',
    sql: `SELECT SUM(CASE WHEN points_change < 0 THEN ABS(points_change) ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN points_change > 0 THEN points_change ELSE 0 END), 0)
          AS value FROM [_public].points_transactions`,
  },
  {
    id: 'ce-resolution-rate',
    sql: "SELECT COUNT(CASE WHEN status = 'resolved' THEN 1 END) * 100.0 / COUNT(*) AS value FROM [_public].support_tickets",
  },
  {
    id: 'ce-satisfaction',
    sql: 'SELECT AVG(CAST(satisfaction_rating AS FLOAT)) AS value FROM [_public].support_tickets WHERE satisfaction_rating IS NOT NULL',
  },
]

// ---------------------------------------------------------------------------
// Inventory Replenishment tab — 8 metrics
// ---------------------------------------------------------------------------

const inventoryQueries: MetricQuery[] = [
  {
    id: 'ir-qty-on-hand',
    sql: 'SELECT SUM(quantity_on_hand) AS value FROM [_public].inventory',
  },
  {
    id: 'ir-below-reorder',
    sql: 'SELECT COUNT(CASE WHEN quantity_on_hand <= reorder_point THEN 1 END) AS value FROM [_public].inventory',
  },
  {
    id: 'ir-stockout-count',
    sql: 'SELECT COUNT(CASE WHEN stockout_occurred = 1 THEN 1 END) AS value FROM [_public].inventory_events',
  },
  {
    id: 'ir-fill-rate',
    sql: `SELECT (1.0 - (
            COUNT(CASE WHEN stockout_occurred = 1 THEN 1 END) * 1.0
            / NULLIF(COUNT(*), 0)
          )) * 100.0 AS value FROM [_public].inventory_events`,
  },
  {
    id: 'ir-supplier-ontime',
    sql: 'SELECT COUNT(CASE WHEN on_time = 1 THEN 1 END) * 100.0 / COUNT(*) AS value FROM [_public].supplier_deliveries',
  },
  {
    id: 'ir-avg-lead-time',
    sql: 'SELECT AVG(actual_lead_time_days) AS value FROM [_public].supplier_deliveries',
  },
  {
    id: 'ir-turnover',
    sql: 'SELECT AVG(CAST(daily_demand AS FLOAT)) * 365.0 / NULLIF(AVG(CAST(quantity_on_hand AS FLOAT)), 0) AS value FROM [_public].inventory_snapshots',
  },
  {
    id: 'ir-shrinkage-rate',
    sql: `SELECT SUM(CASE WHEN event_type = 'SHRINKAGE' THEN ABS(quantity_change) ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN event_type = 'SALE' THEN ABS(quantity_change) ELSE 0 END)
                   + SUM(CASE WHEN event_type = 'SHRINKAGE' THEN ABS(quantity_change) ELSE 0 END), 0)
          AS value FROM [_public].inventory_events`,
  },
]

// ---------------------------------------------------------------------------
// Lookup
// ---------------------------------------------------------------------------

const mssqlTabQueries: Record<MssqlTabId, MetricQuery[]> = {
  main: mainQueries,
  omnichannel: omnichannelQueries,
  'customer-engagement': customerEngagementQueries,
  'inventory-replenishment': inventoryQueries,
}

export function getMssqlQueriesForTab(tabId: string): MetricQuery[] {
  return mssqlTabQueries[tabId as MssqlTabId] ?? []
}
