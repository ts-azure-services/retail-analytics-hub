# Testing Spec

This document defines the testing strategy for the retail simulation framework. No tests exist yet — this is a prescriptive spec for what to build.

---

## Table of Contents

- [Approach](#approach)
- [Prerequisites](#prerequisites)
- [Test Categories](#test-categories)
- [Simulation Core](#simulation-core)
- [Parameter Sweeps](#parameter-sweeps)
- [ML Pipeline](#ml-pipeline)
- [Agent System](#agent-system)
- [Sync Pipeline](#sync-pipeline)
- [Seed Data](#seed-data)
- [Dashboard API](#dashboard-api)
- [Analysis Tools](#analysis-tools)
- [Fixture Strategy](#fixture-strategy)
- [Stochastic Output Handling](#stochastic-output-handling)

---

## Approach

Tests validate **structural correctness** — that the right tables are populated, correct columns exist, functions return expected types, and error paths behave predictably. For a stochastic simulation framework, tests assert on shape and constraints rather than exact numeric values.

All Python tests use **pytest** with **pytest-asyncio** for async agent code. Dashboard server tests use the existing Node.js toolchain.

---

## Prerequisites

Add to `pyproject.toml` dependencies:

```toml
[project.optional-dependencies]
test = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

Test directory structure:

```
tests/
├── conftest.py                    # Shared fixtures (temp DBs, configs)
├── simulation/
│   ├── test_config.py
│   ├── test_local_backend.py
│   ├── test_metrics.py
│   ├── test_run_simulation.py
│   └── test_workflows.py
├── sweep/
│   ├── test_config_generator.py
│   ├── test_scenario_tracker.py
│   └── test_sweep_runner.py
├── ml/
│   └── test_data_prep.py
├── agents/
│   ├── test_db.py
│   ├── test_mcp_tools.py
│   ├── test_agent1_executors.py
│   ├── test_agent3_executors.py
│   └── test_agent3_main.py
├── sync/
│   ├── test_export_postgres.py
│   └── test_upload.py
├── seed/
│   └── test_seed_local.py
└── analysis/
    ├── test_sweep_recommend.py
    └── test_config_applier.py
```

---

## Test Categories

| Category | Scope | When to Run |
|----------|-------|-------------|
| **Unit** | Individual functions and classes in isolation | Every commit |
| **Integration** | End-to-end flows (seed → simulate → persist) | Pre-merge |
| **Contract** | API request/response schemas, MCP tool I/O shapes | Every commit |
| **Smoke** | Agent `/health` endpoints on running containers | Post-deploy |

---

## Simulation Core

### Configuration (`tests/simulation/test_config.py`)

Tests for `SimulationConfig`, `_apply_overrides`, and `validate`.

| Test | What to Assert |
|------|---------------|
| Default construction | All dataclass fields have expected default values; nested sub-configs (`DistributionConfig`, `ResourceConfig`, `SLAConfig`, `OmnichannelAssumptions`, `InventoryAssumptions`, `EngagementAssumptions`) are instantiated |
| Override loading — valid file | Write a temp `config_overrides.json` with `{"distributions": {"arrival_rate_online": 99.0}}`, construct `SimulationConfig`, assert `config.distributions.arrival_rate_online == 99.0` |
| Override loading — missing file | No `config_overrides.json` at expected path → config loads with defaults, no exception |
| Override loading — malformed JSON | Write invalid JSON → config loads with defaults, warning logged |
| `_apply_overrides` — unknown section | `{"nonexistent_section": {"field": 1}}` → warning logged, no crash |
| `_apply_overrides` — unknown field | `{"distributions": {"nonexistent_field": 1}}` → warning logged, existing fields unchanged |
| `validate` — local mode | `USE_LOCAL_DB=True` → returns `True` regardless of missing Azure env vars |
| `validate` — cloud mode missing creds | `USE_LOCAL_DB=False` with empty Postgres/Cosmos creds → returns `False` |

### Local Backend (`tests/simulation/test_local_backend.py`)

Tests for `DuckDBPostgresWriter` using a temp DuckDB file.

| Test | What to Assert |
|------|---------------|
| Table creation | Construct writer with temp DB → all 10 ML tables exist (`simulation_scenarios`, `customer_journeys`, `hourly_demand`, `order_metrics`, `inventory_events`, `supplier_deliveries`, `inventory_snapshots`, `engagement_events`, `customer_snapshots`, `campaign_interactions`) |
| Sequence creation | All 6 sequences exist (`orders_order_id_seq`, `order_items_order_item_id_seq`, `payments_payment_id_seq`, `points_transactions_transaction_id_seq`, `returns_return_id_seq`, `purchase_order_lines_po_line_id_seq`) |
| Sequence reset on existing data | Seed orders table with `order_id=500`, re-construct writer → sequence starts at 10000 (above max) |
| `write_order` | Returns an `int` order ID; row exists in `orders` table |
| `write_order` — error path | Invalid data (e.g. missing required column) → returns `None`, no crash |
| `write_order_items` | Returns `True`; items linked to correct `order_id` |
| `write_payment` | Returns an `int` payment ID |
| `update_inventory` | Quantity changes reflected; negative quantity clamps or errors gracefully |
| `_decimal_to_float` | `Decimal("1.50")` → `1.5`; nested dicts/lists traversed; non-Decimal values pass through |

### Metrics Collector (`tests/simulation/test_metrics.py`)

Tests for `MetricsCollector` using in-memory state (no DB needed for most tests).

| Test | What to Assert |
|------|---------------|
| Empty state | `calculate_metrics()` with no recorded events → `total_customers=0`, `conversion_rate=0`, `return_rate=0`, no division-by-zero errors |
| Full journey | Record arrival → browsing → queue → checkout → purchase complete → `calculate_metrics()` returns `total_customers=1`, `conversion_rate=100.0` |
| Abandonment | Record arrival → abandonment("price") → conversion rate = 0, abandonment tracked |
| Payment failure | Record arrival → browsing → payment failure → conversion rate = 0 |
| Mixed journeys | 3 arrivals, 1 complete, 1 abandon, 1 payment fail → `conversion_rate ≈ 33.3` |
| Order metrics | Record order created → fulfillment start → fulfillment complete → delivery → return → `return_rate = 100.0` |
| Unknown customer/order | `_get_journey("nonexistent")` returns `None`; `_get_order(99999)` returns `None` |
| `record_metric` | First call sets value; second call increments |
| `persist_to_db` | With a temp DuckDB, writes rows to `customer_journeys`, `order_metrics`, `hourly_demand`; rows include correct `scenario_id` |
| `export_to_dict` | Returns serializable dict with expected keys |

### Run Simulation (`tests/simulation/test_run_simulation.py`)

Tests for CLI parsing and orchestrator setup.

| Test | What to Assert |
|------|---------------|
| Default CLI args | `--workflow omnichannel`, `--duration 24.0`, `--seed 42` parsed correctly |
| Invalid workflow | `--workflow invalid` raises `SystemExit` |
| Sweep mode dispatch | `--sweep conversion` routes to `run_sweep_mode`, does not enter normal simulation path |
| `SimulationOrchestrator.setup` — validation failure | Config with `validate() == False` → raises `ValueError` |
| Quick simulation — structural | Run `--workflow omnichannel --duration 0.1 --seed 42` against seeded temp DB → completes without exception; at least one table has new rows |

### Workflows (`tests/simulation/test_workflows.py`)

Integration tests for individual workflows. Each test uses a seeded temp DuckDB and runs for a minimal duration (0.1 hours).

| Test | What to Assert |
|------|---------------|
| Omnichannel — completes | `OmnichannelPurchaseWorkflow` runs to completion; `orders` table has rows |
| Omnichannel — empty catalog | No products loaded → workflow runs without crash, no orders created |
| Inventory — completes | `InventoryReplenishmentWorkflow` runs to completion; `purchase_orders` table may have rows |
| Engagement — completes | `CustomerEngagementWorkflow` runs to completion; `customer_stats` or `customer_scores` updated |
| All workflows — completes | `run_all_workflows` with duration 0.1 → no crash, all workflows registered |

---

## Parameter Sweeps

### Config Generator (`tests/sweep/test_config_generator.py`)

| Test | What to Assert |
|------|---------------|
| `SweepConfig.total_scenarios` | `SweepConfig(params=[SweepParameter("a", [1,2]), SweepParameter("b", [3,4,5])])` → `total_scenarios == 6` |
| `total_scenarios` — empty params | No parameters → `total_scenarios == 1` (single baseline) |
| Grid enumeration | Generated scenario list length equals `total_scenarios` |
| Pre-built sweeps | `CONVERSION_SWEEP.total_scenarios == 36` (4 x 3 x 3) |

### Scenario Tracker (`tests/sweep/test_scenario_tracker.py`)

Uses a temp DuckDB.

| Test | What to Assert |
|------|---------------|
| Table creation | `_ensure_table()` creates `simulation_scenarios` with expected columns |
| `start_scenario` | Row inserted with status `running` |
| `complete_scenario` — omnichannel | Updates scenario with omnichannel-specific KPI columns (`total_customers`, `total_orders`, `total_revenue`, `conversion_rate`) |
| `complete_scenario` — inventory | Updates with inventory KPI columns (`stockout_count`, `fill_rate`, `avg_lead_time`) |
| `complete_scenario` — engagement | Updates with engagement KPI columns (`churn_rate`, `campaign_response_rate`, `avg_clv`) |
| `fail_scenario` | Sets status to `failed`, records `error_message` |
| `get_sweep_summary` | Returns dict with `total`, `completed`, `failed` counts |
| Upsert behavior | `start_scenario` with same `scenario_id` twice → single row, updated values |

### Sweep Runner (`tests/sweep/test_sweep_runner.py`)

Integration test using a small sweep (2 scenarios) with temp DBs.

| Test | What to Assert |
|------|---------------|
| `SWEEP_WORKFLOW_MAP` | All 9 sweep names map to valid workflow types (`omnichannel`, `inventory`, `engagement`) |
| Single scenario execution | `_run_single_scenario` with a conversion sweep scenario → scenario tracked as `completed` |
| Scenario isolation | Each scenario gets a fresh `simpy.Environment` — verified by checking environment time resets to 0 |
| Exception handling | Scenario that raises → tracked as `failed`, runner continues to next scenario |
| `run` return value | Returns list of completed scenario IDs |

---

## ML Pipeline

### Data Preparation (`tests/ml/test_data_prep.py`)

Uses a temp DuckDB pre-populated with a few rows in ML tables.

| Test | What to Assert |
|------|---------------|
| `get_conversion_dataset` | Returns DataFrame with columns: `channel`, `arrival_hour`, `day_of_week`, `browsing_duration`, `basket_size`, `queue_wait_time`, `completed` |
| `get_conversion_dataset` — empty table | Returns empty DataFrame with correct columns, no exception |
| `get_order_value_dataset` | Returns DataFrame with `total_amount` column |
| `get_demand_forecast_dataset` | Returns DataFrame with Prophet columns `ds` (datetime) and `y` (numeric) |
| `get_demand_forecast_dataset` — channel filter | `channel="online"` → only online rows |
| `get_stockout_dataset` | Returns DataFrame with `stockout_occurred` column |
| `get_lead_time_dataset` | Returns DataFrame with `actual_lead_time_days` column |
| `get_fulfillment_dataset` | Returns DataFrame with `fulfillment_duration` column |
| `get_scenario_list` | Returns list of scenario IDs matching status and optional workflow filter |
| `_get_connection` — reuse | Second call returns same connection object |
| Scenario ID filtering | Pass specific `scenario_ids` → only those rows returned |

---

## Agent System

### Database Layer (`tests/agents/test_db.py`)

| Test | What to Assert |
|------|---------------|
| `_connect` — valid path | Returns a DuckDB connection; read-only |
| `_connect` — missing file | Raises `FileNotFoundError` |
| `execute_query` — basic | `SELECT 1 AS val` → `[{"val": 1}]` |
| `execute_query` — row limit injection | Query without `LIMIT` → `LIMIT {settings.query_row_limit}` appended |
| `execute_query` — existing LIMIT | Query with `LIMIT 5` → no additional limit injected |
| `execute_query` — existing TOP | Query with `SELECT TOP 10` → no additional limit |
| `execute_query` — error | Invalid SQL → returns `[{"error": "..."}]` |
| Backend routing | `settings.fabric_sql_endpoint` empty → DuckDB path; non-empty → Fabric connection attempted |

### MCP Tools (`tests/agents/test_mcp_tools.py`)

| Test | What to Assert |
|------|---------------|
| `call_tool` — unknown name | Returns `{"error": "Unknown tool: foo. Available: [...]"}` |
| `call_tool` — handler raises | Returns `{"error": "Tool bar failed: ..."}` |
| `get_tool_registry` — singleton | Two calls return same dict object |
| `TAB_TOOL_MAP` — completeness | All keys (`main`, `omnichannel`, `customer-engagement`, `inventory-replenishment`, `customer-reviews`) have `summary`, `drivers`, and `extra` entries |
| `TAB_TOOL_MAP` — tools exist | Every tool name referenced in `TAB_TOOL_MAP` exists in the registry |

### Agent 1 Executors (`tests/agents/test_agent1_executors.py`)

Async tests using `pytest-asyncio`. Mock `call_tool` to return canned tool responses.

| Test | What to Assert |
|------|---------------|
| `prepare_input` | Parses JSON with `message`, `active_tab`, `current_view`, `selected_metric_id`; stores `active_tab` in `_context` |
| `gather_data` — valid intent | Intent with `tab="omnichannel"`, `metric_ids=["revenue"]`, `question_type="general"` → calls summary tool, driver tool for `revenue`, extra tools |
| `gather_data` — intent parse failure | Malformed intent JSON → falls back to `{"tab": active_tab, "metric_ids": [], "question_type": "general"}` |
| `gather_data` — unknown tab | Tab not in `TAB_TOOL_MAP` → falls back to `"main"` tools |
| `gather_data` — tool error propagation | `call_tool` returns `{"error": "..."}` → error dict passed through in gathered data, no crash |
| `extract_output` | Passes through response text unmodified |

### Agent 3 Executors (`tests/agents/test_agent3_executors.py`)

Async tests. Mock `db.update_review_result`.

| Test | What to Assert |
|------|---------------|
| `_parse_json` — raw JSON | `'{"key": "val"}'` → `{"key": "val"}` |
| `_parse_json` — markdown fenced | `` '```json\n{"key": "val"}\n```' `` → `{"key": "val"}` |
| `_parse_json` — invalid | `'not json'` → `{}` |
| `fetch_review` | Stores `review_id` and `review_text` in `_context` |
| `adapt_classification` — valid | Classifier returns `{"sentiment_category": "positive", "sentiment_score": 0.8}` → stored in `_context` |
| `adapt_classification` — parse failure | Invalid JSON from classifier → defaults to `"neutral"`, `0.0` |
| `persist_results` — with review_id | Calls `db.update_review_result` with correct args |
| `persist_results` — no review_id | `_context` has no `review_id` → skips DB write |

### Agent 3 API (`tests/agents/test_agent3_main.py`)

Tests using `httpx.AsyncClient` with FastAPI `TestClient`. Mock the `analyze_review` workflow function.

| Test | What to Assert |
|------|---------------|
| `POST /analyze` — success | Returns `ReviewResponse` with sentiment fields populated |
| `POST /analyze` — workflow exception | Returns `ReviewResponse` with `status="incomplete processing"`, calls `db.mark_error` |
| `POST /retry` | Returns `{"total": N, "succeeded": M, "failed": K}` |
| `GET /health` | Returns 200 with health status |

---

## Sync Pipeline

### Export (`tests/sync/test_export_postgres.py`)

Uses a temp DuckDB with 2 tables seeded with a few rows.

| Test | What to Assert |
|------|---------------|
| Normal export | Creates one `.parquet` file per table in staging directory |
| Parquet contents | Read back with PyArrow → row count matches source table |
| Empty database | Prints "No tables found", creates no files |
| Read-only connection | Export function does not write to the source DB |

### Upload (`tests/sync/test_upload.py`)

Mock `BlobServiceClient` to avoid real Azure calls.

| Test | What to Assert |
|------|---------------|
| Missing connection string | `sys.exit(1)` called |
| Invalid `--only` value | `sys.exit(1)` called |
| Normal upload | `upload_blob` called once per file with `overwrite=True` |
| `--only postgres` | Only `sync/staging/postgres/` files uploaded |
| Empty staging directory | No upload calls, no crash |

---

## Seed Data

### Seed Local (`tests/seed/test_seed_local.py`)

Uses temp DuckDB files.

| Test | What to Assert |
|------|---------------|
| `generate_customers(10)` | Returns 10 dicts; each has `customer_id`, `email`, `first_name`, `last_name` |
| `generate_products(5)` | Returns 5 dicts; each has `sku`, `price` (positive float), `category` |
| `generate_inventory` | Returns entries for each SKU across all locations |
| `seed_postgres_db` | All expected tables created; `customers` has rows; `payments` table exists but is empty |
| `--clean` flag | Existing `.duckdb` files deleted before seeding |
| DDL idempotency | Running seed twice on same DB → no duplicate tables or errors |
| Sequence alignment | Seed order IDs start below 10000; `DuckDBPostgresWriter` sequences start at 10000 → no collision |

---

## Dashboard API

### Server Endpoints (`dashboard/tests/`)

Tests using the Node.js test framework matching the project's toolchain.

| Test | What to Assert |
|------|---------------|
| `GET /api/health` | Returns `{"status": "ok"}` |
| `GET /api/metrics/main` | Returns 200 with metric data |
| `GET /api/metrics/invalid-tab` | Returns 400 |
| `GET /api/reviews` | Returns 200 with review array |
| `GET /api/reviews?filter=positive` | Filter parameter is passed through to query |
| `POST /api/agent1/chat` — agent down | Returns 502 (proxy failure) |
| Agent proxy timeout | 30-second `AbortController` fires → 502 response |

---

## Analysis Tools

### Sweep Recommend (`tests/analysis/test_sweep_recommend.py`)

Uses a temp DuckDB with a few scenario rows.

| Test | What to Assert |
|------|---------------|
| Volume scoring | More rows across detail tables → higher score |
| Variety scoring | More distinct values → higher score |
| Missing tables | `_table_exists` returns `False` → score defaults to 0, no crash |
| `PARAM_SECTION_MAP` completeness | Every parameter from all 9 sweeps has a mapping to a config section |
| Output format | Recommendations JSON has expected structure per sweep |

### Config Applier (`tests/analysis/test_config_applier.py`)

| Test | What to Assert |
|------|---------------|
| Preview mode | `--preview` reads recommendations, prints diff, does **not** write `config_overrides.json` |
| Apply mode | `--apply` writes `config_overrides.json`; file contains valid JSON matching expected structure |
| Workflow filter | `--workflow omnichannel` → only omnichannel overrides extracted |
| Range midpoint | Recommendation with `{"min": 0.1, "max": 0.3}` → override value is `0.2` |
| `get_current_defaults` | Returns dict with keys matching `SECTION_CLASSES` (`distributions`, `omnichannel`, `inventory`, `engagement`) |

---

## Fixture Strategy

### Temp Databases

All tests that need a database use **pytest `tmp_path` fixtures** with ephemeral DuckDB files:

```python
@pytest.fixture
def seeded_postgres_db(tmp_path):
    """Create a minimal DuckDB with seed schema and a few rows."""
    db_path = str(tmp_path / "test_postgres.duckdb")
    conn = duckdb.connect(db_path)
    # Create tables from PG_DDL subset
    # Insert 5 customers, 5 products, 5 inventory rows
    conn.close()
    return db_path
```

No test should read from or write to the real `local_postgres.duckdb`, `local_cosmos.duckdb`, or `event_hubs.duckdb` files at the repo root.

### Minimal Seed Data

Fixtures use small counts to keep tests fast:

| Entity | Test Count | Production Count |
|--------|-----------|-----------------|
| Customers | 5 | 500 |
| Products | 5 | 50 |
| Suppliers | 3 | 50 |
| Inventory | 25 (5 SKUs x 5 locations) | 250 |
| Orders | 5 | 500 |

### Mock LLM Responses

Agent tests mock the `ChatAgent` / `AgentExecutor` layer to return canned JSON strings. Tests never call Azure OpenAI.

```python
@pytest.fixture
def mock_sentiment_response():
    return '{"sentiment_category": "positive", "sentiment_score": 0.85, "key_phrases": ["great taste"], "confidence": 0.9}'
```

### Mock External Services

| Dependency | Mock Strategy |
|------------|--------------|
| Azure OpenAI | Mock `ChatAgent` to return canned text |
| Azure Blob Storage | Mock `BlobServiceClient` |
| Azure CosmosDB | Not tested directly; tests use DuckDB equivalents |
| Azure PostgreSQL | Not tested directly; tests use DuckDB equivalents |
| MCP Server subprocess | Mock `call_tool` function |

---

## Stochastic Output Handling

Simulation workflows use random distributions (Poisson arrivals, exponential service times, uniform selection). Tests handle this by:

1. **Fixed seeds** — All simulation tests use `--seed 42` (or `random.seed(42)` + `np.random.seed(42)`) for reproducibility within a single Python version.

2. **Structural assertions** — Assert on the *shape* of output, not exact values:
   - Table has rows (not "table has exactly 47 rows")
   - Conversion rate is between 0 and 100 (not "conversion rate is 33.3")
   - Order IDs are positive integers
   - All required columns are present

3. **Bound checks** — Where business logic constrains output:
   - `sentiment_score` is between -1.0 and 1.0
   - `basket_size` is a positive integer
   - `fulfillment_duration` is non-negative
   - Sequence-generated IDs are >= 10000

4. **Deterministic sub-components** — Config parsing, JSON serialization, SQL generation, safety override rules, and schema creation are fully deterministic and should have exact assertions.
