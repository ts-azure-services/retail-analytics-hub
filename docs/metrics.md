# Metrics

This document defines all business metrics available from the simulation data, organized into high-level retail KPIs and workflow-specific metrics. Each metric includes its computation method, source tables, and composite drivers that explain movement in the metric.

All metrics are computed from `local_postgres.duckdb` unless otherwise noted. Event-level data in `local_cosmos.duckdb` (JSON documents in `WorkflowEvents`, `FulfillmentState`, `InventoryEvents`, `EngagementEvents`) provides supplementary detail for drill-down analysis.

---

## High-Level Retail Metrics

These are executive-level KPIs that span the entire retail operation. Most are derived by combining data across multiple tables.

### 1. Total Revenue

The top-line metric for the business.

**Computation:**

```sql
-- From completed customer journeys (simulation/sweep data)
SELECT SUM(total_amount) FROM customer_journeys WHERE completed = TRUE;

-- From seed orders (transactional data)
SELECT SUM(total_amount) FROM orders WHERE status = 'completed';
```

**Composite Drivers:**

| Driver | Formula | Source Table | Why It Matters |
|--------|---------|-------------|----------------|
| Order Volume | `COUNT(*) WHERE completed = TRUE` | `customer_journeys` | More orders = more revenue; driven by traffic and conversion |
| Average Order Value (AOV) | `AVG(total_amount) WHERE completed = TRUE` | `customer_journeys` | Higher basket value lifts revenue without needing more traffic |
| Basket Size | `AVG(basket_size) WHERE completed = TRUE` | `customer_journeys` | Larger baskets directly increase order value |
| Average Unit Price | `SUM(total_amount) / SUM(basket_size)` | `customer_journeys` | Product mix shift toward premium items raises AOV |
| Channel Mix | `SUM(total_amount) GROUP BY channel` | `customer_journeys` | Online vs in-store vs BOPIS have different AOVs and conversion rates |
| Lost Sales from Stockouts | `SUM(quantity_change) WHERE stockout_occurred = TRUE` | `inventory_events` | Revenue that could not be captured due to out-of-stock |
| Return-Adjusted Revenue | `revenue - SUM(refund_amount)` | `returns` | Returns reduce net revenue; high return rate erodes margin |

**Drill-Down:** Revenue by channel, by hour of day (`hourly_demand.revenue`), by product category (`order_items` joined to `products`).

---

### 2. Total Customers

**Computation:**

```sql
-- Master customer count
SELECT COUNT(*) FROM customers;

-- Active customers (from engagement snapshots)
SELECT COUNT(DISTINCT customer_id) FROM customer_snapshots
WHERE activity_state = 'active';
```

**Composite Drivers:**

| Driver | Formula | Source Table |
|--------|---------|-------------|
| Arrivals (Traffic) | `COUNT(*)` | `customer_journeys` |
| Active Customers | `COUNT(*) WHERE activity_state = 'active'` | `customer_snapshots` |
| Lapsed Customers | `COUNT(*) WHERE activity_state = 'lapsed'` | `customer_snapshots` |
| Churned Customers | `COUNT(*) WHERE churned = TRUE` | `customer_snapshots` |
| Loyalty Enrolled | `COUNT(*)` | `loyalty_account` |
| Customers by Channel | `COUNT(*) GROUP BY channel` | `customer_journeys` |

---

### 3. Conversion Rate

The fraction of arriving customers who complete a purchase.

**Computation:**

```sql
SELECT
    COUNT(CASE WHEN completed THEN 1 END) * 100.0 / COUNT(*) AS conversion_rate
FROM customer_journeys;
```

**Composite Drivers:**

| Driver | Formula | Source Table | Why It Matters |
|--------|---------|-------------|----------------|
| Cart Abandonment Rate | `COUNT(WHERE abandoned) / COUNT(*)` | `customer_journeys` | Primary leak in the funnel |
| Abandonment by Reason | `COUNT(*) GROUP BY abandonment_reason` | `customer_journeys` | Identifies whether abandonment is due to price, wait time, or browsing fatigue |
| Payment Failure Rate | `COUNT(WHERE payment_failed) / COUNT(*)` | `customer_journeys` | Technical failures that block otherwise willing buyers |
| Queue Balk Rate | `COUNT(WHERE abandonment_reason = 'queue_too_long') / in_store_count` | `customer_journeys` | In-store customers who leave because the line is too long |
| Browsing Duration | `AVG(browsing_duration)` | `customer_journeys` | Longer browsing can indicate engagement or friction |
| Conversion by Channel | `conversion grouped by channel` | `customer_journeys` | Channel-specific conversion identifies where effort is needed |

---

### 4. Average Order Value (AOV)

**Computation:**

```sql
SELECT AVG(total_amount) FROM customer_journeys WHERE completed = TRUE;
```

**Composite Drivers:**

| Driver | Formula | Source Table |
|--------|---------|-------------|
| Basket Size | `AVG(basket_size)` | `customer_journeys` |
| Unit Price Distribution | `AVG(unit_price)` | `order_items` |
| Product Category Mix | `SUM(subtotal) GROUP BY category` | `order_items` JOIN `products` |
| Channel Effect | `AVG(total_amount) GROUP BY channel` | `customer_journeys` |

---

### 5. Customer Lifetime Value (CLV)

Total spend per customer over their lifetime, a forward-looking indicator of customer profitability.

**Computation:**

```sql
-- From engagement snapshots (per simulation scenario)
SELECT AVG(total_spend) FROM customer_snapshots WHERE total_spend > 0;

-- From purchase history (seed data)
SELECT customer_id, SUM(line_total) AS lifetime_value
FROM customer_purchase_history
GROUP BY customer_id;
```

**Composite Drivers:**

| Driver | Formula | Source Table |
|--------|---------|-------------|
| Purchase Frequency | `AVG(purchase_count)` | `customer_snapshots` |
| Average Order Value | `AVG(avg_order_value)` | `customer_snapshots` |
| Customer Tenure | `AVG(days_since_join)` | `customer_snapshots` |
| Loyalty Points Balance | `AVG(loyalty_points)` | `customer_snapshots` |
| Value Tier Distribution | `COUNT(*) GROUP BY value_tier` | `customer_snapshots` |
| Churn Risk Score | `AVG(churn_risk_score)` | `customer_snapshots` |

---

### 6. Return Rate

**Computation:**

```sql
-- From order metrics (simulation data)
SELECT COUNT(CASE WHEN returned THEN 1 END) * 100.0 / COUNT(*) FROM order_metrics;

-- From returns table (transactional)
SELECT COUNT(*) FROM returns;
```

**Composite Drivers:**

| Driver | Formula | Source Table |
|--------|---------|-------------|
| Returns by Channel | `COUNT(WHERE returned) GROUP BY channel` | `order_metrics` |
| Return Reason Distribution | `COUNT(*) GROUP BY reason` | `returns` |
| Refund Amount | `SUM(refund_amount)` | `returns` |

---

### 7. Inventory Health (Composite)

An aggregate view of whether the supply chain can meet demand.

**Composite Drivers:**

| Driver | Formula | Source Table |
|--------|---------|-------------|
| Fill Rate | `1 - (stockout_events / total_demand_events)` | `inventory_events` |
| Total Stockouts | `COUNT(WHERE stockout_occurred = TRUE)` | `inventory_events` |
| Avg Days of Supply | `AVG(quantity_on_hand / daily_demand)` | `inventory_snapshots` |
| Items Below Reorder Point | `COUNT(WHERE quantity_on_hand <= reorder_point)` | `inventory` |
| On-Order Coverage | `SUM(on_order_qty)` | `inventory` |
| Shrinkage Rate | `SUM(quantity_change WHERE event_type = 'shrinkage') / total_stock` | `inventory_events` |

---

### 8. Fulfillment Performance (Composite)

**Composite Drivers:**

| Driver | Formula | Source Table |
|--------|---------|-------------|
| On-Time Delivery % | `COUNT(WHERE on_time) / COUNT(*)` | `order_metrics` |
| Avg Fulfillment Duration | `AVG(fulfillment_duration)` | `order_metrics` |
| Late Orders | `COUNT(WHERE on_time = FALSE)` | `order_metrics` |
| Fulfillment by Channel | `AVG(fulfillment_duration) GROUP BY channel` | `order_metrics` |
| Payment Success Rate | `COUNT(WHERE status = 'completed') / COUNT(*)` | `payments` |

---

## Omnichannel Purchase Workflow Metrics

These metrics describe the customer shopping journey from arrival to fulfillment. Primary source tables: `customer_journeys`, `order_metrics`, `hourly_demand`, `orders`, `order_items`, `payments`.

### Traffic & Demand

| Metric | Formula | Source | Drivers |
|--------|---------|--------|---------|
| **Arrival Rate** | `COUNT(*) / simulation_hours` | `customer_journeys` | Arrival rate by channel; time-of-day multipliers from config |
| **Hourly Arrival Count** | `arrival_count` | `hourly_demand` | Channel mix, hour of day, day of week |
| **Hourly Order Count** | `order_count` | `hourly_demand` | Arrivals × conversion rate per hour |
| **Hourly Revenue** | `revenue` | `hourly_demand` | Order count × AOV per hour |
| **Hourly Abandonment Count** | `abandonment_count` | `hourly_demand` | Peaks during high-traffic hours when queues are long |
| **Avg Basket Size by Hour** | `avg_basket_size` | `hourly_demand` | Varies with time-of-day shopping patterns |

### Conversion Funnel

| Metric | Formula | Source | Drivers |
|--------|---------|--------|---------|
| **Conversion Rate** | `completed / total_journeys` | `customer_journeys` | Abandonment rate, payment failures, queue wait |
| **Conversion by Channel** | `completed / total per channel` | `customer_journeys` | Online has highest abandonment; in-store has queue balking |
| **Cart Abandonment Rate** | `abandoned / total_journeys` | `customer_journeys` | `abandonment_reason` breakdown: price, queue, browsing fatigue |
| **Payment Failure Rate** | `payment_failed / total_journeys` | `customer_journeys` | Payment method distribution, gateway reliability |
| **Queue Balk Rate** | `balked / in_store_arrivals` | `customer_journeys` | Queue depth vs `queue_balk_threshold` (config) |

### Journey Timing

| Metric | Formula | Source | Drivers |
|--------|---------|--------|---------|
| **Avg Browsing Duration** | `AVG(browsing_duration)` | `customer_journeys` | Triangular distribution params: browsing_time_min/mode/max |
| **Avg Queue Wait Time** | `AVG(queue_wait_time)` | `customer_journeys` | `checkout_counters_per_store` (resource capacity), arrival rate |
| **Max Queue Wait Time** | `MAX(queue_wait_time)` | `customer_journeys` | Peaks during high-traffic hours |
| **Avg Checkout Time** | `AVG(checkout_time)` | `customer_journeys` | Service time distribution: checkout_min/mode/max |
| **Avg Total Journey Time** | `AVG(total_journey_time)` | `customer_journeys` | Sum of browse + queue + checkout + fulfillment |

### Order & Revenue

| Metric | Formula | Source | Drivers |
|--------|---------|--------|---------|
| **Total Orders** | `COUNT(*)` | `order_metrics` | Traffic × conversion |
| **Total Revenue** | `SUM(total_amount) WHERE completed` | `customer_journeys` | Orders × AOV |
| **AOV** | `AVG(total_amount) WHERE completed` | `customer_journeys` | Basket size × unit price |
| **Revenue by Channel** | `SUM(total_amount) GROUP BY channel` | `customer_journeys` | Channel-specific traffic and AOV |
| **Payment Method Distribution** | `COUNT(*) GROUP BY payment_method` | `payments` | credit_card, debit_card, paypal shares |

### Fulfillment

| Metric | Formula | Source | Drivers |
|--------|---------|--------|---------|
| **On-Time Delivery %** | `COUNT(WHERE on_time) / COUNT(*)` | `order_metrics` | Fulfillment duration vs SLA (`delivery_sla_days`) |
| **Avg Fulfillment Duration** | `AVG(fulfillment_duration)` | `order_metrics` | Picker/packer capacity, packing time distribution |
| **Fulfillment by Channel** | `AVG(fulfillment_duration) GROUP BY channel` | `order_metrics` | BOPIS is fastest; online depends on warehouse capacity |
| **Return Rate** | `COUNT(WHERE returned) / COUNT(*)` | `order_metrics` | Category-specific return rates from config |

---

## Inventory Replenishment Workflow Metrics

These metrics describe supply chain health. Primary source tables: `inventory_events`, `supplier_deliveries`, `inventory_snapshots`, `inventory`, `purchase_orders`, `purchase_order_lines`, `replenishment_policy`.

### Stock Levels

| Metric | Formula | Source | Drivers |
|--------|---------|--------|---------|
| **Total Quantity on Hand** | `SUM(quantity_on_hand)` | `inventory` | Demand depletion rate vs replenishment rate |
| **Quantity by Location** | `SUM(quantity_on_hand) GROUP BY location_id` | `inventory` | Demand variance across stores/warehouse |
| **Items Below Reorder Point** | `COUNT(WHERE quantity_on_hand <= reorder_point)` | `inventory` | Demand spikes, slow supplier deliveries |
| **Reserved Inventory** | `SUM(quantity_reserved)` | `inventory` | Open orders awaiting fulfillment |
| **On-Order Inventory** | `SUM(on_order_qty)` | `inventory` | POs placed but not yet received |
| **Days of Supply** | `quantity_on_hand / daily_demand` | `inventory_snapshots` | Low values signal upcoming stockout risk |

### Stockouts

| Metric | Formula | Source | Drivers |
|--------|---------|--------|---------|
| **Stockout Count** | `COUNT(WHERE stockout_occurred = TRUE)` | `inventory_events` | Demand exceeding available stock |
| **Stockout Rate** | `stockout_events / total_demand_events` | `inventory_events` | Reorder point too low, lead time too long, demand spike |
| **Stockout Duration** | `SUM(stockout_hours)` | `inventory_snapshots` | Time from depletion to replenishment receipt |
| **Stockout by SKU** | `COUNT(*) GROUP BY sku WHERE stockout_occurred` | `inventory_events` | Identifies chronic problem items |
| **Stockout by Location** | `COUNT(*) GROUP BY location WHERE stockout_occurred` | `inventory_events` | Identifies underserved locations |
| **Fill Rate** | `1 - (stockout_events / demand_events)` | `inventory_events` | Composite of reorder policy, lead time, demand variability |

**Stockout Composite Drivers (SimPy breakdown):**

The simulation models stockouts as the result of several interacting processes:

1. **Demand rate** — `daily_demand` from `inventory_snapshots` determines consumption velocity
2. **Reorder point** — `reorder_point` from `replenishment_policy`; if set too low, POs trigger too late
3. **Safety stock** — `safety_stock` from `replenishment_policy`; buffer against demand variability
4. **Lead time** — `actual_lead_time_days` from `supplier_deliveries`; longer lead time = higher stockout risk
5. **Supplier reliability** — `on_time` flag and `short_shipped` flag from `supplier_deliveries`
6. **Shrinkage** — `event_type = 'shrinkage'` events from `inventory_events` erode stock silently

### Supplier Performance

| Metric | Formula | Source | Drivers |
|--------|---------|--------|---------|
| **On-Time Delivery %** | `COUNT(WHERE on_time) / COUNT(*)` | `supplier_deliveries` | Supplier reliability parameter, lead time variability |
| **Avg Actual Lead Time** | `AVG(actual_lead_time_days)` | `supplier_deliveries` | `mean_lead_time_days` per supplier + stochastic variation |
| **Lead Time Variance** | `STDDEV(actual_lead_time_days)` | `supplier_deliveries` | Higher variance = less predictable replenishment |
| **Lead Time Accuracy** | `AVG(actual_lead_time_days - expected_lead_time_days)` | `supplier_deliveries` | Positive = late; negative = early |
| **Short Shipment Rate** | `COUNT(WHERE short_shipped) / COUNT(*)` | `supplier_deliveries` | `short_shipment_probability` from config |
| **Received vs Ordered** | `SUM(received_quantity) / SUM(order_quantity)` | `supplier_deliveries` | Quantity fill rate from suppliers |
| **Supplier Performance by ID** | All above metrics `GROUP BY supplier_id` | `supplier_deliveries` | Identifies best/worst suppliers |

### Replenishment Efficiency

| Metric | Formula | Source | Drivers |
|--------|---------|--------|---------|
| **Total POs Issued** | `COUNT(*)` | `purchase_orders` | Reorder frequency driven by demand and reorder point |
| **PO Status Distribution** | `COUNT(*) GROUP BY status` | `purchase_orders` | PENDING vs RECEIVED completion rate |
| **Avg Order Quantity** | `AVG(order_qty)` | `purchase_order_lines` | Economic order quantity from `replenishment_policy` |
| **Reorder Trigger Rate** | `COUNT(WHERE reorder_triggered) / COUNT(*)` | `inventory_snapshots` | How often stock hits reorder point |
| **Inventory Turnover** | `SUM(daily_demand) * 365 / AVG(quantity_on_hand)` | `inventory_snapshots` | Higher turnover = more efficient use of inventory investment |
| **Shrinkage Rate** | `SUM(ABS(quantity_change) WHERE event_type='shrinkage') / total_stock` | `inventory_events` | `daily_shrinkage_rate` from config |

---

## Customer Engagement Workflow Metrics

These metrics describe CRM, loyalty, and retention performance. Primary source tables: `customer_snapshots`, `campaign_interactions`, `engagement_events`, `loyalty_account`, `points_transactions`, `support_tickets`, `customer_scores`.

### Customer Lifecycle

| Metric | Formula | Source | Drivers |
|--------|---------|--------|---------|
| **Active Customer Rate** | `COUNT(WHERE activity_state = 'active') / COUNT(*)` | `customer_snapshots` | Purchase recency vs `active_threshold_days` |
| **Lapsed Customer Rate** | `COUNT(WHERE activity_state = 'lapsed') / COUNT(*)` | `customer_snapshots` | Time since last purchase exceeds active threshold |
| **Churn Rate** | `COUNT(WHERE churned = TRUE) / COUNT(*)` | `customer_snapshots` | Combined effect of engagement decay and unresponsiveness |
| **Retention Rate** | `1 - churn_rate` | `customer_snapshots` | Inverse of churn |
| **Avg Churn Risk Score** | `AVG(churn_risk_score)` | `customer_snapshots` | Weighted sum of recency, spend decline, unresponsive count |
| **Lifecycle State Transitions** | `COUNT(*) GROUP BY activity_state` across snapshots | `customer_snapshots` | Movement between New → Active → Lapsed → Churned |

**Churn Composite Drivers (SimPy breakdown):**

The engagement simulation computes `churn_risk_score` as an accumulating score influenced by:

1. **Days since last purchase** — `days_since_last_purchase` in `customer_snapshots`; primary decay signal
2. **Unresponsive count** — `unresponsive_count`; campaigns sent with no response increase risk
3. **Total spend decline** — Customers whose `total_spend` stagnates relative to tenure
4. **Campaign fatigue** — Repeated sends without engagement (`days_since_last_engagement` in `campaign_interactions`)
5. **Service issues** — Unresolved or poorly-rated support tickets push risk up
6. **Loyalty disengagement** — Low or zero `loyalty_points` relative to tenure

### Customer Segmentation

| Metric | Formula | Source | Drivers |
|--------|---------|--------|---------|
| **Value Tier Distribution** | `COUNT(*) GROUP BY value_tier` | `customer_snapshots` | VIP / High / Medium / Low based on spend thresholds |
| **RFM Segment Distribution** | `COUNT(*) GROUP BY rfm_segment` | `customer_snapshots` | Champions, Loyal, Potential, At-Risk, etc. |
| **Avg Spend by Tier** | `AVG(total_spend) GROUP BY value_tier` | `customer_snapshots` | Validates tier thresholds |
| **Avg Purchase Count by Segment** | `AVG(purchase_count) GROUP BY rfm_segment` | `customer_snapshots` | Frequency differences between segments |

### Campaign Performance

| Metric | Formula | Source | Drivers |
|--------|---------|--------|---------|
| **Open Rate** | `COUNT(WHERE opened) / COUNT(*)` | `campaign_interactions` | Campaign type, customer segment, send timing |
| **Click-Through Rate (CTR)** | `COUNT(WHERE clicked) / COUNT(*)` | `campaign_interactions` | Content relevance, offer strength, segment targeting |
| **Conversion Rate** | `COUNT(WHERE converted) / COUNT(*)` | `campaign_interactions` | Full-funnel effectiveness |
| **Click-to-Open Rate** | `COUNT(WHERE clicked) / COUNT(WHERE opened)` | `campaign_interactions` | Content quality independent of subject line |
| **Response by Campaign Type** | All rates `GROUP BY campaign_type` | `campaign_interactions` | Email vs SMS vs push performance |
| **Response by Segment** | All rates `GROUP BY value_tier, rfm_segment` | `campaign_interactions` | VIPs respond differently than at-risk customers |
| **Campaign Fatigue** | `AVG(unresponsive_count)` and trend over time | `campaign_interactions` | Rising unresponsive counts signal over-messaging |

**Campaign Response Composite Drivers (SimPy breakdown):**

Response probabilities in the simulation are computed from:

1. **Base response rate** — `base_email_response_rate` from config, varies by campaign type
2. **Value tier boost** — VIP and High-value customers get `vip_response_boost` / `high_response_boost`
3. **RFM segment** — Champions respond at higher rates than At-Risk segments
4. **Fatigue decay** — `unresponsive_count` degrades response probability over consecutive non-responses
5. **Days since last engagement** — Recent engagement increases likelihood of response

### Loyalty Program

| Metric | Formula | Source | Drivers |
|--------|---------|--------|---------|
| **Enrollment Rate** | `COUNT(*) in loyalty_account / COUNT(*) in customers` | `loyalty_account`, `customers` | Proportion of customers in loyalty program |
| **Avg Points Balance** | `AVG(current_points)` | `loyalty_account` | Accrual rate vs redemption rate |
| **Lifetime Points Earned** | `SUM(lifetime_points)` | `loyalty_account` | `points_per_dollar` × total spend |
| **Points Issued** | `SUM(points_change) WHERE points_change > 0` | `points_transactions` | Purchase-driven accrual + bonus promotions |
| **Points Redeemed** | `SUM(ABS(points_change)) WHERE points_change < 0` | `points_transactions` | Redemption threshold and customer awareness |
| **Redemption Rate** | `redeemed / issued` | `points_transactions` | Higher redemption = more engaged loyalty members |
| **Tier Distribution** | `COUNT(*) GROUP BY tier` | `loyalty_account` | Standard, Silver, Gold, Platinum distribution |
| **Transaction Reasons** | `COUNT(*) GROUP BY reason` | `points_transactions` | Purchase earn, redemption, bonus, promo breakdown |

### Service & Support

| Metric | Formula | Source | Drivers |
|--------|---------|--------|---------|
| **Total Tickets** | `COUNT(*)` | `support_tickets` | `service_issue_probability` from config |
| **Open Tickets** | `COUNT(WHERE status = 'open')` | `support_tickets` | Resolution capacity vs creation rate |
| **Resolution Rate** | `COUNT(WHERE status = 'resolved') / COUNT(*)` | `support_tickets` | Staff efficiency, issue complexity |
| **Avg Resolution Time** | `AVG(resolved_at - created_at)` | `support_tickets` | `resolution_time_min/max` from config |
| **Avg Satisfaction Rating** | `AVG(satisfaction_rating)` | `support_tickets` | Resolution speed, issue type, customer expectations |
| **Tickets by Issue Type** | `COUNT(*) GROUP BY issue_type` | `support_tickets` | Identifies systemic problems |
| **Satisfaction by Issue Type** | `AVG(satisfaction_rating) GROUP BY issue_type` | `support_tickets` | Some issue types consistently produce lower satisfaction |

---

## ML Model Metrics

The ML pipeline trains 9 models on simulation data. Each model produces evaluation metrics during training (5-fold cross-validation) and feature importance scores that indicate which simulation parameters most influence predictions.

### Classification Models

These models predict binary outcomes. Evaluation metrics:

| Metric | Description |
|--------|-------------|
| **AUC-ROC** | Area under the receiver operating characteristic curve. Primary evaluation metric. Higher = better separation between classes. |
| **Accuracy** | Fraction of correct predictions. Can be misleading with imbalanced classes. |
| **Precision** | Of predicted positives, how many are actually positive. Important when false positives are costly. |
| **Recall** | Of actual positives, how many were predicted. Important when false negatives are costly (e.g., missing churn). |
| **F1 Score** | Harmonic mean of precision and recall. Balances both error types. |

**Classification Models and Their Business Context:**

| Model | Target | AUC Interpretation | Key Features (by importance) |
|-------|--------|-------------------|------------------------------|
| **Conversion** | `completed` | Higher AUC = better ability to predict which customers will purchase | browsing_duration, basket_size, queue_wait_time, channel, arrival_hour |
| **Stockout** | `stockout_occurred` | Higher AUC = better early warning for stockouts | quantity_before, reorder_point, safety_stock, on_order_qty |
| **Churn** | `churned` | Higher AUC = better identification of at-risk customers | days_since_last_purchase, unresponsive_count, total_spend, churn_risk_score |
| **Campaign Response** | `clicked` | Higher AUC = better targeting of receptive customers | campaign_type, value_tier, rfm_segment, days_since_last_engagement |

### Regression Models

These models predict continuous values. Evaluation metrics:

| Metric | Description |
|--------|-------------|
| **MAE** | Mean Absolute Error. Average magnitude of prediction errors in original units. |
| **RMSE** | Root Mean Squared Error. Penalizes large errors more than MAE. |
| **R²** | Coefficient of determination. Fraction of variance explained by the model (1.0 = perfect). |
| **MAPE** | Mean Absolute Percentage Error. Scale-independent error measure. |

**Regression Models and Their Business Context:**

| Model | Target | Unit | Key Features (by importance) |
|-------|--------|------|------------------------------|
| **Order Value** | `total_amount` | Dollars | basket_size, channel, browsing_duration, arrival_hour |
| **Fulfillment** | `fulfillment_duration` | Hours | channel, order_hour, day_of_week |
| **Lead Time** | `actual_lead_time_days` | Days | supplier_id, order_quantity, expected_lead_time_days |
| **CLV** | `total_spend` | Dollars | purchase_count, days_since_join, avg_order_value, loyalty_points |

### Time Series Model

| Model | Target | Method | Metrics |
|-------|--------|--------|---------|
| **Demand Forecast** | Hourly order count | Prophet | MAE, RMSE, MAPE on holdout period |

Prophet decomposes demand into trend, weekly seasonality, and daily seasonality components. The model captures hour-of-day peaks and day-of-week patterns observed in `hourly_demand`.

### Feature Importance as Metric Drivers

Feature importance scores from trained models serve as a quantitative decomposition of what drives each predicted outcome. After training, `model.get_feature_importance()` returns a dictionary of feature → score. Higher scores indicate stronger influence.

This connects back to composite drivers: if the conversion model shows `queue_wait_time` has high importance, that validates queue management as a lever for improving conversion. Similarly, if the stockout model shows `reorder_point` dominates, that confirms reorder policy is the primary control for preventing stockouts.

---

## Scenario-Level Aggregate Metrics

The `simulation_scenarios` table stores pre-computed KPIs for each parameter sweep scenario, enabling scenario comparison without re-querying detail tables.

| Column | Type | Description |
|--------|------|-------------|
| `total_customers` | INTEGER | Total customer arrivals in the scenario |
| `total_orders` | INTEGER | Completed orders |
| `total_revenue` | DOUBLE | Sum of order values |
| `conversion_rate` | DOUBLE | Orders / customers (%) |
| `stockout_count` | INTEGER | Total stockout events |
| `fill_rate` | DOUBLE | Demand fill rate (0-1) |
| `avg_lead_time` | DOUBLE | Mean supplier lead time (days) |
| `churn_rate` | DOUBLE | Fraction of customers who churned (0-1) |
| `campaign_response_rate` | DOUBLE | Campaign click-through rate (0-1) |
| `avg_clv` | DOUBLE | Average customer lifetime value |

These are the same metrics described above, pre-aggregated per scenario. Use them for sweep comparison, scoring, and recommendation generation.

---

## Cross-Workflow Metric Relationships

The three workflows interact, creating cross-cutting metric dependencies:

```
                    Omnichannel Purchase
                   /                    \
         orders drive                    orders drive
        demand depletion               purchase history
              |                              |
    Inventory Replenishment        Customer Engagement
         stockouts reduce               churn reduces
         conversion rate              future order volume
              \                              /
               \____________________________/
                  Both impact total revenue
```

| Upstream Metric | Downstream Impact | Mechanism |
|----------------|-------------------|-----------|
| Conversion Rate (omnichannel) | Demand Rate (inventory) | Higher conversion = more units sold = faster stock depletion |
| Stockout Rate (inventory) | Lost Sales (omnichannel) | Out-of-stock items cannot be purchased |
| Fulfillment Duration (omnichannel) | Customer Satisfaction (engagement) | Slow fulfillment increases churn risk |
| Churn Rate (engagement) | Traffic (omnichannel) | Churned customers stop arriving |
| Campaign Conversion (engagement) | Order Volume (omnichannel) | Successful campaigns drive incremental purchases |
| Lead Time (inventory) | Fulfillment SLA (omnichannel) | Slow replenishment delays BOPIS and online orders |
