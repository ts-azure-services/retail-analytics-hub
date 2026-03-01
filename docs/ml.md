# ML Pipeline

After running sweeps, the ML pipeline trains predictive models on the generated simulation data. Models are trained with scikit-learn (gradient boosting) or Prophet (time series) and serialized to `.joblib` files.

## Data Flow

```
Simulation runs → DuckDB tables → DataExtractor → Feature engineering → Model training → .joblib artifacts
```

`DataExtractor` in `ml/data_prep.py` queries the relevant DuckDB tables for each model, joining scenario metadata with detail records to build training datasets.

## Models

| Model | Type | Target Variable | Key Features |
|-------|------|----------------|--------------|
| **Conversion** | Classification | `completed` (bool) | channel, arrival_hour, browsing_duration, basket_size, queue_wait |
| **Order Value** | Regression | `total_amount` | channel, basket_size, arrival_hour |
| **Demand Forecast** | Time Series | hourly order count | hour_of_day, day_of_week (Prophet) |
| **Fulfillment** | Regression | `fulfillment_duration` | channel, order_hour |
| **Stockout** | Classification | `stockout_occurred` | quantity_before, reorder_point, safety_stock |
| **Lead Time** | Regression | `actual_lead_time_days` | supplier_id, order_quantity |
| **Churn** | Classification | `churned` (bool) | days_since_purchase, total_spend, unresponsive_count |
| **Campaign Response** | Classification | `clicked` (bool) | campaign_type, value_tier, rfm_segment |
| **CLV** | Regression | `total_spend` | days_since_join, purchase_count, loyalty_points |

## Training Process

1. **Extract** — `DataExtractor` queries DuckDB tables for training features, filtering by scenario IDs
2. **Preprocess** — Encode categorical variables, handle missing values, apply feature transformations
3. **Train** — Fit `GradientBoostingClassifier` or `GradientBoostingRegressor` (Prophet for demand forecasting)
4. **Evaluate** — Cross-validation with metrics: AUC for classifiers, MAE/R² for regressors
5. **Serialize** — Save model + label encoders + evaluation metrics to a `.joblib` bundle

Training is orchestrated by `analysis/train_models.py`, which supports training all models at once or filtering by model group (omnichannel, inventory, engagement).

## Adding a New Model

1. Create a model class in `simulation/ml/` following the existing pattern (inherit from a base, implement `extract_data`, `train`, `predict`)
2. Add a dataset extraction query to `ml/data_prep.py`
3. Register the training function in `analysis/train_models.py`
4. Export from `ml/__init__.py`
