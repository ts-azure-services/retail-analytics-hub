# Data Model

The simulation persists all data to local DuckDB files that mirror cloud database schemas (Azure PostgreSQL, CosmosDB). Two database files are used: `local_postgres.duckdb` for relational/transactional data and `local_cosmos.duckdb` for document-oriented event data.

## Table Lifecycle Overview

Tables come alive at different stages of the pipeline. Some are seeded with baseline data, others are created empty (schema only) and filled during simulation, and the ML training tables are only populated during sweep runs.

```
  Pipeline Stage          What Happens to Tables
 ================================================================

  make seed               Seed scripts create ALL Postgres and
  (seed_local.py)         Cosmos schemas. Core entity tables and
                          a subset of transactional tables are
                          populated with baseline data. Remaining
                          transactional/engagement tables are
                          created empty (schema only).

          |
          v

  make simulate           Simulation workflows write to the
  (run_simulation.py)     transactional and Cosmos tables that
                          were left empty at seed time.
                          ML training tables are created (schema)
                          by local_backend.py on first run.
                          Single-run mode does NOT populate
                          training tables.

          |
          v

  make sweep              Sweep runner executes many simulation
  (sweep_runner.py)       scenarios. After each scenario completes,
                          training tables are bulk-populated via
                          persist_to_db() and persist_ml_data().
                          simulation_scenarios tracks each run.

          |
          v

  make train              Training pipeline reads from training
  (train_models.py)       tables (read-only). No new tables are
                          created or written. Outputs .joblib
                          model artifacts.
```

### PostgreSQL Tables — When They Populate

```
                          seed        simulate/sweep     train
                        (baseline)    (workflow runs)    (read)
                        ----------    ---------------    ------
 CORE ENTITIES
  customers                 *
  products                  *
  suppliers                 *
  inventory                 *              U
  replenishment_policy      *

 TRANSACTIONAL
  orders                    *              I
  order_items               *              I
  payments                  -              I
  purchase_orders           -              I,U
  purchase_order_lines      -              I,U
  returns                   -              I

 CUSTOMER & ENGAGEMENT
  loyalty_account           -              I,U
  customer_preferences      -              I,U
  customer_stats            -              I,U
  customer_scores           -              I,U
  points_transactions       -              I
  support_tickets           -              I
  recommendations_cache     -              I,U
  customer_purchase_history *

 TRAINING TABLES (ML)
  simulation_scenarios                     I               R
  customer_journeys                        I               R
  order_metrics                            I               R
  hourly_demand                            I               R
  inventory_events                         I               R
  supplier_deliveries                      I               R
  inventory_snapshots                      I               R
  customer_snapshots                       I               R
  campaign_interactions                    I               R
  engagement_events                        I               R

  Legend:  * = seeded with data    - = schema only (empty)
           I = INSERT              U = UPDATE
           R = read by training pipeline
```

### CosmosDB Collections — When They Populate

```
                          seed        simulate/sweep     train
                        (baseline)    (workflow runs)    (read)
                        ----------    ---------------    ------
  Customers                 *              U
  Carts                     *              I,U
  WorkflowEvents            *              I
  FulfillmentState          -              I
  InventoryEvents           -              I
  EngagementEvents          -              I

  Legend:  * = seeded with data    - = schema only (empty)
           I = INSERT              U = UPDATE
```

### Training Tables by Workflow

Training tables are populated exclusively during sweep runs. Each workflow flushes its buffered events to Postgres after the SimPy environment completes.

```
 Omnichannel Purchase Workflow          Inventory Replenishment Workflow
 (MetricsCollector.persist_to_db)       (workflow.persist_ml_data)
 +---------------------------+          +---------------------------+
 | customer_journeys         |          | inventory_events          |
 | order_metrics             |          | supplier_deliveries       |
 | hourly_demand             |          | inventory_snapshots       |
 +---------------------------+          +---------------------------+
       |   |   |                              |   |   |
       v   v   v                              v   v   v
  Conversion  Fulfillment               Stockout  Lead Time
  Order Value Demand Forecast           Demand Forecast (inv)

 Customer Engagement Workflow           Sweep Runner
 (workflow.persist_ml_data)             (ScenarioTracker)
 +---------------------------+          +---------------------------+
 | customer_snapshots        |          | simulation_scenarios      |
 | campaign_interactions     |          +---------------------------+
 | engagement_events         |                    |
 +---------------------------+                    v
       |   |   |                         Scenario metadata and
       v   v   v                         aggregate KPIs per run
  Churn   Campaign Response
  CLV
```

---

## Seed Data (Operational Foundation)

These tables are created by the seed scripts (`seed_local.py`) before any simulation runs. They represent the baseline operational state.

### Core Entities (seeded with data)

| Table | Database | Records | Description |
|-------|----------|---------|-------------|
| `customers` | Postgres | 500 | Customer profiles (name, email, join date) |
| `products` | Postgres | 50 | Product catalog — chocolate products (name, category, price, SKU) |
| `suppliers` | Postgres | 50 | Supplier profiles (name, mean lead time, reliability, min order qty) |
| `inventory` | Postgres | 250 | Stock positions per SKU and location (50 SKUs x 5 locations) |
| `replenishment_policy` | Postgres | ~150 | Reorder rules per SKU/location (reorder point, order quantity, safety stock) |

### Transactional Tables (partially seeded)

| Table | Database | Seed State | Description |
|-------|----------|------------|-------------|
| `orders` | Postgres | 500 seed orders | Order headers (customer, date, amount, status, channel) |
| `order_items` | Postgres | ~1,500-2,500 | Line items per order (product, quantity, unit price) |
| `payments` | Postgres | empty | Payment records — populated during simulation |
| `purchase_orders` | Postgres | empty | Supplier POs — populated by inventory workflow |
| `purchase_order_lines` | Postgres | empty | PO line items — populated by inventory workflow |
| `returns` | Postgres | empty | Return records — populated by omnichannel workflow |

### Customer & Engagement Tables (mostly schema-only at seed)

| Table | Database | Seed State | Description |
|-------|----------|------------|-------------|
| `loyalty_account` | Postgres | empty | Loyalty membership — populated by engagement workflow |
| `customer_preferences` | Postgres | empty | Channel and communication preferences |
| `customer_stats` | Postgres | empty | Aggregated purchase statistics (total spend, order count, AOV) |
| `customer_scores` | Postgres | empty | RFM and engagement scores |
| `points_transactions` | Postgres | empty | Loyalty points earn/redeem history |
| `support_tickets` | Postgres | empty | Customer service tickets (issue type, status, resolution) |
| `customer_purchase_history` | Postgres | seeded | Denormalized purchase history for RFM segmentation |
| `recommendations_cache` | Postgres | empty | Cached product recommendations per customer |

### Document Collections (CosmosDB)

| Collection | Seed State | Description |
|------------|------------|-------------|
| `Customers` | 500 docs | Full customer documents (profile, contact, address, account info, tags) |
| `Carts` | 80 docs | Shopping cart state (items, channel, status) |
| `WorkflowEvents` | 50 docs | Cart and order lifecycle events |
| `FulfillmentState` | empty | Order fulfillment tracking — populated by omnichannel workflow |
| `InventoryEvents` | empty | Inventory movement events — populated by inventory workflow |
| `EngagementEvents` | empty | Engagement events — populated by engagement workflow |

---

## Simulation Data (Training Tables)

These tables are created by `local_backend.py` (`_ensure_ml_tables()`) when the simulation backend initializes. They are populated during sweep runs and store the structured features and labels used to train ML models. The term "training tables" refers to the fact that these tables feed the ML training pipeline — they are not produced by ML training itself, but rather *by* the simulation sweeps *for* training.

### Scenario Tracking

| Table | Database | Populated By | Description |
|-------|----------|-------------|-------------|
| `simulation_scenarios` | Postgres | `ScenarioTracker` in sweep_runner.py | One row per swept scenario — metadata (ID, workflow type, duration, config JSON) and aggregate KPIs (revenue, conversion rate, fill rate, churn rate, CLV) |

### Omnichannel Training Tables

Populated by `MetricsCollector.persist_to_db()` after each omnichannel scenario completes.

| Table | ML Models Served | Key Columns |
|-------|-----------------|-------------|
| `customer_journeys` | Conversion, Order Value | channel, browsing_duration, basket_size, queue_wait_time, abandoned, completed, total_amount |
| `order_metrics` | Fulfillment | channel, order_hour, fulfillment_duration, on_time |
| `hourly_demand` | Demand Forecast | hour_of_day, day_of_week, channel, order_count, revenue |

### Inventory Training Tables

Populated by `InventoryReplenishmentWorkflow.persist_ml_data()` after each inventory scenario completes.

| Table | ML Models Served | Key Columns |
|-------|-----------------|-------------|
| `inventory_events` | Stockout | sku, event_type, quantity_before/after, reorder_point, safety_stock, stockout_occurred |
| `supplier_deliveries` | Lead Time | supplier_id, order_quantity, expected/actual_lead_time_days, on_time, short_shipped |
| `inventory_snapshots` | Demand Forecast (inv) | sku, snapshot_day, quantity_on_hand, daily_demand, stockout_hours |

### Engagement Training Tables

Populated by `CustomerEngagementWorkflow.persist_ml_data()` after each engagement scenario completes.

| Table | ML Models Served | Key Columns |
|-------|-----------------|-------------|
| `customer_snapshots` | Churn, CLV | activity_state, value_tier, total_spend, days_since_last_purchase, churn_risk_score, churned |
| `campaign_interactions` | Campaign Response | campaign_type, value_tier, rfm_segment, opened, clicked, converted |
| `engagement_events` | (general engagement analysis) | customer_id, event_type, campaign_id, response, churn_risk_score |
