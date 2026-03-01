# Architecture & Key Concepts

## Closed-Loop Workflow

The project follows a four-stage loop for tuning simulation assumptions:

1. **Model** — Define workflows (omnichannel, inventory, engagement) with discrete-event simulation logic in SimPy
2. **Configure** — All assumptions live centrally in `shared/config.py` as dataclasses, organized per workflow. No hardcoded values exist in workflow files.
3. **Sweep** — Systematically vary assumptions across parameter grids to find which combinations produce the richest, most realistic data
4. **Recommend + Apply** — Score sweep results by volume, variety, and KPI realism; generate recommendations; write tuned values back to `config_overrides.json` so future runs pick them up automatically

This loop is extensible: when a workflow model introduces new assumptions, you add the field to the relevant config dataclass, reference it in the workflow, optionally add it to a sweep config, and the same sweep → recommend → apply pipeline handles the rest.

## SimPy Environment

The simulation uses SimPy's discrete-event engine. Time advances only when events occur — there is no wall-clock polling. Each workflow registers processes with the environment, and processes yield timeouts (waits) or resource requests (queues, inventory). The environment runs until a configurable duration in simulated hours.

## Centralized Configuration

`SimulationConfig` in `shared/config.py` is the single source of truth for all tunable parameters. It contains nested dataclasses:

| Section | Scope | Examples |
|---------|-------|---------|
| `DistributionConfig` | Arrival rates, abandonment probabilities, basket characteristics | `arrival_rate_online`, `abandonment_rate_in_store` |
| `ResourceConfig` | Queue capacities, inventory levels | `checkout_counters`, `initial_stock` |
| `SLAConfig` | Service-level targets | `fulfillment_sla_hours`, `target_fill_rate` |
| `OmnichannelAssumptions` | Checkout times, payment methods, carriers, queue thresholds | `checkout_time_mean`, `payment_failure_rate` |
| `InventoryAssumptions` | Reorder points, lead times, shrinkage, audit parameters | `reorder_point`, `shrinkage_rate` |
| `EngagementAssumptions` | Value tiers, campaign rates, churn weights, loyalty params | `base_email_response_rate`, `points_per_dollar` |

### Config Overrides

After running the recommendation pipeline, tuned values are stored in `config_overrides.json` at the project root. This file is auto-loaded by `SimulationConfig.__post_init__`, so all subsequent simulation runs use the tuned values without code changes.

## Metrics Collection

`MetricsCollector` in `shared/metrics.py` tracks KPIs during simulation. Each workflow records events (arrivals, abandonments, purchases, stockouts, campaign sends) as they happen. After a run completes, the collector computes aggregated metrics (conversion rate, fill rate, churn rate) and persists both raw events and summaries.

## Persistence

Simulation data persists to DuckDB via `shared/persistence.py` and `shared/local_backend.py`. Each workflow writes to its own set of tables (see [workflows.md](workflows.md) for table listings). The local DuckDB backend mirrors the schema that would exist in cloud databases (Cosmos DB, PostgreSQL), allowing fully offline development and ML training.
