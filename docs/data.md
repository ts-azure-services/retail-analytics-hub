# Data Model

The simulation persists all data to local DuckDB files that mirror cloud database schemas (Azure PostgreSQL, CosmosDB). Two database files are used: `local_postgres.duckdb` for relational/transactional data and `local_cosmos.duckdb` for document-oriented event data.

## Seed Data (Operational Foundation)

These tables are created and populated by the seed scripts before any simulation runs. They represent the baseline operational state.

### Core Entities

| Table | Database | Description |
|-------|----------|-------------|
| `customers` | Postgres | Customer profiles (name, email, segment, join date) |
| `products` | Postgres | Product catalog (name, category, price, SKU) |
| `inventory` | Postgres | Current stock positions per SKU and location |
| `suppliers` | Postgres | Supplier profiles (name, lead time, reliability rating) |
| `replenishment_policy` | Postgres | Reorder rules per SKU (reorder point, order quantity, safety stock) |

### Transactional Tables

| Table | Database | Description |
|-------|----------|-------------|
| `orders` | Postgres | Order headers (customer, date, amount, status, channel, fulfillment status) |
| `order_items` | Postgres | Line items per order (product, quantity, unit price) |
| `payments` | Postgres | Payment records (order, amount, method, status) |
| `purchase_orders` | Postgres | Supplier purchase orders (supplier, status, dates) |
| `purchase_order_lines` | Postgres | PO line items (SKU, quantity ordered/received) |
| `returns` | Postgres | Return records (order, reason, refund amount) |

### Customer & Engagement Tables

| Table | Database | Description |
|-------|----------|-------------|
| `loyalty_account` | Postgres | Loyalty program membership (points balance, tier) |
| `customer_preferences` | Postgres | Channel and communication preferences |
| `customer_stats` | Postgres | Aggregated purchase statistics (total spend, order count, AOV) |
| `customer_scores` | Postgres | RFM and engagement scores |
| `points_transactions` | Postgres | Loyalty points earn/redeem history |
| `support_tickets` | Postgres | Customer service tickets (issue type, status, resolution) |
| `customer_purchase_history` | Postgres | Denormalized purchase history for fast lookups |
| `recommendations_cache` | Postgres | Cached product recommendations per customer |

### Document Collections (CosmosDB-style)

| Collection | Database | Description |
|------------|----------|-------------|
| `Customers` | Cosmos | Full customer documents (profile, contact, address, account info, tags) |
| `Carts` | Cosmos | Shopping cart state (items, channel, status) |
| `WorkflowEvents` | Cosmos | Cart and order lifecycle events |
| `FulfillmentState` | Cosmos | Order fulfillment tracking documents |
| `InventoryEvents` | Cosmos | Inventory movement event documents |
| `EngagementEvents` | Cosmos | Customer engagement event documents |

## Simulation Data (ML Training)

These tables are created by simulation runs and parameter sweeps. They store the structured features and labels used to train ML models.

### Scenario Tracking

| Table | Description |
|-------|-------------|
| `simulation_scenarios` | Scenario metadata: ID, workflow type, duration, config JSON, aggregate KPIs (revenue, conversion rate, fill rate, churn rate, CLV) |

### Omnichannel Tables

| Table | ML Models Served | Key Columns |
|-------|-----------------|-------------|
| `customer_journeys` | Conversion, Order Value | channel, browsing_duration, basket_size, queue_wait_time, abandoned, completed, total_amount |
| `order_metrics` | Fulfillment | channel, order_hour, fulfillment_duration, on_time |
| `hourly_demand` | Demand Forecast | hour_of_day, day_of_week, channel, order_count, revenue |

### Inventory Tables

| Table | ML Models Served | Key Columns |
|-------|-----------------|-------------|
| `inventory_events` | Stockout | sku, event_type, quantity_before/after, reorder_point, safety_stock, stockout_occurred |
| `supplier_deliveries` | Lead Time | supplier_id, order_quantity, expected/actual_lead_time_days, on_time, short_shipped |
| `inventory_snapshots` | Demand Forecast | sku, snapshot_day, quantity_on_hand, daily_demand, stockout_hours |

### Engagement Tables

| Table | ML Models Served | Key Columns |
|-------|-----------------|-------------|
| `customer_snapshots` | Churn, CLV | activity_state, value_tier, total_spend, days_since_last_purchase, churn_risk_score, churned |
| `campaign_interactions` | Campaign Response | campaign_type, value_tier, rfm_segment, opened, clicked, converted |
| `engagement_events` | (general engagement analysis) | customer_id, event_type, campaign_id, response, churn_risk_score |
