# Simulation Workflows

A discrete-event simulation framework for retail operations, built with SimPy. Simulates three interconnected business workflows and provides ML models trained on simulation data for predictive analytics.

## Overview

This project simulates retail operations across three domains:

1. **Omnichannel Purchase** - Customer journeys from arrival to checkout across online, in-store, and BOPIS channels
2. **Inventory Replenishment** - Supply chain operations including demand depletion, reorder triggers, and supplier deliveries
3. **Customer Engagement** - CRM lifecycle including segmentation, campaigns, loyalty programs, and churn prevention

The simulation generates realistic operational data that can be used to train ML models for predictions like conversion probability, stockout risk, and customer churn.

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

### Setup

```bash
# Install dependencies
uv sync

# Seed local DuckDB databases
make seed-local

# Run a quick test simulation
make run-simulation-quick
```

### Running Simulations

```bash
# Run individual workflows
make run-omnichannel HOURS=2
make run-inventory-workflow HOURS=2
make run-engagement-workflow HOURS=2

# Run all workflows together
make run-all-workflows HOURS=1
```

### Running Sweeps

```bash
# Run a parameter sweep (generates ML training data)
make run-sweep-conversion

# See all available sweep commands
make help
```

### Training Models

```bash
# Train all models
make train-models

# Train models for specific workflow
make train-models-omnichannel
make train-models-inventory
make train-models-engagement
```

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
│   └── train_models.py     # Model training CLI
├── models/                 # Saved model files (gitignored)
└── local_postgres.duckdb   # Local database (gitignored)
```

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

### Adding a New ML Model

1. Create model class in `ml/` following existing patterns
2. Add dataset extractor to `ml/data_prep.py`
3. Add training function to `analysis/train_models.py`
4. Export from `ml/__init__.py`
