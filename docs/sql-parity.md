# SQL Dialect Parity — Postgres/DuckDB ↔ MSSQL ↔ KQL

This document covers the multi-dialect SQL system that allows the dashboard and agents to run locally on DuckDB (Postgres syntax) and in cloud on Fabric SQL endpoint (MSSQL/T-SQL syntax) or Fabric KQL (Kusto Query Language) without query-level code changes at runtime.

---

## Runtime Modes

The platform supports three runtime modes, selected by environment variables:

| Mode | When Active | SQL Dialect | Connection | Used By |
|---|---|---|---|---|
| **Local (DuckDB)** | Default — no Fabric env vars set | Postgres/DuckDB | `duckdb.connect()` read-only | Dashboard + all agents |
| **Fabric SQL** | `FABRIC_SQL_ENDPOINT` is set | MSSQL / T-SQL | `pg.Pool` (dashboard) or `psycopg` (agents) → Fabric SQL endpoint | Dashboard (4 metric tabs) + agents (4 metric tabs + drivers + aggregated + timeseries) |
| **Fabric KQL** | `FABRIC_KQL_CLUSTER_URI` is set | Kusto Query Language | `KustoClient` (azure-kusto-data) | Dashboard (customer-reviews tab) + Agent 3 (reviews tools) |

### Environment Variables

| Variable | Purpose | Example |
|---|---|---|
| `FABRIC_SQL_ENDPOINT` | Fabric SQL endpoint connection string | `Host=xxx.datawarehouse.fabric.microsoft.com;...` |
| `FABRIC_KQL_CLUSTER_URI` | Fabric KQL / Eventhouse cluster URI | `https://xxx.z0.kusto.fabric.microsoft.com` |
| `FABRIC_KQL_DATABASE` | KQL database name | `RetailEventhouse` |
| `FABRIC_KQL_TABLE` | KQL table for customer reviews | `CustomerReviews` |

---

## Dialect Switching — Dashboard

### Detection

`dashboard/server/query-executor.ts` determines the dialect at startup:

```
const dialect: SqlDialect = FABRIC_SQL_ENDPOINT ? 'mssql' : 'postgres'
```

### Query Routing

`dashboard/shared/metric-queries.ts` exports `getQueriesForTab(tabId, dialect)`:

- **`dialect = 'postgres'`** → returns queries from the Postgres `tabQueries` lookup (local dev)
- **`dialect = 'mssql'`** → lazy-loads `metric-queries-mssql.ts` via `getMssqlQueriesForTab(tabId)` (cloud)
- **`tabId = 'customer-reviews'` + `dialect = 'mssql'`** → returns `[]` (reviews use KQL, not Fabric SQL)

### Tab Coverage

| Tab | Tiles | Postgres Source | MSSQL Source | KQL Source |
|---|---|---|---|---|
| Main | 6 | `metric-queries.ts` | `metric-queries-mssql.ts` | — |
| Omnichannel | 8 | `metric-queries.ts` | `metric-queries-mssql.ts` | — |
| Customer Engagement | 8 | `metric-queries.ts` | `metric-queries-mssql.ts` | — |
| Inventory Replenishment | 8 | `metric-queries.ts` | `metric-queries-mssql.ts` | — |
| Customer Reviews | 6 | `metric-queries.ts` | — | `executeReviewsMetricsViaKql()` in `query-executor.ts` |
| **Total** | **36** | | | |

Customer reviews in cloud mode are intercepted before reaching `getQueriesForTab`:

```
if (tabId === 'customer-reviews' && kustoClient) {
    return executeReviewsMetricsViaKql()
}
```

### MSSQL Query File

`dashboard/shared/metric-queries-mssql.ts` contains all 30 MSSQL metric queries (4 tabs × 6–8 metrics). All tables are prefixed with `[_public].` for Fabric-mirrored Postgres tables.

### KQL Queries

Six KQL queries for customer reviews are hardcoded in `query-executor.ts` inside `executeReviewsMetricsViaKql()`. The table name is configurable via `FABRIC_KQL_TABLE`.

---

## Dialect Switching — Agents

### Detection

`agents/shared/db.py` provides the single source of truth:

```python
def use_mssql_dialect() -> bool:
    return bool(get_settings().fabric_sql_endpoint)
```

### Query Routing Per Module

Each agent tool module checks `use_mssql_dialect()` and imports MSSQL variants from `agents/mcp_server/tools/sql_variants/`:

| Module | Postgres SQL | MSSQL SQL | Special Functions |
|---|---|---|---|
| `main_tab.py` | `_METRIC_SQL`, `_DRIVER_SQL` | `get_mssql_metric_sql('main')`, `get_mssql_driver_sql('main')` | — |
| `omnichannel_tab.py` | `_METRIC_SQL`, `_DRIVER_SQL` | `get_mssql_metric_sql('omnichannel')`, `get_mssql_driver_sql('omnichannel')` | `_OMNI_CHANNEL_COMPARISON_SQL` |
| `engagement_tab.py` | `_METRIC_SQL`, `_DRIVER_SQL` | `get_mssql_metric_sql('customer-engagement')`, `get_mssql_driver_sql('customer-engagement')` | `_ENGAGEMENT_SEGMENT_SQL` |
| `inventory_tab.py` | `_METRIC_SQL`, `_DRIVER_SQL` | `get_mssql_metric_sql('inventory-replenishment')`, `get_mssql_driver_sql('inventory-replenishment')` | `_INVENTORY_SKU_SUMMARY_SQL`, `_INVENTORY_CRITICAL_SKUS_SQL` |
| `timeseries.py` | Inline SQL with `LIMIT` | `get_mssql_hourly_demand_sql()`, `get_mssql_demand_by_hour_sql()` | — |
| `aggregated.py` | Inline SQL (11 health checks + 3 correlation queries) | `_AGGREGATED_HEALTH_CHECK`, `_AGGREGATED_CHANNEL_SQL`, `_AGGREGATED_ORDER_SQL`, `_AGGREGATED_CUSTOMER_SQL` | — |
| `reviews_tab.py` | `_METRIC_SQL`, `_DRIVER_SQL` | — | KQL via `_METRIC_KQL`, `_DRIVER_KQL` (when `fabric_kql_cluster_uri` set) |

### MSSQL Variants Module

`agents/mcp_server/tools/sql_variants/__init__.py` contains:

- Metric queries for 4 tabs (30 total)
- Driver queries for 4 tabs (~80 total)
- Extra queries: channel comparison, segment analysis, SKU analysis (summary + critical SKUs)
- Timeseries functions: `get_mssql_hourly_demand_sql()`, `get_mssql_demand_by_hour_sql()`
- Aggregated queries: health check (11 metrics), channel/order/customer correlation queries
- Public API: `get_mssql_metric_sql(tab)`, `get_mssql_driver_sql(tab)`, `MSSQL_QUERIES` dict

### Row Limit Enforcement

`agents/shared/db.py` `execute_query()` auto-appends `LIMIT N` for Postgres/DuckDB queries. For MSSQL, this is skipped — MSSQL queries use `TOP N` where needed:

```python
if "LIMIT" not in sql.upper() and "TOP " not in sql.upper():
    if not use_mssql_dialect():
        sql = f"{sql} LIMIT {settings.query_row_limit}"
```

---

## Syntax Differences — Postgres/DuckDB vs MSSQL

| Feature | Postgres / DuckDB | MSSQL / T-SQL |
|---|---|---|
| Boolean literals | `TRUE`, `FALSE` | `1`, `0` |
| Bare boolean check | `WHERE completed` | `WHERE completed = 1` |
| Conditional count | `COUNT(*) FILTER (WHERE cond)` | `COUNT(CASE WHEN cond THEN 1 END)` |
| Row limit | `LIMIT N` | `TOP N` (after SELECT) |
| Schema prefix | _(none)_ | `[_public].` (Fabric-mirrored tables) |
| AVG on integers | Returns float | **Truncates to integer** — requires `CAST(col AS FLOAT)` |
| Standard deviation | `STDDEV(col)` | `STDEV(col)` (sample) / `STDEVP(col)` (population) |
| Correlation | `CORR(x, y)` | Manual CTE formula (see below) |
| NULL-safe division | `NULLIF(expr, 0)` | `NULLIF(expr, 0)` (same) |

### Integer AVG Truncation

MSSQL's `AVG()` on integer columns performs integer division. All MSSQL queries wrapping integer columns in `AVG()` must use `CAST(col AS FLOAT)`:

```sql
-- Postgres (works correctly)
SELECT AVG(basket_size) AS value FROM customer_journeys

-- MSSQL (wrong — returns 2 instead of 2.90)
SELECT AVG(basket_size) AS value FROM customer_journeys

-- MSSQL (correct)
SELECT AVG(CAST(basket_size AS FLOAT)) AS value FROM customer_journeys
```

Columns requiring this CAST in MSSQL variants:

| Column | Table | Affected Queries |
|---|---|---|
| `basket_size` | `customer_journeys` | 3 driver queries |
| `purchase_count` | `customer_snapshots` | 1 driver query |
| `loyalty_points` | `customer_snapshots` | 1 driver query |
| `unresponsive_count` | `customer_snapshots` | 2 driver queries |
| `daily_demand` | `inventory_snapshots` | 1 metric + 1 driver query |
| `quantity_on_hand` | `inventory_snapshots` | 1 metric query (turnover) |
| `satisfaction_rating` | `support_tickets` | 1 metric query |

### CORR Formula

MSSQL lacks a built-in `CORR()` function. The equivalent uses a CTE to ensure consistent row sets:

```sql
-- Postgres
SELECT CORR(order_quantity, actual_lead_time_days) AS correlation
FROM supplier_deliveries

-- MSSQL equivalent
WITH pairs AS (
    SELECT CAST(order_quantity AS FLOAT) AS x,
           CAST(actual_lead_time_days AS FLOAT) AS y
    FROM [_public].supplier_deliveries
    WHERE order_quantity IS NOT NULL
      AND actual_lead_time_days IS NOT NULL
)
SELECT (AVG(x * y) - AVG(x) * AVG(y))
     / NULLIF(STDEVP(x) * STDEVP(y), 0) AS correlation
FROM pairs
```

Key details:
- Uses `STDEVP` (population) not `STDEV` (sample) to match Postgres `CORR` behavior
- CTE filters NULLs first so all aggregates operate on the same row set
- `AVG(x * y) - AVG(x) * AVG(y)` computes population covariance

---

## SQL Parity Test

### Overview

`tests/sql_parity_test.py` validates that all MSSQL translations produce equivalent results to the Postgres/DuckDB originals. It runs against a local azure-sql-edge container.

### Infrastructure

- **Container**: `mcr.microsoft.com/azure-sql-edge:latest` (ARM64/AMD64)
- **Docker Compose**: `tests/docker-compose-sqlserver.yml`
- **Health check**: `bash -c 'echo > /dev/tcp/localhost/1433'`
- **Database**: `parity_test` on `localhost:1433` (SA password in compose file)

### Data Pipeline

1. Connect to DuckDB (`local_postgres.duckdb`, `event_hubs.duckdb`)
2. Connect to azure-sql-edge, create `parity_test` database
3. Export all tables from DuckDB → MSSQL using multi-row `INSERT VALUES` (900 rows per statement, `fetchmany(5000)` streaming)
4. Verify row counts match between DuckDB and MSSQL — re-export on mismatch

### What's Tested

| Category | Count | Comparison Method |
|---|---|---|
| Dashboard metrics (5 tabs) | 36 | Float value within 1% tolerance |
| Agent driver queries (4 tabs) | 61 | Row count match + single-value comparison |
| Aggregated health check | 11 | Float value within 1% tolerance |
| **Total** | **108** | |

### Running

```
make sql-parity-test
```

This handles container lifecycle (port conflict detection, start, test, teardown) and generates `tests/parity-report.json`.

### Report Format

```json
{
  "dashboard_metrics": { "passed": 36, "failed": 0 },
  "agent_drivers": { "passed": 61, "failed": 0 },
  "aggregated": { "passed": 11, "failed": 0 },
  "total_passed": 108,
  "total_failed": 0,
  "total": 108,
  "status": "PASS"
}
```

---

## File Inventory

| File | Purpose |
|---|---|
| `dashboard/shared/metric-queries.ts` | Postgres/DuckDB dashboard metric queries (36) + dialect router |
| `dashboard/shared/metric-queries-mssql.ts` | MSSQL dashboard metric queries (30, excl. customer reviews) |
| `dashboard/server/query-executor.ts` | Dashboard query executor — dialect selection, KQL client, query dispatch |
| `agents/shared/db.py` | Agent DB layer — `use_mssql_dialect()`, `execute_query()` with row limit logic |
| `agents/shared/config.py` | Agent settings — `fabric_sql_endpoint`, `fabric_kql_*` variables |
| `agents/mcp_server/tools/sql_variants/__init__.py` | All MSSQL agent queries — metrics, drivers, extras, timeseries, aggregated |
| `agents/mcp_server/tools/main_tab.py` | Main tab — Postgres SQL + dialect switch |
| `agents/mcp_server/tools/omnichannel_tab.py` | Omnichannel tab — Postgres SQL + dialect switch |
| `agents/mcp_server/tools/engagement_tab.py` | Engagement tab — Postgres SQL + dialect switch |
| `agents/mcp_server/tools/inventory_tab.py` | Inventory tab — Postgres SQL + dialect switch |
| `agents/mcp_server/tools/timeseries.py` | Timeseries — Postgres SQL + dialect switch |
| `agents/mcp_server/tools/aggregated.py` | Cross-tab health check + correlation — Postgres SQL + dialect switch |
| `agents/mcp_server/tools/reviews_tab.py` | Customer reviews — Postgres SQL + KQL switch |
| `tests/sql_parity_test.py` | Parity test runner (108 queries) |
| `tests/docker-compose-sqlserver.yml` | azure-sql-edge container for parity testing |
| `tests/parity-report.json` | Last parity test result |

---

## Adding a New Metric

When adding a new metric query:

1. **Add the Postgres/DuckDB query** in the relevant tab module (`_METRIC_SQL` or `_DRIVER_SQL`) and in `metric-queries.ts` (dashboard)
2. **Add the MSSQL translation** in `sql_variants/__init__.py` and `metric-queries-mssql.ts`
   - Replace `TRUE`/`FALSE` with `1`/`0`
   - Replace `FILTER (WHERE ...)` with `CASE WHEN ... THEN 1 END`
   - Replace `LIMIT N` with `TOP N`
   - Add `CAST(col AS FLOAT)` around any integer column used in `AVG()`
   - Replace `STDDEV` with `STDEV`, `CORR` with the CTE formula
   - Prefix all tables with `[_public].`
3. **Add to parity test** — Postgres version in `DASHBOARD_POSTGRES_QUERIES` or `AGENT_DRIVER_POSTGRES`, MSSQL version imported from `sql_variants` (auto-stripped of `[_public].`)
4. **If customer reviews** — add KQL variant using `summarize`, `countif()`, `isnotnull()` syntax
5. **Run `make sql-parity-test`** to verify parity
