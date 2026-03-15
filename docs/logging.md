# Observability — OpenTelemetry & Application Insights

This document describes the distributed tracing, metrics, and log correlation setup across the Python agents and Node.js dashboard. Traces are exported to Azure Application Insights in cloud and to the .NET Aspire dashboard during local development.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Exporter Selection Logic](#exporter-selection-logic)
- [Python Agents](#python-agents)
- [Node.js Dashboard](#nodejs-dashboard)
- [Infrastructure — Cloud](#infrastructure--cloud)
- [Infrastructure — Local (Aspire)](#infrastructure--local-aspire)
- [Manual Spans](#manual-spans)
- [Thread Context Propagation](#thread-context-propagation)
- [Dependencies & Version Pin](#dependencies--version-pin)
- [Environment Variables](#environment-variables)
- [File Inventory](#file-inventory)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        Cloud (ACA)                               │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │ Agent 1  │  │ Agent 2  │  │ Agent 3  │  │    Dashboard     │ │
│  │ (Python) │  │ (Python) │  │ (Python) │  │   (Node.js)      │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───────┬──────────┘ │
│       │              │              │               │            │
│       └──────────────┴──────────────┴───────────────┘            │
│                              │                                   │
│                    AzureMonitorExporter                           │
│                              │                                   │
│                  ┌───────────▼────────────┐                      │
│                  │  Application Insights  │                      │
│                  │   (Log Analytics WS)   │                      │
│                  └────────────────────────┘                      │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                     Local (Docker Compose)                        │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                       │
│  │ Agent 1  │  │ Agent 2  │  │ Agent 3  │   OTLP/gRPC           │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  ──────────┐         │
│       └──────────────┴──────────────┘                  │         │
│                                              ┌─────────▼───────┐ │
│                                              │ Aspire Dashboard │ │
│                                              │ :18888 (UI)     │ │
│                                              │ :4317  (OTLP)   │ │
│                                              └─────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

---

## Exporter Selection Logic

Both the Python agents and Node.js dashboard use the same three-tier fallback:

| Priority | Condition | Exporter | Protocol | Target |
|----------|-----------|----------|----------|--------|
| 1 | `APPLICATIONINSIGHTS_CONNECTION_STRING` is set | Azure Monitor Exporter | Proprietary (HTTP) | Application Insights |
| 2 | `OTEL_EXPORTER_OTLP_ENDPOINT` is set | OTLP Exporter | gRPC | Aspire dashboard / collector |
| 3 | Neither is set | Console Exporter | stdout | Terminal |

The env vars are mutually exclusive by precedence — if both are set, Application Insights wins.

---

## Python Agents

### Bootstrap

All three agents call `configure_telemetry(app, service_name)` once at FastAPI startup in their `main.py`:

```python
from agents.shared.telemetry import configure_telemetry

app = FastAPI()
configure_telemetry(app, service_name="agent1-explainer")
```

### What `configure_telemetry` does

1. Creates an OpenTelemetry `Resource` tagged with the service name.
2. Selects the exporter (see table above).
3. Configures a `TracerProvider` with a `BatchSpanProcessor`.
4. Configures a `MeterProvider` with a `PeriodicExportingMetricReader` (60-second export interval).
5. Enables auto-instrumentation for:
   - **FastAPI** — traces every HTTP request/response.
   - **HTTPX** — traces outbound HTTP calls (agent-to-agent, MCP, Azure OpenAI).
   - **Logging** — correlates Python log records with the active trace/span IDs.

### Crash protection

The outer `configure_telemetry` function wraps everything in `try/except`. If telemetry setup fails for any reason, the error is logged and the agent continues running without traces.

---

## Node.js Dashboard

### Bootstrap

The Express server loads tracing before the application via the `--import` flag:

```
tsx --import ./server/tracing.ts --watch server/index.ts
```

### What `tracing.ts` does

1. Reads `OTEL_SERVICE_NAME` (default: `dashboard`), `APPLICATIONINSIGHTS_CONNECTION_STRING`, and `OTEL_EXPORTER_OTLP_ENDPOINT`.
2. Selects the exporter using the same three-tier logic.
3. Starts a `NodeSDK` with `getNodeAutoInstrumentations()` (fs instrumentation disabled to reduce noise).
4. Registers a `SIGTERM` handler for clean shutdown.

### Dependencies

| Package | Version |
|---------|---------|
| `@opentelemetry/sdk-node` | ^0.52.0 |
| `@opentelemetry/auto-instrumentations-node` | ^0.47.0 |
| `@opentelemetry/exporter-trace-otlp-grpc` | ^0.52.0 |
| `@opentelemetry/resources` | ^1.25.0 |
| `@opentelemetry/semantic-conventions` | ^1.25.0 |
| `@azure/monitor-opentelemetry-exporter` | ^1.0.0-beta.24 |

---

## Infrastructure — Cloud

### Terraform

Application Insights is provisioned in `infra/cloud/main.tf`:

```hcl
resource "azurerm_application_insights" "main" {
  name                = "appi-fabric-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  workspace_id        = azurerm_log_analytics_workspace.example.id
  application_type    = "other"
}
```

The connection string is injected as an environment variable into all four container apps (dashboard + 3 agents):

| Env Var | Source |
|---------|--------|
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | `azurerm_application_insights.main.connection_string` |
| `OTEL_SERVICE_NAME` | Hardcoded per container: `dashboard`, `agent1-explainer`, `agent2-narrative`, `agent3-sentiment` |

### Terraform outputs

| Output | Sensitive |
|--------|-----------|
| `appinsights_connection_string` | Yes |
| `appinsights_instrumentation_key` | Yes |

---

## Infrastructure — Local (Aspire)

### Docker Compose

The .NET Aspire dashboard is defined in `agents/docker-compose.yml`:

```yaml
aspire-dashboard:
  image: mcr.microsoft.com/dotnet/aspire-dashboard:latest
  ports:
    - "18888:18888"   # UI
    - "4317:18889"    # OTLP gRPC
  environment:
    - DOTNET_DASHBOARD_UNSECURED_ALLOW_ANONYMOUS=true
```

Each agent container receives:

```yaml
environment:
  - OTEL_EXPORTER_OTLP_ENDPOINT=http://aspire-dashboard:18889
  - OTEL_SERVICE_NAME=agent1-explainer
```

### Makefile targets

| Target | Description |
|--------|-------------|
| `make aspire-up` | Start Aspire dashboard (OTEL trace viewer on http://localhost:18888) |
| `make aspire-down` | Stop and remove Aspire dashboard container |
| `make aspire-logs` | Tail Aspire dashboard logs |

---

## Manual Spans

Beyond auto-instrumentation, custom spans are added at key boundaries:

### MCP tool calls (`agents/shared/mcp_tools.py`)

Every `call_tool()` invocation is wrapped in a `mcp.tool.call` span with attributes:

| Attribute | Description |
|-----------|-------------|
| `mcp.tool.name` | Name of the MCP tool being called |
| `mcp.tool.cached` | Whether the result came from cache |
| `mcp.tool.success` | Whether the call succeeded |

### Database connections (`agents/shared/db.py`)

Both `_connect()` and `_fabric_connection()` are wrapped in `db.connect` spans with a `db.system` attribute indicating the backend (DuckDB, Fabric SQL, or Fabric KQL).

### Parallel tool gathering (`agents/agent1_explainer/executors.py`)

The `gather_data` executor wraps parallel MCP tool calls in a `gather_data.parallel_tools` span with a `tool.count` attribute. Individual worker threads propagate the parent OTEL context (see next section).

---

## Thread Context Propagation

Agent 1's `gather_data` executor runs MCP tool calls in parallel via `ThreadPoolExecutor`. Since OTEL context is thread-local, the parent span context must be explicitly propagated:

```
1. Capture parent context:   parent_ctx = otel_context.get_current()
2. In each worker thread:    token = otel_context.attach(parent_ctx)
3. Run the tool call
4. Detach:                   otel_context.detach(token)
```

This ensures parallel tool call spans appear as children of the `gather_data.parallel_tools` span rather than as orphans.

---

## Dependencies & Version Pin

### Python

| Package | Version Constraint | Notes |
|---------|-------------------|-------|
| `opentelemetry-api` | `>=1.25.0,<1.39.0` | Pinned upper bound |
| `opentelemetry-sdk` | `>=1.25.0,<1.39.0` | Pinned upper bound |
| `opentelemetry-instrumentation-fastapi` | `>=0.46b0,<0.60b0` | Tracks SDK version |
| `opentelemetry-instrumentation-httpx` | `>=0.46b0,<0.60b0` | Tracks SDK version |
| `opentelemetry-instrumentation-logging` | `>=0.46b0,<0.60b0` | Tracks SDK version |
| `opentelemetry-exporter-otlp` | `>=1.25.0,<1.39.0` | OTLP gRPC + HTTP |
| `azure-monitor-opentelemetry-exporter` | `>=1.0.0b21` | Speaks App Insights protocol |

### Why the `<1.39.0` pin?

The `agent-framework-core` package (used by all agents) declares a dependency on `azure-monitor-opentelemetry` v1.8.2 (the Azure Monitor distro). That distro's `__init__.py` imports `LogData` from `opentelemetry.sdk._logs`, which was removed in SDK v1.39.0. This causes an `ImportError` at import time, crashing the container.

Pinning the SDK to `<1.39.0` keeps both the distro and the Azure Monitor Exporter functional. The pin should be removed once `azure-monitor-opentelemetry` ships a version compatible with SDK 1.39+.

> The distro's observability is opt-in (`ENABLE_OTEL=true`, default `false`) and is not activated by our agents. The import crash is triggered by Python's namespace package resolution when importing the exporter sub-package, which traverses the distro's `__init__.py`.

---

## Environment Variables

| Variable | Set By | Purpose |
|----------|--------|---------|
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Terraform (cloud) | Activates Azure Monitor export |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | docker-compose.yml (local) | Activates OTLP/gRPC export to Aspire |
| `OTEL_SERVICE_NAME` | Terraform / docker-compose.yml | Service name in traces |
| `ENABLE_OTEL` | Not set (default `false`) | agent-framework's own observability — leave disabled |

---

## File Inventory

| File | Language | Role |
|------|----------|------|
| `agents/shared/telemetry.py` | Python | Central OTEL bootstrap for all agents |
| `agents/shared/config.py` | Python | Pydantic settings including telemetry env vars |
| `agents/shared/mcp_tools.py` | Python | Manual `mcp.tool.call` spans |
| `agents/shared/db.py` | Python | Manual `db.connect` spans |
| `agents/agent1_explainer/executors.py` | Python | Thread context propagation for parallel tool calls |
| `agents/agent1_explainer/main.py` | Python | Calls `configure_telemetry` at startup |
| `agents/agent2_narrative/main.py` | Python | Calls `configure_telemetry` at startup |
| `agents/agent3_sentiment/main.py` | Python | Calls `configure_telemetry` at startup |
| `dashboard/server/tracing.ts` | TypeScript | Node.js OTEL bootstrap (loaded via `--import`) |
| `dashboard/package.json` | JSON | OTEL npm dependencies |
| `agents/docker-compose.yml` | YAML | Aspire dashboard service + OTEL env vars |
| `infra/cloud/main.tf` | HCL | Application Insights resource + env var injection |
| `Makefile` | Make | `aspire-up`, `aspire-down`, `aspire-logs` targets |
| `pyproject.toml` (root + 3 agents) | TOML | OTEL Python dependencies with version pins |

---

## Diagnostics — Checking Container Logs

To retrieve console logs for a specific container app revision in Log Analytics, use the following KQL query:

```kql
ContainerAppConsoleLogs_CL
| where RevisionName_s == "ca-agent2-narrative-r3shm3--v1773542122"
| project Log_s
| summarize AllLogs = strcat_array(make_list(Log_s), "\n")
```

Replace the `RevisionName_s` value with the revision name of the container you want to inspect. Revision names are visible in the Azure Portal under the container app's **Revisions** blade or in `az containerapp revision list` output.
