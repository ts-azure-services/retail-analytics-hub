# Parameter Sweeps

The sweep framework systematically explores parameter space to generate diverse training data for ML models and to identify which simulation assumptions produce the most realistic outputs.

## How Sweeps Work

1. **Define parameters** — Each sweep specifies which config fields to vary and their candidate values
2. **Generate scenarios** — Grid search (all combinations) or random sampling produces a set of scenario configs
3. **Execute scenarios** — Each scenario runs the target workflow with its specific parameter overrides, using an isolated copy of the database
4. **Persist results** — Scenario metadata and ML training data are saved to DuckDB

Each sweep runs against an isolated database copy, so sweeps can execute in parallel without interference.

## Available Sweeps

| Sweep | Workflow | Parameters Varied | Scenarios |
|-------|----------|-------------------|-----------|
| `conversion` | Omnichannel | abandonment rates, payment failure rate | 36 |
| `demand` | Omnichannel | arrival rates, basket size | 36 |
| `fulfillment` | Omnichannel | fulfillment delays, SLA thresholds | 27 |
| `inventory_supply` | Inventory | lead times, supplier reliability | 27 |
| `inventory_policy` | Inventory | reorder points, safety stock levels | 27 |
| `inventory_demand` | Inventory | demand rates, shrinkage rate | 27 |
| `engagement_campaign` | Engagement | response rates, send frequency | 27 |
| `engagement_retention` | Engagement | churn thresholds, retention offer params | 27 |
| `engagement_loyalty` | Engagement | points multipliers, redemption rates | 27 |

Sweep parameters are defined in `sweep/config_generator.py` as `SweepConfig` objects. Each `SweepParameter` specifies a config field name and a list of candidate values. The total scenario count is the product of all candidate list lengths.

## Centralized Assumptions

All simulation assumptions are defined as dataclasses in `shared/config.py`. Each workflow has its own assumptions section:

| Section | Fields | Examples |
|---------|--------|----------|
| `OmnichannelAssumptions` | 21 | checkout times, payment methods, carriers, queue balk thresholds |
| `InventoryAssumptions` | 23 | reorder points, lead times, shrinkage rate, audit params |
| `EngagementAssumptions` | 60 | value tier thresholds, campaign response rates, churn risk weights, loyalty program params |

These sit alongside `DistributionConfig`, `ResourceConfig`, and `SLAConfig` inside `SimulationConfig`. Sweeps override these values per-scenario via a generic mechanism that searches all config sections automatically.

## Recommendations

After running sweeps, the recommendation pipeline identifies which parameter combinations produced the best results.

### Scoring

Each scenario is scored by a weighted composite:
- **Volume (0.3)** — Total rows across detail tables (more data = more training examples)
- **Variety (0.3)** — Distinct values across categorical dimensions (channels, outcome types, segments)
- **KPI Realism (0.4)** — How closely the scenario's key business metric (revenue, fill rate, CLV) matches realistic targets

### Convergence Analysis

For each parameter, the pipeline checks whether top-scoring scenarios agree on a value:
- **Converged** — Top scenarios cluster around a single value → fixed recommendation
- **Divergent** — Top scenarios span diverse values → range recommendation (preserves data variety)

### Applying Recommendations

The output is a `recommendations.json` file. The config applier can preview proposed changes against current defaults, then write `config_overrides.json`. This file is auto-loaded by `SimulationConfig.__post_init__`, so subsequent simulation runs use the tuned values without code changes.

## Sweep Reporting

After running sweeps, the sweep report ranks parameter combinations by three dimensions:

| Dimension | What It Ranks | Why It Matters |
|-----------|--------------|----------------|
| **Data Volume** | Scenarios by total rows across detail tables | Higher volume = more training examples for ML |
| **Data Variety** | Scenarios by distinct categorical values (channels, outcome types, event types, segments) | Higher variety = better model generalization |
| **Primary KPI** | Scenarios by the key business metric (revenue, fill rate, CLV) | Identifies which parameter combos drive realistic outcomes |

## Extending the Framework

### Adding a New Sweep

1. Define a `SweepConfig` in `sweep/config_generator.py` with the parameters to vary
2. Export it from `sweep/__init__.py`
3. Map the sweep name to its target workflow in `sweep_runner.py`

### Adding a New Assumption

1. Add the field to the relevant dataclass in `shared/config.py` (e.g., `EngagementAssumptions`)
2. Reference it in the workflow code (e.g., `self.config.engagement.new_field`)
3. Optionally add it to a sweep config — the generic `_apply_overrides` in `sweep_runner.py` will pick it up automatically
4. Run the sweep → recommend → apply pipeline to tune it
