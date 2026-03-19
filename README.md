# Retail Workflows

A discrete-event simulation framework for retail operations, built with SimPy. Simulates three interconnected business workflows — omnichannel purchase, inventory replenishment, and customer engagement — and provides a closed-loop pipeline that sweeps parameter space, recommends optimal configurations, and re-simulates with better assumptions.

A React dashboard surfaces 36+ live metrics, and three AI agents (Azure OpenAI) provide on-demand narrative analysis, metric explanations, and customer sentiment processing.

## How It Fits Together

```
seed → simulate → sweep → recommend → apply → re-simulate
                                                   ↓
                              dashboard ← agents ← MCP tools ← DuckDB
                                                   ↓
                                        sync → Azure (Postgres, Cosmos, Fabric)
```

The simulation engine generates transactional data across three retail workflows. Parameter sweeps explore how assumption changes affect data volume, variety, and KPI realism. The best configurations feed back into the simulation. Nine ML models train on the swept data. A dashboard and three AI agents make it all explorable. Data can stay local (DuckDB) or sync to Azure.

## Prerequisites

Python 3.12+ with [uv](https://docs.astral.sh/uv/) · Node.js 18+ · Docker · Terraform · Azure CLI (`az login`)

## Getting Started

```bash
uv sync                  # install Python deps
make help                # see all available targets
make seed                # seed local DuckDB databases
make simulate            # run simulation
make dashboard-start     # start dashboard (localhost:5173)
```

## Documentation

| Topic | Doc | Covers |
|-------|-----|--------|
| Architecture | [concepts.md](docs/concepts.md) | Closed-loop design, SimPy environment, centralized config, MetricsCollector, persistence |
| Simulation | [workflows.md](docs/workflows.md) | Three workflows in detail, process flows, extension architecture |
| Data Model | [data.md](docs/data.md) | Table schemas, lifecycle (seed → simulate → sweep → train), DuckDB ↔ cloud parity |
| Metrics | [metrics.md](docs/metrics.md) | All 36+ metrics with SQL, composite drivers, cross-workflow relationships |
| Sweeps | [sweeps.md](docs/sweeps.md) | 9 sweep configs, scoring (volume/variety/KPI realism), recommendations |
| ML | [ml.md](docs/ml.md) | 9 models (scikit-learn + Prophet), training pipeline, feature importance |
| Dashboard | [dashboard.md](docs/dashboard.md) | Tabs, polling, agent integration, tech stack (React 19, Vite, Express) |
| Agents | [agents.md](docs/agents.md) | 3-agent architecture, MCP server, workflow steps, design patterns |
| Observability | [logging.md](docs/logging.md) | OpenTelemetry, Application Insights, Aspire dashboard, manual spans |
| SQL Parity | [sql-parity.md](docs/sql-parity.md) | DuckDB/Postgres ↔ MSSQL ↔ KQL dialect switching, parity tests |
| Security | [security-checklist.md](docs/security-checklist.md) | Infrastructure audit, network segmentation, compliance (PCI DSS, GDPR, SOC 2) |
| Testing | [testing.md](docs/testing.md) | Prescriptive test spec across all subsystems |

## Repo Structure

```
simulation/                            # Discrete-event simulation engine
├── shared/                            #   Config, resources, persistence, metrics
├── workflows/                         #   Omnichannel, inventory, engagement
├── sweep/                             #   Parameter sweep framework
├── ml/                                #   9 ML models (3 per workflow)
└── run_simulation.py                  #   CLI entry point
analysis/                              # Sweep reporting, recommendations, ML training
agents/                                # AI agent system (Docker Compose)
├── agent1_explainer/                  #   Metric drill-downs (port 8001)
├── agent2_narrative/                  #   Cross-tab narratives (port 8002)
├── agent3_sentiment/                  #   Review sentiment (port 8003)
├── mcp_server/                        #   7 MCP tool modules
└── shared/                            #   Config, DB, models, telemetry
dashboard/                             # React SPA + Express API (ports 5173, 3001)
sync/                                  # Local → Azure data pipeline
infra/                                 # Terraform (local: OpenAI | cloud: full stack)
seed-data/                             # DuckDB seeding & utilities
fabric-admin-scripts/                  # Microsoft Fabric provisioning
docs/                                  # Detailed documentation (see table above)
Makefile                               # All commands — run: make help
```
