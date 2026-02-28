# Simulation Workflows

A discrete-event simulation framework for retail operations, built with SimPy. Simulates three interconnected business workflows and provides ML models trained on simulation data for predictive analytics.

## Overview

This project simulates retail operations across three domains:

1. **Omnichannel Purchase** - Customer journeys from arrival to checkout across online, in-store, and BOPIS channels
2. **Inventory Replenishment** - Supply chain operations including demand depletion, reorder triggers, and supplier deliveries
3. **Customer Engagement** - CRM lifecycle including segmentation, campaigns, loyalty programs, and churn prevention

The simulation generates realistic operational data that can be used to train ML models for predictions like conversion probability, stockout risk, and customer churn.

## Conceptual Flow

The project follows a closed-loop workflow for tuning simulation assumptions:

1. **Model** — Define workflows (omnichannel, inventory, engagement) with discrete-event simulation logic
2. **Configure** — All assumptions live centrally in `config.py` dataclasses (zero hardcoded values in workflow files), cleanly organized per workflow
3. **Sweep** — Systematically vary those assumptions across parameter grids to find which produce the richest, most realistic data
4. **Recommend + Apply** — Score sweep results by volume, variety, and KPI realism; generate recommendations; and write them back to `config_overrides.json` so future runs use tuned values

This loop is extensible: if a workflow model changes and introduces new assumptions, you add the fields to the relevant config dataclass, reference them in the workflow, optionally add them to a sweep config, and the same sweep → recommend → apply pipeline handles the rest.

## Architecture

```
simulation/
├── shared/                 # Shared infrastructure
│   ├── config.py           # SimulationConfig with all parameters
│   ├── resources.py        # SimPy resources (queues, inventory)
│   ├── persistence.py      # Database connections (DuckDB, Cosmos, Postgres)
│   ├── metrics.py          # MetricsCollector for KPI tracking
│   └── local_backend.py    # DuckDB schema definitions
├── workflows/              # Business process simulations
│   ├── omnichannel_purchase.py
│   ├── inventory_replenishment.py
│   └── customer_engagement.py
├── sweep/                  # Parameter sweep framework
│   ├── config_generator.py # Sweep parameter definitions
│   ├── sweep_runner.py     # Multi-scenario execution
│   └── scenario_tracker.py # Results persistence
└── ml/                     # ML model training pipeline
    ├── data_prep.py        # Dataset extraction from simulation DB
    ├── conversion_model.py # Purchase conversion classifier
    ├── value_model.py      # Order value regressor
    ├── demand_forecast.py  # Prophet time series forecasting
    ├── fulfillment_model.py# Fulfillment time regressor
    ├── stockout_model.py   # Stockout risk classifier
    ├── lead_time_model.py  # Supplier lead time regressor
    ├── churn_model.py      # Customer churn classifier
    ├── campaign_response_model.py  # Campaign click predictor
    └── clv_model.py        # Customer lifetime value regressor
```

## Workflows

### Omnichannel Purchase Workflow

Simulates customer shopping journeys with realistic behaviors:

- **Arrival processes**: Poisson arrivals for online, in-store, and BOPIS channels
- **Browsing**: Exponential browsing duration, basket building
- **Queue management**: In-store checkout queues with balking behavior
- **Cart abandonment**: Probabilistic abandonment based on channel and wait time
- **Payment processing**: Payment failures and retries
- **Fulfillment**: Order processing with SLA tracking

Key metrics: Conversion rate, average order value, queue wait times, fulfillment SLA compliance.

### Inventory Replenishment Workflow

Simulates supply chain operations:

- **Demand depletion**: Stochastic consumption from customer purchases
- **Reorder point monitoring**: Continuous review (s,Q) policy
- **Purchase order generation**: Automatic PO creation when stock hits ROP
- **Supplier simulation**: Variable lead times with reliability modeling
- **Receiving**: Goods receipt with potential short shipments
- **Shrinkage**: Daily inventory loss simulation

Key metrics: Fill rate, stockout count, average lead time, supplier on-time rate.

### Customer Engagement Workflow

Simulates CRM and loyalty operations:

- **Customer lifecycle**: State transitions (New → Active → Lapsed → Churned)
- **RFM segmentation**: Recency, Frequency, Monetary scoring
- **Campaign execution**: Scheduled and triggered marketing campaigns
- **Response simulation**: Open, click, and conversion modeling
- **Loyalty program**: Points accrual and redemption
- **Churn prevention**: Risk scoring and retention campaigns
- **Service tickets**: Issue creation and resolution impact

Key metrics: Churn rate, campaign response rate, customer lifetime value, loyalty redemption rate.

## Parameter Sweeps

The sweep framework enables systematic exploration of parameter space to generate diverse training data for ML models.

### How Sweeps Work

1. **Define parameters**: Each sweep specifies which parameters to vary and their value ranges
2. **Generate scenarios**: Grid search (all combinations) or random sampling
3. **Execute scenarios**: Each scenario runs the workflow with specific parameter values
4. **Persist results**: Scenario metadata and ML training data saved to DuckDB

### Available Sweeps

| Sweep | Workflow | Parameters | Scenarios |
|-------|----------|------------|-----------|
| `conversion` | Omnichannel | abandonment rates, payment failure | 36 |
| `demand` | Omnichannel | arrival rates, basket size | 36 |
| `fulfillment` | Omnichannel | fulfillment delays, SLA thresholds | 27 |
| `inventory_supply` | Inventory | lead times, supplier reliability | 27 |
| `inventory_policy` | Inventory | reorder points, safety stock | 27 |
| `inventory_demand` | Inventory | demand rates, shrinkage | 27 |
| `engagement_campaign` | Engagement | response rates, send frequency | 27 |
| `engagement_retention` | Engagement | churn thresholds, retention offers | 27 |
| `engagement_loyalty` | Engagement | points multipliers, redemption rates | 27 |

### Sweep Parameters Example

The `conversion` sweep varies these parameters:

```python
CONVERSION_SWEEP = SweepConfig(
    name="conversion",
    parameters=[
        SweepParameter("abandonment_rate_online", [0.15, 0.25, 0.35, 0.45]),
        SweepParameter("abandonment_rate_in_store", [0.03, 0.05, 0.08]),
        SweepParameter("payment_failure_rate", [0.01, 0.02, 0.05]),
    ],
    base_duration_hours=24,
)
```

This creates 4 × 3 × 3 = 36 unique scenarios, each running a 24-hour simulation.

## ML Pipeline

After running sweeps, the ML pipeline trains models on the generated simulation data.

### Data Flow

```
Simulation → DuckDB Tables → DataExtractor → ML Models → .joblib files
```

### Models

| Model | Type | Target | Key Features |
|-------|------|--------|--------------|
| **Conversion** | Classification | completed (bool) | channel, arrival_hour, browsing_duration, basket_size, queue_wait |
| **Order Value** | Regression | total_amount | channel, basket_size, arrival_hour |
| **Demand Forecast** | Time Series | hourly orders | hour_of_day, day_of_week (Prophet) |
| **Fulfillment** | Regression | fulfillment_duration | channel, order_hour |
| **Stockout** | Classification | stockout_occurred | quantity_before, reorder_point, safety_stock |
| **Lead Time** | Regression | actual_lead_time_days | supplier_id, order_quantity |
| **Churn** | Classification | churned (bool) | days_since_purchase, total_spend, unresponsive_count |
| **Campaign Response** | Classification | clicked (bool) | campaign_type, value_tier, rfm_segment |
| **CLV** | Regression | total_spend | days_since_join, purchase_count, loyalty_points |

### Training Process

1. **Extract data**: `DataExtractor` queries DuckDB tables for training features
2. **Preprocess**: Encode categorical variables, handle missing values
3. **Train**: Fit sklearn `GradientBoostingClassifier/Regressor` or Prophet
4. **Evaluate**: Cross-validation, compute metrics (AUC, MAE, R²)
5. **Save**: Serialize model + encoders + metrics to `.joblib`

### Using Trained Models

```python
from simulation.ml import ConversionModel
import pandas as pd

# Load trained model
model = ConversionModel()
model.load("models/conversion_latest.joblib")

# Predict on new data
features = pd.DataFrame({
    'channel': ['online'],
    'arrival_hour': [14],
    'day_of_week': [2],
    'browsing_duration': [5.5],
    'basket_size': [3],
    'queue_wait_time': [0.0],
})

probability = model.predict(features)
print(f"Conversion probability: {probability[0]:.2%}")
```

## Database Schema

The simulation uses DuckDB for local persistence. Key tables:

### Scenario Tracking
- `simulation_scenarios` - Scenario metadata, parameters, and aggregate results

### Omnichannel Data
- `customer_journeys` - Individual journey records with features and outcomes
- `order_metrics` - Order-level fulfillment data
- `hourly_demand` - Aggregated demand by hour/channel

### Inventory Data
- `inventory_events` - Stock movements and stockout events
- `supplier_deliveries` - PO fulfillment with lead time actuals
- `inventory_snapshots` - Daily inventory positions

### Engagement Data
- `customer_snapshots` - Customer state at simulation end
- `campaign_interactions` - Campaign send/response records

## Configuration

The `SimulationConfig` class in `shared/config.py` contains all tunable parameters:

```python
@dataclass
class DistributionConfig:
    # Arrival rates (customers per hour)
    arrival_rate_online: float = 20.0
    arrival_rate_in_store: float = 15.0

    # Abandonment probabilities
    abandonment_rate_online: float = 0.25
    abandonment_rate_in_store: float = 0.05

    # Basket characteristics
    basket_size_mean: float = 3.0
    basket_size_std: float = 1.5

    # ... and many more
```

## Local Development

### Prerequisites

- Python 3.11+
- uv (Python package manager)

### Getting Started

Install dependencies with `uv sync`, then seed the local DuckDB database. From there you can run individual workflows, full sweeps, or the ML training pipeline. Run `make help` to see all available commands organized by category.

## Project Structure

```
.
├── main.py                 # CLI entry point
├── Makefile                # Common commands
├── pyproject.toml          # Dependencies
├── seed-data/              # Database seeding scripts
├── simulation/             # Core simulation code
│   ├── shared/             # Infrastructure
│   ├── workflows/          # Business processes
│   ├── sweep/              # Parameter sweeps
│   └── ml/                 # ML models
├── analysis/               # Analysis scripts
│   ├── train_models.py     # Model training CLI
│   ├── sweep_report.py     # Sweep volume/variety/KPI report
│   ├── sweep_recommend.py  # Recommendation engine (scores & ranks)
│   └── config_applier.py   # Preview/apply recommendations to config
├── models/                 # Saved model files (gitignored)
└── local_postgres.duckdb   # Local database (gitignored)
```

## Sweep Reporting

After running sweeps, use the sweep report to see which parameter combinations produced the most volume and variety of data — useful for understanding which scenarios generate the richest ML training datasets.

### What the Report Shows

Each sweep gets three ranked tables:

| Section | What it ranks | Why it matters |
|---------|--------------|----------------|
| **Data Volume** | Scenarios by total rows across detail tables (customer_journeys, inventory_events, etc.) | Higher volume = more training examples for ML |
| **Data Variety** | Scenarios by distinct values (channels, outcome types, event types, segments) | Higher variety = better model generalization |
| **Primary KPI** | Scenarios by the key business metric (revenue, fill rate, CLV) | Identifies which parameter combos drive the most interesting outcomes |

### Example Output

```
================================================================================
  SWEEP DATA OVERVIEW
================================================================================
  Sweep                          Workflow        Scenarios  Completed  Last Run
  ------------------------------ -------------- ---------- ----------  -------------------
  demand                         omnichannel            36         36  2026-02-27 14:45:58
  conversion                     omnichannel            36         36  2026-02-27 12:28:14
  engagement_loyalty             engagement             27         27  2026-02-26 23:54:31
  ...

================================================================================
  SWEEP: DEMAND  (omnichannel)
================================================================================

  Detail table row counts (total: 56,050):
    customer_journeys                  53,810 rows
    order_metrics                           0 rows
    hourly_demand                       2,240 rows

  TOP 10 SCENARIOS BY DATA VOLUME:
  #    Scenario                       Total Rows   Tables  Parameters
  ---- ---------------------------- ------------ --------  ----------------------------------------
  1    demand_0033                         2,829        2  arrival_rate_online=50, arrival_rate_in_store=25, ...
  2    demand_0034                         2,785        2  arrival_rate_online=50, arrival_rate_in_store=25, ...
  ...
```

### Current Observations

Based on sweep runs to date:

- **Omnichannel sweeps** produce good customer journey volume (53K–62K rows per sweep) but `order_metrics` shows 0 rows and revenue is $0 — the order completion path is not fully wired in sweep mode
- **Inventory sweeps** show 0 rows in all detail tables (`inventory_events`, `supplier_deliveries`, `inventory_snapshots`) — `persist_ml_data` is not yet writing to those tables
- **Engagement sweeps** populate `customer_snapshots` and `campaign_interactions` but not `engagement_events`
- The **demand sweep** with `arrival_rate_online=50, arrival_rate_in_store=25` consistently produces the highest per-scenario volume (~2,800 rows)
- Variety scores are fairly uniform within a sweep — most scenarios hit all 3 channels and 24 hours; the differentiators are abandonment reason diversity and outcome type spread

## Centralized Assumptions

All simulation assumptions are defined as dataclasses in `shared/config.py` — no hardcoded values exist in workflow files. Each workflow has its own assumptions section:

| Section | Fields | Examples |
|---------|--------|----------|
| `OmnichannelAssumptions` | 21 | checkout times, payment methods, carriers, queue balk thresholds |
| `InventoryAssumptions` | 23 | reorder points, lead times, shrinkage rate, audit params |
| `EngagementAssumptions` | 60 | value tier thresholds, campaign response rates, churn risk weights, loyalty program params |

These sit alongside the existing `DistributionConfig`, `ResourceConfig`, and `SLAConfig` sections inside `SimulationConfig`. Sweeps override these values per-scenario via a generic mechanism that searches all config sections automatically.

### Config Overrides

After running the recommendation pipeline, tuned values are stored in `config_overrides.json` at the project root. This file is auto-loaded by `SimulationConfig.__post_init__`, so all subsequent simulation runs pick up the tuned values without any code changes.

```json
{
  "engagement": {
    "base_email_response_rate": 0.08,
    "points_per_dollar": 12.0
  },
  "distributions": {
    "abandonment_rate_online": 0.20
  }
}
```

## Sweep Recommendations

After running sweeps and reviewing the sweep report, use the recommendation pipeline to automatically tune assumptions.

### How It Works

1. **Score** — Each scenario is scored by a weighted composite: volume (0.3) + variety (0.3) + KPI realism (0.4)
2. **Rank** — Top scenarios per sweep are identified
3. **Analyze convergence** — For each parameter, if top scenarios agree on a value it becomes a fixed recommendation; if they span diverse values it becomes a range recommendation (for data variety)
4. **Output** — A human-readable report and `recommendations.json`

### End-to-End Flow

Run one or more sweeps, then generate recommendations from the results. Preview the proposed changes against current defaults to see exactly what would shift. When satisfied, apply the recommendations — this writes `config_overrides.json`, which is automatically loaded on subsequent simulation runs. See `make help` for the specific commands at each step.

## Key Concepts

### SimPy Environment

The simulation uses SimPy's discrete-event simulation. Time advances only when events occur:

```python
env = simpy.Environment()

def customer_process(env, customer_id):
    yield env.timeout(browsing_time)  # Wait for browsing
    yield checkout_queue.request()     # Wait for queue
    yield env.timeout(checkout_time)   # Process checkout

env.process(customer_process(env, "C001"))
env.run(until=60)  # Run for 60 time units
```

### Metrics Collection

The `MetricsCollector` tracks KPIs during simulation:

```python
metrics = MetricsCollector("my_workflow")
metrics.record_customer_arrival(customer_id, channel, env.now)
metrics.record_abandonment(customer_id, "queue_too_long")
metrics.record_purchase_complete(customer_id, order_id, env.now)

# Get aggregated metrics
summary = metrics.calculate_metrics()
print(f"Conversion rate: {summary.conversion_rate}%")
```

### Persistence

Data persists to DuckDB for ML training:

```python
# After simulation completes
metrics.persist_to_db(scenario_id, persistence_manager)

# For inventory/engagement workflows
workflow.persist_ml_data(scenario_id)
```

## Extending the Framework

### Adding a New Sweep

1. Define parameters in `sweep/config_generator.py`:
```python
MY_SWEEP = SweepConfig(
    name="my_sweep",
    parameters=[
        SweepParameter("param1", [1.0, 2.0, 3.0]),
        SweepParameter("param2", [True, False]),
    ],
    base_duration_hours=24,
)
```

2. Add to exports in `sweep/__init__.py`
3. Map to workflow in `sweep_runner.py`
4. Add Makefile target

### Adding a New Assumption

1. Add the field to the relevant dataclass in `shared/config.py` (e.g. `EngagementAssumptions`)
2. Reference it in the workflow code (e.g. `self.config.engagement.new_field`)
3. Optionally add it to a sweep config in `sweep/config_generator.py` — the generic `_apply_overrides` in `sweep_runner.py` will pick it up automatically
4. Run the sweep → recommend → apply pipeline to tune it

### Adding a New ML Model

1. Create model class in `ml/` following existing patterns
2. Add dataset extractor to `ml/data_prep.py`
3. Add training function to `analysis/train_models.py`
4. Export from `ml/__init__.py`
