# Retail Workflows

A discrete-event simulation framework for retail operations, built with SimPy. Simulates three interconnected business workflows (omnichannel purchase, inventory replenishment, customer engagement) and provides a parameter sweep pipeline that tunes simulation assumptions to generate diverse, realistic data for ML model training.

## Repo Structure

```
simulation/
├── shared/                            # Shared infrastructure
│   ├── config.py                      # SimulationConfig with all parameters
│   ├── resources.py                   # SimPy resources (queues, inventory)
│   ├── persistence.py                 # Database connections (DuckDB, Cosmos, Postgres)
│   ├── metrics.py                     # MetricsCollector for KPI tracking
│   └── local_backend.py              # DuckDB schema definitions
├── workflows/                         # Business process simulations
│   ├── omnichannel_purchase.py
│   ├── inventory_replenishment.py
│   └── customer_engagement.py
├── sweep/                             # Parameter sweep framework
│   ├── config_generator.py            # Sweep parameter definitions
│   ├── sweep_runner.py                # Multi-scenario execution
│   └── scenario_tracker.py            # Results persistence
├── ml/                                # ML model training pipeline
│   ├── data_prep.py                   # Dataset extraction from simulation DB
│   ├── conversion_model.py            # Purchase conversion classifier
│   ├── value_model.py                 # Order value regressor
│   ├── demand_forecast.py             # Prophet time series forecasting
│   ├── fulfillment_model.py           # Fulfillment time regressor
│   ├── stockout_model.py              # Stockout risk classifier
│   ├── lead_time_model.py             # Supplier lead time regressor
│   ├── churn_model.py                 # Customer churn classifier
│   ├── campaign_response_model.py     # Campaign click predictor
│   └── clv_model.py                   # Customer lifetime value regressor
└── run_simulation.py                  # CLI entry point
analysis/                              # Post-simulation analysis & training
├── sweep_report.py                    # Sweep volume/variety reporting
├── sweep_recommend.py                 # Recommendation generation
├── config_applier.py                  # Apply recommendations to config
└── train_models.py                    # ML model training orchestrator
seed-data/                             # Database seeding & utilities
├── seed_local.py                      # Local DuckDB seeding
├── seed_cosmos.py                     # CosmosDB seeding
├── seed_postgres.py                   # PostgreSQL seeding
├── merge_sweeps.py                    # Consolidate sweep results
├── validate_data.py                   # Data validation
├── cleanup_cosmos.py                  # CosmosDB cleanup
└── cleanup_postgres.py                # PostgreSQL cleanup
docs/                                  # Documentation
├── workflows.md                       # Workflow details
├── concepts.md                        # Architecture & key concepts
├── sweeps.md                          # Parameter sweep framework
├── ml.md                              # ML pipeline
└── data.md                            # Data model & schema reference
Makefile                               # All commands (make help)
```
