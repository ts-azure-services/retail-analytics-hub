# Workflows

The simulation models three retail domains. Each workflow runs as a set of SimPy processes that generate events over a configurable time horizon, persisting structured data to DuckDB for downstream analysis and ML training.

## Omnichannel Purchase

Simulates customer shopping journeys from arrival through checkout and fulfillment across three channels: online, in-store, and BOPIS (buy-online-pick-up-in-store).

### Process Flow

1. **Arrival** — Customers arrive via Poisson processes at channel-specific rates
2. **Browsing** — Exponentially-distributed browsing duration; basket is built during this phase
3. **Queue & Checkout** — In-store customers enter a checkout queue with balking behavior (leave if the queue exceeds a threshold); online customers proceed directly
4. **Cart Abandonment** — Probabilistic abandonment based on channel, wait time, and basket characteristics
5. **Payment** — Payment method selection, with configurable failure and retry rates
6. **Fulfillment** — Order processing with carrier assignment and SLA tracking

### Key Metrics

- Conversion rate, average order value, revenue
- Queue wait times, balking rate
- Fulfillment SLA compliance, fulfillment duration

### Data Tables

- `customer_journeys` — Individual journey records with features and outcomes
- `order_metrics` — Order-level fulfillment data
- `hourly_demand` — Aggregated demand by hour and channel

---

## Inventory Replenishment

Simulates supply chain operations for a product catalog: demand depletion, reorder triggers, supplier deliveries, and inventory auditing.

### Process Flow

1. **Demand Depletion** — Stochastic consumption driven by customer purchases from the omnichannel workflow
2. **Reorder Point Monitoring** — Continuous-review (s, Q) policy: when stock falls to the reorder point, a purchase order is generated
3. **Purchase Order Generation** — Automatic PO creation with quantity based on economic order quantity
4. **Supplier Delivery** — Variable lead times modeled per supplier, with reliability and short-shipment probability
5. **Goods Receipt** — Receiving with potential quantity discrepancies
6. **Shrinkage** — Daily inventory loss simulation (theft, damage, expiry)

### Key Metrics

- Fill rate, stockout count and duration
- Average lead time, supplier on-time rate
- Inventory turnover, shrinkage rate

### Data Tables

- `inventory_events` — Stock movements and stockout events
- `supplier_deliveries` — PO fulfillment with lead time actuals
- `inventory_snapshots` — Daily inventory positions per product

---

## Customer Engagement

Simulates CRM and loyalty operations: customer lifecycle management, campaign execution, loyalty programs, and churn prevention.

### Process Flow

1. **Customer Lifecycle** — State machine transitions: New → Active → Lapsed → Churned, driven by purchase recency and engagement signals
2. **RFM Segmentation** — Periodic recency/frequency/monetary scoring to assign value tiers (High, Medium, Low)
3. **Campaign Execution** — Scheduled and event-triggered campaigns (email, SMS, push) with channel-specific send logic
4. **Response Simulation** — Open, click, and conversion probabilities conditioned on campaign type, customer segment, and fatigue
5. **Loyalty Program** — Points accrual on purchases and periodic multiplier promotions; redemption at configurable thresholds
6. **Churn Prevention** — Risk scoring based on engagement decay; automatic retention campaign triggers
7. **Service Tickets** — Issue creation and resolution, with impact on satisfaction and churn probability

### Key Metrics

- Churn rate, retention rate
- Campaign response rate (open, click, conversion)
- Customer lifetime value, loyalty redemption rate
- Service ticket resolution time

### Data Tables

- `customer_snapshots` — Customer state at simulation end (segment, tier, lifetime value, churn status)
- `campaign_interactions` — Campaign send/response records

---

## Reusable Architecture for New Workflows

The three workflows share a common architecture that makes adding new retail workflows straightforward. This section documents what is reusable as-is, what requires new code, and where the extension points are.

### Shared Simulation Contract

All three workflow classes follow an identical constructor signature:

```
__init__(self, env, config, resources, persistence, metrics)
```

Each implements the same structural pattern: SimPy processes that emit to three persistence channels (Event Hub for streaming, CosmosDB for immutable logs, PostgreSQL for transactional state). The `env`, `config`, `resources`, `persistence`, and `MetricsCollector` objects are dependency-injected — nothing is hardcoded to a specific domain. A new workflow drops into `simulation/workflows/` and follows this contract without touching existing code.

### Shared Agent Pipeline

Agents use a stage-based pipeline via `WorkflowBuilder` from `agent_framework`:

| Stage | Agent 1 (Explainer) | Agent 2 (Narrative) | Agent 3 (Sentiment) |
|---|---|---|---|
| Input prep | `prepare_input` | `prepare_input` | `fetch_review` |
| Classification | Intent classifier (LLM) | Intent classifier (LLM) | Sentiment classifier (LLM) |
| Data/Adaptation | `gather_data` (MCP tools) | `gather_data` (MCP tools) | `adapt_classification` |
| Analysis | Data analyzer (LLM) | Analyzer + Deep reasoner (LLM) | — |
| Formatting | Response formatter (LLM) | Narrative formatter (LLM) | Responder (LLM) |
| Output | `extract_output` | `extract_output` | `persist_results` |

The `WorkflowBuilder`, `@executor` decorator, `ChatAgent`/`AgentExecutor` creation pattern, and SSE streaming protocol are all reusable. A new agent creates its own `workflow_manager.py`, `agents.py`, `executors.py`, and `prompts.py` following the same pattern.

### Reusable Shared Modules

| Module | What It Provides | Extension Point |
|---|---|---|
| `agents/shared/models.py` | Pydantic models, enums (`TabId`, `QuestionType`, `DecisionDomain`, `TimeHorizon`, `Urgency`) | Add new enum values and domain-specific models |
| `agents/shared/mcp_tools.py` | Tool registry, `call_tool()` with TTL caching, `TAB_TOOL_MAP` | Add new entry to `TAB_TOOL_MAP` with summary/drivers/extras/metric_ids |
| `agents/shared/db.py` | Dual-backend abstraction (DuckDB local, Fabric SQL cloud), `execute_query()` with row limits | New queries automatically get dialect switching |
| `agents/shared/config.py` | `Settings` via Pydantic BaseSettings, Azure AD auth, singleton `get_settings()` | Add new env vars as needed |
| `agents/shared/telemetry.py` | OTEL spans, `configure_telemetry()` | New agents inherit tracing for free |

### Adding a New Retail Workflow

A new workflow (e.g., Store Workforce Scheduling, Pricing Optimization, Markdown/Clearance) requires new code in these layers:

| Layer | What to Create | Example: Workforce Scheduling |
|---|---|---|
| **Simulation** | `simulation/workflows/workforce_scheduling.py` | SimPy processes for shift demand, break scheduling, overtime triggers |
| **Persistence** | New PostgreSQL tables + Event Hub topics | `shifts`, `staff_availability`, `labor_forecasts`; topic `workforce_events` |
| **MCP tools** | `agents/mcp_server/tools/workforce_tab.py` | `get_workforce_metrics_summary`, `get_staffing_drivers`, `get_shift_analysis` |
| **TAB_TOOL_MAP** | New key in `mcp_tools.py` | `"workforce": {"summary": ..., "drivers": ..., "extras": [...], "metric_ids": [...]}` |
| **Dashboard** | New `TabId` enum value + React components | `TabId.WORKFORCE_SCHEDULING` |
| **Agent (optional)** | New agent folder or reuse existing agents | Often not needed — see below |

### When You Don't Need a New Agent

Agent 1 (Explainer) routes by `TabId` and Agent 2 (Narrative) queries across all tabs via `tabs_to_query`. Adding a new workflow often requires **no new agent** — just:

1. A new simulation workflow class following the shared constructor contract
2. A new MCP tool module + `TAB_TOOL_MAP` entry
3. New enum values in `TabId` and metric ID lists
4. New prompts added to the existing agent's prompt files

Agent 2's `gather_data` executor already loops through `tabs_to_query` dynamically, so a new tab is automatically in scope for cross-functional narratives.

### Opportunities for Stronger Contracts

As the workflow count grows, the following patterns could be formalized:

- **Base workflow class** — The three workflows follow a convention, not a contract. An abstract `BaseRetailWorkflow(ABC)` with methods like `arrival_process()`, `_emit_event()`, and `persist_ml_data()` would enforce consistency.
- **Typed executor context** — The module-level `_context` dict works for three agents but would benefit from a typed context dataclass at scale.
- **Centralized prompt registry** — Per-agent `prompts.py` files could consolidate into `prompts.toml` for versioning across agents.
- **Query-builder base** — MCP tool modules share the summary + drivers + extras query structure but each re-implements SQL assembly. A base class could reduce boilerplate.
