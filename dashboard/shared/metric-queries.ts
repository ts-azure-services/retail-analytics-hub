// Shared between server and client — no React dependencies.

export type TabId = 'main' | 'omnichannel' | 'customer-engagement' | 'inventory-replenishment' | 'customer-reviews'

export interface MetricQuery {
  id: string
  sql: string
}

// ---------------------------------------------------------------------------
// Main tab — 6 metrics
// ---------------------------------------------------------------------------

const mainQueries: MetricQuery[] = [
  {
    id: 'revenue',
    sql: 'SELECT SUM(total_amount) AS value FROM customer_journeys WHERE completed = TRUE',
  },
  {
    id: 'customers',
    sql: 'SELECT COUNT(DISTINCT customer_id) AS value FROM customer_snapshots',
  },
  {
    id: 'conversion',
    sql: 'SELECT COUNT(*) FILTER (WHERE completed) * 100.0 / COUNT(*) AS value FROM customer_journeys',
  },
  {
    id: 'aov',
    sql: 'SELECT AVG(total_amount) AS value FROM customer_journeys WHERE completed = TRUE',
  },
  {
    id: 'clv',
    sql: 'SELECT AVG(total_spend) AS value FROM customer_snapshots WHERE total_spend > 0',
  },
  {
    id: 'return-rate',
    sql: 'SELECT COUNT(*) FILTER (WHERE returned) * 100.0 / COUNT(*) AS value FROM order_metrics',
  },
]

// ---------------------------------------------------------------------------
// Omnichannel tab — 8 metrics
// ---------------------------------------------------------------------------

const omnichannelQueries: MetricQuery[] = [
  {
    id: 'omni-arrival-rate',
    sql: `SELECT COUNT(*) * 1.0 / NULLIF(MAX(arrival_time) - MIN(arrival_time), 0) AS value FROM customer_journeys`,
  },
  {
    id: 'omni-conversion',
    sql: 'SELECT COUNT(*) FILTER (WHERE completed) * 100.0 / COUNT(*) AS value FROM customer_journeys',
  },
  {
    id: 'omni-cart-abandon',
    sql: 'SELECT COUNT(*) FILTER (WHERE abandoned) * 100.0 / COUNT(*) AS value FROM customer_journeys',
  },
  {
    id: 'omni-avg-journey',
    sql: 'SELECT AVG(total_journey_time) AS value FROM customer_journeys',
  },
  {
    id: 'omni-total-orders',
    sql: 'SELECT COUNT(*) AS value FROM order_metrics',
  },
  {
    id: 'omni-ontime',
    sql: 'SELECT COUNT(*) FILTER (WHERE on_time) * 100.0 / COUNT(*) AS value FROM order_metrics',
  },
  {
    id: 'omni-fulfillment-dur',
    sql: 'SELECT AVG(fulfillment_duration) AS value FROM order_metrics',
  },
  {
    id: 'omni-payment-success',
    sql: "SELECT COUNT(*) FILTER (WHERE NOT payment_failed) * 100.0 / COUNT(*) AS value FROM customer_journeys WHERE completed = TRUE OR payment_failed = TRUE",
  },
]

// ---------------------------------------------------------------------------
// Customer Engagement tab — 8 metrics
// ---------------------------------------------------------------------------

const customerEngagementQueries: MetricQuery[] = [
  {
    id: 'ce-active-rate',
    sql: "SELECT COUNT(*) FILTER (WHERE activity_state = 'active') * 100.0 / COUNT(*) AS value FROM customer_snapshots",
  },
  {
    id: 'ce-churn-rate',
    sql: 'SELECT COUNT(*) FILTER (WHERE churned = TRUE) * 100.0 / COUNT(*) AS value FROM customer_snapshots',
  },
  {
    id: 'ce-open-rate',
    sql: 'SELECT COUNT(*) FILTER (WHERE opened) * 100.0 / COUNT(*) AS value FROM campaign_interactions',
  },
  {
    id: 'ce-campaign-ctr',
    sql: 'SELECT COUNT(*) FILTER (WHERE clicked) * 100.0 / COUNT(*) AS value FROM campaign_interactions',
  },
  {
    id: 'ce-enrollment-rate',
    sql: 'SELECT COUNT(DISTINCT la.customer_id) * 100.0 / NULLIF(COUNT(DISTINCT cs.customer_id), 0) AS value FROM customer_snapshots cs LEFT JOIN loyalty_account la ON cs.customer_id = la.customer_id',
  },
  {
    id: 'ce-redemption-rate',
    sql: `SELECT SUM(CASE WHEN points_change < 0 THEN ABS(points_change) ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN points_change > 0 THEN points_change ELSE 0 END), 0)
          AS value FROM points_transactions`,
  },
  {
    id: 'ce-resolution-rate',
    sql: "SELECT COUNT(*) FILTER (WHERE status = 'resolved') * 100.0 / COUNT(*) AS value FROM support_tickets",
  },
  {
    id: 'ce-satisfaction',
    sql: 'SELECT AVG(satisfaction_rating) AS value FROM support_tickets WHERE satisfaction_rating IS NOT NULL',
  },
]

// ---------------------------------------------------------------------------
// Inventory Replenishment tab — 8 metrics
// ---------------------------------------------------------------------------

const inventoryQueries: MetricQuery[] = [
  {
    id: 'ir-qty-on-hand',
    sql: 'SELECT SUM(quantity_on_hand) AS value FROM inventory',
  },
  {
    id: 'ir-below-reorder',
    sql: 'SELECT COUNT(*) FILTER (WHERE quantity_on_hand <= reorder_point) AS value FROM inventory',
  },
  {
    id: 'ir-stockout-count',
    sql: 'SELECT COUNT(*) FILTER (WHERE stockout_occurred = TRUE) AS value FROM inventory_events',
  },
  {
    id: 'ir-fill-rate',
    sql: `SELECT (1.0 - (
            COUNT(*) FILTER (WHERE stockout_occurred = TRUE) * 1.0
            / NULLIF(COUNT(*), 0)
          )) * 100.0 AS value FROM inventory_events`,
  },
  {
    id: 'ir-supplier-ontime',
    sql: 'SELECT COUNT(*) FILTER (WHERE on_time) * 100.0 / COUNT(*) AS value FROM supplier_deliveries',
  },
  {
    id: 'ir-avg-lead-time',
    sql: 'SELECT AVG(actual_lead_time_days) AS value FROM supplier_deliveries',
  },
  {
    id: 'ir-turnover',
    sql: 'SELECT AVG(daily_demand) * 365.0 / NULLIF(AVG(quantity_on_hand), 0) AS value FROM inventory_snapshots',
  },
  {
    id: 'ir-shrinkage-rate',
    sql: `SELECT SUM(CASE WHEN event_type = 'SHRINKAGE' THEN ABS(quantity_change) ELSE 0 END) * 100.0
            / NULLIF(SUM(CASE WHEN event_type = 'SALE' THEN ABS(quantity_change) ELSE 0 END)
                   + SUM(CASE WHEN event_type = 'SHRINKAGE' THEN ABS(quantity_change) ELSE 0 END), 0)
          AS value FROM inventory_events`,
  },
]

// ---------------------------------------------------------------------------
// Customer Reviews tab — 6 metrics
// ---------------------------------------------------------------------------

const customerReviewsQueries: MetricQuery[] = [
  {
    id: 'cr-total-reviews',
    sql: 'SELECT COUNT(*) AS value FROM customer_reviews',
  },
  {
    id: 'cr-positive-pct',
    sql: `SELECT COUNT(*) FILTER (WHERE sentiment_category IN ('positive','very_positive')) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_reviews`,
  },
  {
    id: 'cr-negative-pct',
    sql: `SELECT COUNT(*) FILTER (WHERE sentiment_category IN ('negative','very_negative')) * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_reviews`,
  },
  {
    id: 'cr-avg-score',
    sql: 'SELECT AVG(sentiment_score) AS value FROM customer_reviews WHERE sentiment_score IS NOT NULL',
  },
  {
    id: 'cr-needs-review',
    sql: `SELECT COUNT(*) AS value FROM customer_reviews WHERE status = 'Needing human review'`,
  },
  {
    id: 'cr-processed-pct',
    sql: `SELECT COUNT(*) FILTER (WHERE status = 'processed for response') * 100.0 / NULLIF(COUNT(*), 0) AS value FROM customer_reviews`,
  },
]

// ---------------------------------------------------------------------------
// Lookup
// ---------------------------------------------------------------------------

const tabQueries: Record<TabId, MetricQuery[]> = {
  main: mainQueries,
  omnichannel: omnichannelQueries,
  'customer-engagement': customerEngagementQueries,
  'inventory-replenishment': inventoryQueries,
  'customer-reviews': customerReviewsQueries,
}

export function getQueriesForTab(tabId: string): MetricQuery[] {
  return tabQueries[tabId as TabId] ?? []
}

export const validTabIds: TabId[] = ['main', 'omnichannel', 'customer-engagement', 'inventory-replenishment', 'customer-reviews']
