# Dashboard

## Overview

The dashboard is a React single-page application backed by an Express API server. It displays 36 live metrics across 5 operational tabs, plus an AI-generated executive digest. An integrated chat panel lets users ask questions about any metric, powered by Agent 1.

## Live Data & Refresh Cadence

All metric tiles display a **"live"** indicator — this reflects genuine live polling, not static data. The dashboard uses `@tanstack/react-query` with a `refetchInterval` of **30 seconds** (30,000 ms). Every 30 seconds, each tab fires an HTTP GET to the Express API, which runs read-only queries against DuckDB and returns current metric values.

| Behavior | Detail |
|----------|--------|
| **Polling interval** | 30 seconds per tab |
| **Stale time** | 15 seconds — cached data considered fresh for half the polling interval |
| **Transport** | HTTP GET `/api/metrics/:tab` via `fetch()` |
| **Database** | DuckDB opened in read-only mode, queries run concurrently via `Promise.allSettled` |
| **Retries** | 1 retry on failure |

The digest tab has a separate one-time startup poll: it calls `GET /api/digest` every 5 seconds (up to ~5 minutes) waiting for Agent 2 to generate the executive narrative.

There are no WebSockets or Server-Sent Events — the mechanism is straightforward HTTP polling.

## Tabs & Personas

### Tabs

| Tab | ID | Description |
|-----|----|-------------|
| Digest | `digest` | AI-generated executive narrative (Agent 2) |
| Main | `main` | Revenue, customers, conversion, AOV, CLV, return rate |
| Omnichannel | `omnichannel` | Cross-channel performance and fulfillment metrics |
| Customer Engagement | `customer-engagement` | Loyalty, campaigns, support interactions |
| Inventory Replenishment | `inventory-replenishment` | Stock levels and replenishment tracking |
| Customer Reviews | `customer-reviews` | Sentiment analysis and review processing |

### Personas

Personas control which tabs are visible to a given user role:

| Persona | Visible Tabs |
|---------|-------------|
| **Master** | All 6 tabs |
| **C-Suite** | Digest, Main |
| **Inventory Specialist** | Inventory Replenishment |
| **Customer Specialist** | Customer Engagement, Customer Reviews |
| **Omni Specialist** | Omnichannel |

### View Modes

Each metric tab supports three views:

1. **Dashboard** — tile grid with sparklines + chat panel
2. **Detail** — drill-down into a single metric with drivers, insights, and forecast
3. **Review Table** — customer review records with sentiment badges (Customer Reviews tab only)

## Metrics

36 metrics are defined across 5 tabs in `metric-registry.ts`, each with drivers, insights, and seed values.

### Main (6 metrics)

| Metric | ID | Format |
|--------|----|--------|
| Total Revenue | `revenue` | currency |
| Total Customers | `customers` | number |
| Conversion Rate | `conversion` | percentage |
| Average Order Value | `aov` | currency |
| Customer Lifetime Value | `clv` | currency |
| Return Rate | `return-rate` | percentage |

### Omnichannel (8 metrics)

| Metric | ID | Format |
|--------|----|--------|
| Arrival Rate | `omni-arrival-rate` | number |
| Conversion Rate | `omni-conversion` | percentage |
| Cart Abandonment Rate | `omni-cart-abandon` | percentage |
| Avg Journey Time | `omni-avg-journey` | number |
| Total Orders | `omni-total-orders` | number |
| On-Time Delivery % | `omni-ontime` | percentage |
| Avg Fulfillment Duration | `omni-fulfillment-dur` | number |
| Payment Success Rate | `omni-payment-success` | percentage |

### Customer Engagement (8 metrics)

| Metric | ID | Format |
|--------|----|--------|
| Active Customer Rate | `ce-active-rate` | percentage |
| Churn Rate | `ce-churn-rate` | percentage |
| Campaign Open Rate | `ce-open-rate` | percentage |
| Campaign CTR | `ce-campaign-ctr` | percentage |
| Loyalty Enrollment Rate | `ce-enrollment-rate` | percentage |
| Points Redemption Rate | `ce-redemption-rate` | percentage |
| Ticket Resolution Rate | `ce-resolution-rate` | percentage |
| Avg Satisfaction Rating | `ce-satisfaction` | number |

### Inventory Replenishment (8 metrics)

| Metric | ID | Format |
|--------|----|--------|
| Total Qty on Hand | `ir-qty-on-hand` | number |
| Items Below Reorder Point | `ir-below-reorder` | number |
| Stockout Count | `ir-stockout-count` | number |
| Fill Rate | `ir-fill-rate` | percentage |
| Supplier On-Time % | `ir-supplier-ontime` | percentage |
| Avg Lead Time | `ir-avg-lead-time` | number |
| Inventory Turnover | `ir-turnover` | number |
| Shrinkage Rate | `ir-shrinkage-rate` | percentage |

### Customer Reviews (6 metrics)

| Metric | ID | Format |
|--------|----|--------|
| Total Reviews | `cr-total-reviews` | number |
| Positive Rate | `cr-positive-pct` | percentage |
| Negative Rate | `cr-negative-pct` | percentage |
| Avg Sentiment Score | `cr-avg-score` | number |
| Needing Human Review | `cr-needs-review` | number |
| Processing Rate | `cr-processed-pct` | percentage |

## Agent Integration

Three AI agents connect to the dashboard:

| Agent | Port | Purpose | Trigger |
|-------|------|---------|---------|
| **Agent 1 — Explainer** | 8001 | Chat panel Q&A about metrics | User sends a message in the chat panel; auto-fires on tab activation |
| **Agent 2 — Narrative** | 8002 | Executive digest generation | Server startup + manual regenerate |
| **Agent 3 — Sentiment** | 8003 | Customer review sentiment processing | Server startup (`POST /retry`) |

If Agent 1 is unavailable, the chat panel falls back to the Spark LLM (`gpt-4o-mini`) for responses.

## Analytics Assistant

### Auto-Query on Tab Activation

When a metric tab is visited for the first time in a session and has no existing chat messages, the dashboard automatically sends **"Tell me what's going on"** to Agent 1. This applies to all 5 metric tabs: Main, Omnichannel, Customer Engagement, Inventory Replenishment, and Customer Reviews. The Digest tab is excluded (it uses Agent 2 instead).

The auto-query fires after a 500ms delay to let the tab render. If another query is already in-flight, the tab waits until the previous one completes before firing — Agent 1's workflow does not support concurrent executions on the same instance.

### Tab Navigation Behavior

| Behavior | Detail |
|----------|--------|
| **Serialized queries** | Only one auto-query runs at a time. Each tab waits for the prior tab's query to finish (`isLoading` guard). |
| **Switching quickly** | Safe — if you click through tabs rapidly, each tab will fire its auto-query only after the previous one completes. |
| **Returning to a tab** | If the tab already has chat messages (from auto-query or user interaction), the auto-query does not re-fire. |
| **Drill-down and back** | Navigating into a metric detail or review table view and returning preserves all chat messages. |
| **Tab switching** | Chat history is per-tab and persisted in localStorage via `useKV`. Switching tabs shows that tab's conversation. |
| **Refresh Chat** | Clears the current tab's messages. A new auto-query will not fire (the tab is already marked as queried for this session). |

### Recommended Navigation Flow

No special pauses are needed between tab switches. Navigate naturally:

1. Land on **Main** → auto-query fires, response appears
2. Switch to **Omnichannel** → waits for Main to finish if still loading, then fires
3. Continue through **Customer Engagement** → **Inventory Replenishment** → **Customer Reviews**

Each tab's Analytics Assistant response persists across tab switches and drill-down navigation.

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Framework | React | 19 |
| Build tool | Vite | 7 |
| Language | TypeScript | 5.7 |
| UI primitives | shadcn/ui (Radix UI) | — |
| Styling | Tailwind CSS | 4 |
| Charting | D3.js (sparklines), Recharts | — |
| Animation | Framer Motion | 12 |
| State / data fetching | @tanstack/react-query | 5 |
| Icons | Phosphor Icons | — |
| Server | Express | 5 |
| Database | DuckDB (duckdb-async) | — |

## Server & API

The Express server runs on port `3001` (configurable via `DASHBOARD_API_PORT`) and exposes:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/metrics/:tab` | Returns live metric values for a tab from DuckDB |
| GET | `/api/reviews` | Customer review records (optional `?filter=all\|positive\|negative\|needs_review`) |
| GET | `/api/digest` | Cached digest status: `ready`, `generating`, or `none` |

The server opens DuckDB in read-only mode. SQL queries are defined per-metric in `shared/metric-queries.ts` and run concurrently.

## Port Map

| Service | Port | Configurable |
|---------|------|-------------|
| Vite dev server | 5173 | `vite.config.ts` |
| Express API | 3001 | `DASHBOARD_API_PORT` env var |
| Agent 1 (Explainer) | 8001 | docker-compose |
| Agent 2 (Narrative) | 8002 | `AGENT2_URL` env var |
| Agent 3 (Sentiment) | 8003 | `AGENT3_URL` env var |

## Key Components

| Component | Purpose |
|-----------|---------|
| `NavigationSidebar` | Left sidebar with tab navigation and persona selector |
| `DashboardView` | Responsive metric grid layout + chat panel |
| `MetricTile` | Card with animated counter, trend arrows, D3 sparkline |
| `MetricDetailView` | Drill-down with driver cards, insights, forecast |
| `ChatInterface` | Chat panel with message bubbles and input |
| `DigestView` | Full-page narrative display for Agent 2 output |
| `ReviewTableView` | Customer review table with sentiment/status badges |
