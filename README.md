# Retail Workflows

A discrete-event simulation framework for retail operations, built with SimPy. Simulates three interconnected business workflows (omnichannel purchase, inventory replenishment, customer engagement) and provides a parameter sweep pipeline that tunes simulation assumptions to generate diverse, realistic data for ML model training.

The system operates as a closed loop: simulate → sweep parameters → recommend optimal configs → apply → re-simulate with better assumptions. A React dashboard provides real-time visibility into all 36+ business metrics, and three AI agents (powered by Azure OpenAI) provide on-demand narrative explanations, metric deep-dives, and customer sentiment analysis.

## Prerequisites

- **Python 3.12+** and [uv](https://docs.astral.sh/uv/) for Python dependency management
- **Node.js 18+** and npm (for the dashboard)
- **Docker** (for running AI agents locally via Docker Compose)
- **Terraform** (for provisioning Azure infrastructure)
- **Azure CLI** (`az`) — authenticated with `az login` and a subscription set

## Getting Started

All operations are driven through the Makefile. Run `make help` at any time to see a categorized listing of every available target, grouped into **core** workflows and **utilities**.

1. Install Python dependencies: `uv sync`
2. Seed local DuckDB databases — this creates the three local database files (`local_postgres.duckdb`, `local_cosmos.duckdb`, `event_hubs.duckdb`) with reference data (stores, products, customers, suppliers, etc.)
3. Run a simulation to generate transactional data
4. Start the dashboard to visualize metrics
5. Optionally, run parameter sweeps, train ML models, or deploy to Azure

The Makefile sections map to the subsystems described below. Each section header in `make help` corresponds to a phase or component of the project.

## Subsystems

### Simulation Engine (`simulation/`)

Three SimPy-based discrete-event workflows that model retail operations end-to-end:

- **Omnichannel Purchase** — customer arrivals, browsing, conversion, payment, fulfillment across online and in-store channels
- **Inventory Replenishment** — demand-driven stock depletion, reorder triggers, supplier lead times, delivery, and shrinkage
- **Customer Engagement** — lifecycle progression, campaign targeting, loyalty programs, and churn prevention

Workflows share a centralized `SimulationConfig` (dataclasses in `simulation/shared/`) that controls all assumptions — arrival rates, conversion probabilities, reorder points, churn thresholds, etc. Configuration can be overridden at runtime via `config_overrides.json`.

All simulation output persists to local DuckDB databases that mirror the schemas of cloud PostgreSQL and CosmosDB.

### Parameter Sweeps (`simulation/sweep/`, `analysis/`)

The sweep framework runs each workflow across a grid of parameter variations (9 sweeps, 3 per workflow) to explore how different assumptions affect output data volume, variety, and KPI realism. Each sweep runs in an isolated copy of the database to allow parallel execution.

After sweeps complete, results are merged, scored (volume 0.3 / variety 0.3 / KPI realism 0.4), and the best-performing parameter combinations are written to `recommendations.json`. These recommendations can be previewed and applied back to the simulation config, closing the loop.

### ML Pipeline (`simulation/ml/`, `analysis/train_models.py`)

Nine ML models train on simulation output — three per workflow:

- **Omnichannel**: conversion classifier, order value regressor, demand forecast (Prophet)
- **Inventory**: fulfillment time regressor, stockout risk classifier, supplier lead time regressor
- **Engagement**: churn classifier, campaign response predictor, CLV regressor

Training can run across all models or be scoped to a specific workflow group.

### Customer Reviews (`simulation/customer_review_simulator.py`)

Generates synthetic customer product reviews and persists them to `event_hubs.duckdb`. These reviews feed the sentiment analysis agent and the Reviews tab in the dashboard.

### Dashboard (`dashboard/`)

A React SPA (Vite + TypeScript + Tailwind) with an Express API server that queries DuckDB and exposes 36+ retail metrics across 6 tabs. The dashboard polls for live data every 30 seconds and connects to the three AI agents for on-demand analysis.

- **Frontend**: `http://localhost:5173`
- **API server**: `http://localhost:3001`

The dashboard has its own npm dependencies; install and start targets are available in the Makefile.

### AI Agents (`agents/`)

Three AI agents run as Docker containers, each backed by Azure OpenAI:

| Agent | Port | Model | Purpose |
|-------|------|-------|---------|
| Agent 1 — Explainer | 8001 | gpt-4o-mini | Metric explanations and drill-downs via MCP tools |
| Agent 2 — Narrative | 8002 | o3 | Multi-metric narrative analysis |
| Agent 3 — Sentiment | 8003 | gpt-4o-mini | Customer review sentiment analysis |

Agents share an MCP (Model Context Protocol) server (`agents/mcp_server/`) that exposes 7 tool modules for querying simulation data across all dashboard tabs — main, omnichannel, engagement, inventory, reviews, timeseries, and aggregated views.

Running agents locally requires Azure OpenAI credentials in `local.env` (provisioned via the local Terraform configuration). Docker Compose manages the agent lifecycle — build, start, stop, and log targets are all in the Makefile.

### Data Sync (`sync/`)

A pipeline for pushing local simulation data to Azure cloud services:

1. **Export** — extracts data from the three local DuckDB databases into Parquet (PostgreSQL tables) and NDJSON (CosmosDB collections, Event Hub events) files under `sync/staging/`
2. **Upload** — pushes staged files to Azure Blob Storage
3. **Import** — triggers a Container App Job (`sync/importer/`) that reads from Blob Storage and writes to Azure PostgreSQL, CosmosDB, and Event Hub

Each phase can be run individually or chained together in a single target. Event Hub data can also be synced independently.

### Infrastructure (`infra/`)

Two Terraform configurations manage Azure resources:

- **Local** (`infra/local/`) — provisions Azure OpenAI (with GPT-4o-mini and o3 deployments) and a service principal for agent containers. This is the minimum needed to run agents locally.
- **Cloud** (`infra/cloud/`) — provisions the full cloud stack: CosmosDB, PostgreSQL Flexible Server, Azure Container Registry, Container Apps (dashboard + 3 agents), Blob Storage, Key Vault, and Microsoft Fabric capacity. Supports `dev` (no VNET, fast iteration) and `prod` (full VNET + private endpoints) environment modes.

Both configurations use resource group tagging (`tf=local` / `tf=cloud`) for clean teardown.

### Fabric Integration (`fabric-admin-scripts/`)

Shell scripts and Makefile targets for integrating with Microsoft Fabric:

- Creating a Fabric Lakehouse and Real-Time Intelligence components (Eventhouse, Eventstream, KQL Database)
- Setting up database mirroring from CosmosDB and PostgreSQL into Fabric
- Creating OneLake shortcuts to mirrored data
- Managing Fabric capacity (suspend/resume/update SKU)

Several of these operations involve manual steps in the Fabric portal; the Makefile targets print guided instructions.

### Seed Data (`seed-data/`)

Populates local DuckDB databases with reference data — stores, products, customers, suppliers, and historical transactions. Also includes utilities for merging sweep results into the main databases, validating data integrity, and cleaning up cloud databases.

## Configuration

The project uses two environment files:

- **`local.env`** — Azure OpenAI endpoint, model deployment names, and service principal credentials. Generated by `make tf-local`.
- **`infra/.env`** — Cloud database connection strings, passwords, and Fabric settings. Generated by `make tf`.

Simulation parameters are controlled by `SimulationConfig` dataclasses (see `simulation/shared/config.py`). Runtime overrides can be specified in `config_overrides.json` at the repo root, which is loaded automatically by the config's `__post_init__`.

## Documentation

Detailed documentation lives in the `docs/` directory:

- [docs/concepts.md](docs/concepts.md) — architecture, closed-loop design, config system, MetricsCollector
- [docs/workflows.md](docs/workflows.md) — the three simulation workflows in detail
- [docs/data.md](docs/data.md) — full data model, table schemas, and lifecycle
- [docs/metrics.md](docs/metrics.md) — all 36+ metrics with SQL computations and drivers
- [docs/sweeps.md](docs/sweeps.md) — parameter sweep framework, scoring, convergence
- [docs/ml.md](docs/ml.md) — ML model inventory, training pipeline, extension guide
- [docs/dashboard.md](docs/dashboard.md) — dashboard tabs, metrics, agent integration, tech stack

## Repo Structure

```
simulation/                            # Discrete-event simulation engine
├── shared/                            #   Shared config, resources, persistence, metrics
├── workflows/                         #   Omnichannel, inventory, engagement workflows
├── sweep/                             #   Parameter sweep framework
├── ml/                                #   9 ML models (3 per workflow)
├── customer_review_simulator.py       #   Synthetic review generator
└── run_simulation.py                  #   CLI entry point
analysis/                              # Post-simulation analysis
├── sweep_report.py                    #   Sweep volume/variety reporting
├── sweep_recommend.py                 #   Recommendation generation
├── config_applier.py                  #   Apply recommendations to config
└── train_models.py                    #   ML model training orchestrator
agents/                                # AI agent system
├── agent1_explainer/                  #   Metric explainer agent (port 8001)
├── agent2_narrative/                  #   Narrative analysis agent (port 8002)
├── agent3_sentiment/                  #   Sentiment analysis agent (port 8003)
├── mcp_server/                        #   MCP tool server (7 tool modules)
├── shared/                            #   Shared agent config, DB, models
└── docker-compose.yml                 #   Local agent orchestration
dashboard/                             # React dashboard (Vite + Express)
├── server/                            #   Express API server (port 3001)
├── src/                               #   React frontend (port 5173)
└── PRD.md                             #   Product requirements
sync/                                  # Data sync pipeline (local → Azure)
├── export_postgres.py                 #   DuckDB → Parquet
├── export_cosmos.py                   #   DuckDB → NDJSON
├── export_eventhub.py                 #   DuckDB → NDJSON
├── upload.py                          #   Staged files → Azure Blob Storage
├── validate_cloud.py                  #   Local vs cloud data validation
└── importer/                          #   Container App Job (Blob → cloud DBs)
infra/                                 # Terraform infrastructure-as-code
├── local/                             #   Azure OpenAI + service principal
└── cloud/                             #   Full cloud stack (CosmosDB, Postgres, ACR, Container Apps, Fabric)
seed-data/                             # Database seeding & utilities
├── seed_local.py                      #   Local DuckDB seeding
├── merge_sweeps.py                    #   Consolidate sweep results
├── validate_data.py                   #   Data validation
├── cleanup_cosmos.py                  #   CosmosDB cleanup
└── cleanup_postgres.py                #   PostgreSQL cleanup
fabric-admin-scripts/                  # Fabric provisioning & management
docs/                                  # Documentation (concepts, workflows, data, metrics, sweeps, ML, dashboard)
Makefile                               # All commands — run: make help
```
