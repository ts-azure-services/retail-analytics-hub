# Multi-Agent Architecture Documentation

This document describes the three agents in the `agents/` directory — their purpose, discrete workflow steps, and the multi-agent design patterns they showcase.

---

## Table of Contents

- [Shared Infrastructure](#shared-infrastructure)
- [MCP Server](#mcp-server)
- [Agent 1 — Dashboard Explainer](#agent-1--dashboard-explainer)
- [Agent 2 — Business Narrative](#agent-2--business-narrative)
- [Agent 3 — Customer Sentiment Analysis](#agent-3--customer-sentiment-analysis)
- [Inter-Agent Communication](#inter-agent-communication)
- [Design Pattern Summary](#design-pattern-summary)
- [Deployment](#deployment)

---

## Shared Infrastructure

All three agents build on a common `shared/` module that provides:

| Module | Role |
|--------|------|
| `config.py` | Centralized Pydantic settings (Azure OpenAI credentials, model deployments, DB paths, safety limits). Singleton via `@lru_cache`. |
| `models.py` | Pydantic data contracts for every agent's input/output (e.g. `IntentResult`, `NarrativeResponse`, `ReviewResponse`), plus shared enums (`TabId`, `QuestionType`, `DecisionDomain`). |
| `db.py` | Dual-backend database abstraction — DuckDB for local development, Fabric SQL for cloud. Exposes `execute_query()` with enforced row limits and timeouts. |
| `mcp_tools.py` | Lazy-loaded MCP tool registry. `call_tool(name, **kwargs)` invokes tools by name. `TAB_TOOL_MAP` maps each dashboard tab to its summary, driver, and extra tools. |

---

## MCP Server

The MCP server (`mcp_server/server.py`) acts as a **tool-service abstraction layer** between agents and the database.

- **Protocol**: Model Context Protocol over stdio transport.
- **Deployment**: Spawned as a subprocess by Agent 1 and Agent 2 during initialization.
- **Tool modules**: Dynamically loads tools from seven modules — `main_tab`, `omnichannel_tab`, `engagement_tab`, `inventory_tab`, `reviews_tab`, `timeseries`, `aggregated`.
- **API surface**: `list_tools()` returns available tool definitions; `call_tool(name, arguments)` executes a handler and returns JSON.
- **Purpose**: Decouples agents from raw SQL. Each tool encapsulates a pre-defined query and data transformation, ensuring consistent, versioned data access.

---

## Agent 1 — Dashboard Explainer

### Purpose

Answers specific questions about individual metrics on a single dashboard tab. Produces concise, metric-driven explanations suitable for tactical decision-making.

**Port**: 8001 · **Model**: gpt-4o-mini (temperature 0.3)

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/chat` | Accepts `ChatRequest`, returns `ChatResponse` |
| `GET`  | `/health` | Health check |

### Workflow Steps

```
ChatRequest
  │
  ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 1 — PREPARE_INPUT (Executor)                                │
│  • Packages {message, active_tab, current_view, selected_metric} │
│  • Stores active_tab in module-level context                     │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 2 — INTENT_CLASSIFIER (ChatAgent → AgentExecutor)           │
│  • Model: gpt-4o-mini                                            │
│  • Determines dashboard tab, relevant metric IDs, question type  │
│  • Output: JSON {tab, metric_ids[], question_type,               │
│            clarified_question}                                    │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 3 — GATHER_DATA (Executor)                                  │
│  • Parses intent JSON                                            │
│  • Uses TAB_TOOL_MAP to select MCP tools                         │
│  • Calls: summary tool, driver tools (per metric_id),            │
│           extra tools (for comparison questions)                  │
│  • Aggregates results into {intent, data{summary, drivers,       │
│    extras}}                                                      │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 4 — DATA_ANALYZER (ChatAgent → AgentExecutor)               │
│  • Model: gpt-4o-mini                                            │
│  • Synthesizes raw data into business-focused narrative           │
│  • Highlights specific numbers, drivers, and anomalies           │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 5 — RESPONSE_FORMATTER (ChatAgent → AgentExecutor)          │
│  • Model: gpt-4o-mini                                            │
│  • Produces formatted output: headline, explanation (~150 words),│
│    actionable insight                                            │
│  • Enforces word count; uses specific data values                │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 6 — EXTRACT_OUTPUT (Executor)                               │
│  • Pass-through — yields formatter response as final output      │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
                  ChatResponse
```

### Design Patterns Showcased

| Pattern | Detail |
|---------|--------|
| **Sequential Pipeline Orchestration** | `WorkflowBuilder` chains steps deterministically; one workflow instance per request. |
| **Agent Specialization** | Three separate `ChatAgent` instances (Intent, Analyzer, Formatter), each with a focused system prompt. |
| **MCP Tool Calling** | Data gathering invokes pre-registered MCP tools via `call_tool()` — not raw SQL. |
| **Structured I/O** | Every executor exchanges JSON parsed into Pydantic models, enforcing type safety across async boundaries. |
| **Executor Pattern** | `@executor`-decorated functions with `WorkflowContext` handle each pipeline stage. |
| **Module-Level Shared State** | A `_context` dict carries tab/message info between executor steps within a single request. |

---

## Agent 2 — Business Narrative

### Purpose

Generates comprehensive, cross-functional business narratives with deep reasoning about causality, correlations, and recommendations. Designed for executive briefings and strategic planning.

**Port**: 8002 · **Models**: gpt-4o-mini (intent, formatting) + gpt-5.2 reasoning model (analysis, deep reasoning)

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/narrative` | Accepts `NarrativeRequest`, returns `NarrativeResponse` with structured sections |
| `POST` | `/chat` | Interactive follow-up mode, returns `ChatResponse` |
| `GET`  | `/health` | Health check |

### Workflow Steps

```
NarrativeRequest / ChatRequest
  │
  ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 1 — PREPARE_INPUT (Executor)                                │
│  • Two modes:                                                    │
│    a. "narrative" — broader focus, executive-level cross-tab     │
│    b. "chat" — interactive follow-up with tab/metric context     │
│  • Packages request into contextual prompt                       │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 2 — INTENT_CLASSIFIER (ChatAgent → AgentExecutor)           │
│  • Model: gpt-4o-mini                                            │
│  • Output: JSON {decision_domain, time_horizon, urgency,         │
│            sub_questions[], tabs_to_query[]}                      │
│  • Determines which multiple tabs are relevant, business domain  │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 3 — GATHER_DATA (Executor)                                  │
│  • Broader data collection than Agent 1:                         │
│    – Summary + extras for ALL tabs in tabs_to_query              │
│    – Cross-tab health check tool                                 │
│    – Timeseries data (48-hour demand trend, hourly patterns)     │
│    – Correlation analysis (e.g. conversion vs. revenue)          │
│  • Returns aggregated {intent, data} with multi-tab coverage     │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 4 — DATA_ANALYZER (ChatAgent → AgentExecutor)               │
│  • Model: gpt-5.2 (reasoning model)                              │
│  • Synthesizes multi-tab data into comprehensive analysis        │
│  • Highlights cross-tab metrics, key trends, relationships       │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 5 — DEEP_REASONER (ChatAgent → AgentExecutor)               │
│  • Model: gpt-5.2 (reasoning model)                              │
│  • Causal chain reasoning (a → b → c)                            │
│  • Cross-tab correlations, anomaly detection, root cause analysis │
│  • Produces prioritized recommendations (top 3-5) and risk flags │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 6 — NARRATIVE_FORMATTER (ChatAgent → AgentExecutor)         │
│  • Model: gpt-4o-mini                                            │
│  • Produces executive briefing (~400 words):                     │
│    – Executive Summary (2-3 sentences)                           │
│    – Key Findings (3-5 bullets with numbers)                     │
│    – Recommendations (3-5 ranked by impact)                      │
│    – Risk Flags (1-3 items)                                      │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 7 — EXTRACT_OUTPUT (Executor)                               │
│  • Parses narrative into structured sections (findings,          │
│    recommendations, risks)                                       │
│  • FastAPI endpoint maps output into NarrativeResponse model     │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
                NarrativeResponse
```

### Design Patterns Showcased

| Pattern | Detail |
|---------|--------|
| **Hierarchical Reasoning** | Three-tier LLM chain: Analyzer → Deep Reasoner → Formatter. Each stage builds on the previous, explicitly separating data synthesis from causal reasoning from formatting. |
| **Model Specialization** | Reasoning models (gpt-5.2) handle analysis and deep reasoning; the lightweight gpt-4o-mini handles intent classification and formatting. |
| **Cross-Functional Scope** | Data gathering spans multiple dashboard tabs, timeseries, and correlation tools — contrasting Agent 1's single-tab focus. |
| **Dual Execution Modes** | Conditional prompt branching supports both a "narrative" mode (executive report) and a "chat" mode (interactive follow-up). |
| **Causal Chain Prompting** | Deep Reasoner prompt explicitly requests `a → b → c` chains, root-cause analysis, and risk flags — a structured chain-of-thought approach. |
| **Structured Section Output** | Final response is parsed into typed Pydantic sections (`findings`, `recommendations`, `risks`) for predictable downstream consumption. |

---

## Agent 3 — Customer Sentiment Analysis

### Purpose

Analyzes customer reviews in real-time for sentiment classification and determines the appropriate action — chatbot auto-response or escalation to human review. Includes persistent database tracking and a background retry loop for failed reviews.

**Port**: 8003 · **Model**: gpt-4o-mini

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/analyze` | Accepts `ReviewRequest`, returns `ReviewResponse` |
| `POST` | `/retry` | Manually trigger retry of all incomplete reviews |
| `GET`  | `/health` | Health check |

### Workflow Steps

```
ReviewRequest (review_id, review_text)
  │
  ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 1 — FETCH_REVIEW (Executor)                                 │
│  • Receives review_id and review_text                            │
│  • Stores in module-level _context for downstream stages         │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 2 — SENTIMENT_CLASSIFIER (ChatAgent → AgentExecutor)        │
│  • Model: gpt-4o-mini                                            │
│  • Classifies into: very_negative | negative | neutral |         │
│    positive | very_positive                                      │
│  • Outputs: {sentiment_category, sentiment_score (-1.0 to 1.0), │
│              key_phrases[], confidence}                           │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 3 — ADAPT_CLASSIFICATION (Executor)                         │
│  • Parses sentiment JSON                                         │
│  • Stores classification in _context                             │
│  • Packages for responder: {review_text, sentiment_category,     │
│    sentiment_score}                                              │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 4 — RESPONDER (ChatAgent → AgentExecutor)                   │
│  • Model: gpt-4o-mini                                            │
│  • Deterministic routing rules:                                  │
│    – very_negative → flag for human review (no auto-response)    │
│    – negative + specific defect → flag for human review          │
│    – negative + general dissatisfaction → draft empathetic reply  │
│    – neutral → draft friendly thank-you                          │
│    – positive / very_positive → draft cheerful response          │
│  • Override rules flag human review for: refund requests,        │
│    health concerns, contamination, foreign objects               │
│  • Output: {status, chatbot_statement, needs_human_review,       │
│             reasoning}                                           │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ Step 5 — PERSIST_RESULTS (Executor)                              │
│  • Parses responder JSON                                         │
│  • Updates DuckDB customer_reviews table:                        │
│    sentiment_category, sentiment_score, status,                  │
│    chatbot_statement, processed_at                               │
│  • Yields final output with review_id and all fields             │
└──────────────────────┬───────────────────────────────────────────┘
                       ▼
                 ReviewResponse
```

### Background Retry Loop

Agent 3 runs an **async background task** (10-minute interval) that:

1. Queries `customer_reviews` for rows with status `incomplete processing` and `retry_count < 3`.
2. Re-runs the full workflow for each review.
3. On failure, increments `retry_count` and records `error_message` and `last_retry_at`.

### Database Schema

```sql
CREATE TABLE customer_reviews (
    id                  INTEGER PRIMARY KEY,
    review_text         VARCHAR NOT NULL,
    sentiment_category  VARCHAR,
    sentiment_score     DOUBLE,
    status              VARCHAR DEFAULT 'To be processed',
    chatbot_statement   VARCHAR,
    created_at          TIMESTAMP DEFAULT NOW,
    processed_at        TIMESTAMP,
    error_message       VARCHAR,
    retry_count         INTEGER DEFAULT 0,
    last_retry_at       TIMESTAMP
);
```

### Design Patterns Showcased

| Pattern | Detail |
|---------|--------|
| **Hybrid Classification** | LLM-based sentiment scoring combined with deterministic rule-based routing (e.g. very-negative → human review). |
| **Database Persistence** | Every result is written to a `customer_reviews` table, enabling audit trails, analytics, and recovery. |
| **Background Retry Loop** | A `lifespan`-managed async task retries incomplete reviews every 10 minutes (max 3 attempts), providing resilience to transient failures. |
| **Status State Machine** | Reviews transition through defined statuses: `To be processed` → `processed for response` / `Needing human review` / `incomplete processing`. |
| **Safety Override Rules** | Hard-coded escalation rules for sensitive topics (health, refunds, contamination) override LLM output, enforcing safety guardrails. |
| **Lifespan Management** | FastAPI lifespan context manager initializes the DB schema and starts the background task on application startup. |

---

## Inter-Agent Communication

```
┌─────────────────────────┐
│       Dashboard         │
│  (React + Vite, :5173)  │
└────┬──────┬──────┬──────┘
     │      │      │
     ▼      ▼      ▼
  Agent 1  Agent 2  Agent 3
  (:8001)  (:8002)  (:8003)
     │      │
     ▼      ▼
  MCP Server (subprocess, stdio)
     │
     ▼
  Database (DuckDB / Fabric SQL)
```

- **Dashboard → Agents**: HTTP REST (JSON). Each agent is a standalone FastAPI service.
- **Agents → MCP Server**: Agents 1 and 2 spawn the MCP server as a subprocess and communicate over stdio using the Model Context Protocol.
- **Agents → Database**: Agent 3 writes directly to DuckDB. Agents 1 and 2 read data indirectly through MCP tools.
- **No direct agent-to-agent communication**: The agents are independent; the dashboard orchestrates which agent to call.

---

## Design Pattern Summary

### Orchestration & Workflow

| Pattern | Agents | Description |
|---------|--------|-------------|
| Sequential Pipeline | All | `WorkflowBuilder` chains executor steps in a fixed order. |
| Executor Pattern | All | `@executor`-decorated async functions with `WorkflowContext` encapsulate each stage. |
| Module-Level Context | All | A `_context` dict passes data between executors within a single request lifecycle. |
| Background Task | Agent 3 | Async retry loop runs independently of request handling. |

### LLM Usage

| Pattern | Agents | Description |
|---------|--------|-------------|
| Agent Specialization | All | Each workflow stage uses a dedicated `ChatAgent` with a focused system prompt. |
| Model Tiering | Agent 2 | Reasoning models (gpt-5.2) for deep analysis; lightweight models (gpt-4o-mini) for classification and formatting. |
| Structured JSON Output | All | LLMs produce JSON parsed by Pydantic models; fallback defaults on parse failure. |
| Chain-of-Thought | Agent 2 | Deep Reasoner stage explicitly prompts for causal chains and root-cause analysis. |

### Data & Tools

| Pattern | Agents | Description |
|---------|--------|-------------|
| MCP Tool Abstraction | Agents 1, 2 | Data access via named tools instead of raw SQL. Decouples agents from schema changes. |
| Dual-Backend DB | All | `shared/db.py` transparently switches between DuckDB (local) and Fabric SQL (cloud). |
| Lazy Initialization | All | Tool registry and workflow instances are created on demand, not at import time. |

### Resilience & Safety

| Pattern | Agents | Description |
|---------|--------|-------------|
| Deterministic Safety Rules | Agent 3 | Hard-coded overrides ensure sensitive reviews always escalate to humans. |
| Retry with Backoff | Agent 3 | Failed reviews are retried up to 3 times via a background loop. |
| Error Wrapping | All | Tool call failures and JSON parse errors return structured error objects rather than crashing the pipeline. |
| Health Checks | All | Each agent exposes `/health` for container orchestration readiness probes. |

---

## Deployment

Defined in `docker-compose.yml`, each agent runs as an independent container:

| Service | Port | Model | Key Env Vars |
|---------|------|-------|-------------|
| `agent1-explainer` | 8001 | gpt-4o-mini | `AGENT_TEMPERATURE=0.3` |
| `agent2-narrative` | 8002 | gpt-5.2 | `AGENT_TEMPERATURE=0.3` |
| `agent3-sentiment` | 8003 | gpt-4o-mini | — |

- **Build context**: Parent directory (`..`) so the shared module is available.
- **Health checks**: 30-second interval on `/health`.
- **Restart policy**: `unless-stopped` for automatic recovery.
