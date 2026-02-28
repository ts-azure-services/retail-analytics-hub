"""
Sweep report: rank parameter combinations by data volume and variety.

Queries the local DuckDB after sweep runs to show which scenarios
produced the richest datasets for ML training.

Usage:
    uv run python analysis/sweep_report.py                # all sweeps
    uv run python analysis/sweep_report.py --sweep conversion
    uv run python analysis/sweep_report.py --top 5
"""

import argparse
import json
import sys
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_DB_PATH = str(REPO_ROOT / "local_postgres.duckdb")

# Detail tables per workflow type — used for row-count volume metrics
DETAIL_TABLES = {
    "omnichannel": ["customer_journeys", "order_metrics", "hourly_demand"],
    "inventory": ["inventory_events", "supplier_deliveries", "inventory_snapshots"],
    "engagement": ["engagement_events", "customer_snapshots", "campaign_interactions"],
}


def connect():
    return duckdb.connect(POSTGRES_DB_PATH, read_only=True)


# ------------------------------------------------------------------
#  Discover which sweeps have been run
# ------------------------------------------------------------------

def get_available_sweeps(conn) -> list[dict]:
    """Return list of sweep prefixes with scenario counts."""
    rows = conn.execute("""
        SELECT
            CASE
                WHEN scenario_id LIKE '%\\_%' ESCAPE '\\'
                THEN regexp_replace(scenario_id, '_\\d+$', '')
                ELSE scenario_id
            END AS sweep_prefix,
            workflow_type,
            COUNT(*) AS n_scenarios,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS n_completed,
            MIN(run_timestamp) AS first_run,
            MAX(run_timestamp) AS last_run
        FROM simulation_scenarios
        GROUP BY sweep_prefix, workflow_type
        ORDER BY last_run DESC
    """).fetchall()

    return [
        {
            "sweep": r[0],
            "workflow_type": r[1],
            "n_scenarios": r[2],
            "n_completed": r[3],
            "first_run": r[4],
            "last_run": r[5],
        }
        for r in rows
    ]


# ------------------------------------------------------------------
#  Volume report: row counts across detail tables
# ------------------------------------------------------------------

def _table_exists(conn, table_name: str) -> bool:
    result = conn.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
        (table_name,),
    ).fetchone()
    return result[0] > 0


def volume_report(conn, sweep_prefix: str, workflow_type: str, top_n: int):
    """Rank scenarios by total rows produced across detail tables."""

    tables = DETAIL_TABLES.get(workflow_type, [])
    if not tables:
        return []

    # Build a UNION ALL query that counts rows per scenario across all tables
    parts = []
    for tbl in tables:
        if not _table_exists(conn, tbl):
            continue
        parts.append(
            f"SELECT scenario_id, '{tbl}' AS tbl, COUNT(*) AS row_count "
            f"FROM {tbl} WHERE scenario_id LIKE '{sweep_prefix}%' GROUP BY scenario_id"
        )

    if not parts:
        return []

    union_sql = " UNION ALL ".join(parts)

    rows = conn.execute(f"""
        WITH detail_counts AS ({union_sql})
        SELECT
            d.scenario_id,
            SUM(d.row_count) AS total_rows,
            COUNT(DISTINCT d.tbl) AS tables_populated,
            s.config_json
        FROM detail_counts d
        JOIN simulation_scenarios s ON s.scenario_id = d.scenario_id
        GROUP BY d.scenario_id, s.config_json
        ORDER BY total_rows DESC
        LIMIT {top_n}
    """).fetchall()

    return rows


def per_table_breakdown(conn, sweep_prefix: str, workflow_type: str):
    """Per-table row count summary across all scenarios in a sweep."""
    tables = DETAIL_TABLES.get(workflow_type, [])
    results = {}
    for tbl in tables:
        if not _table_exists(conn, tbl):
            continue
        row = conn.execute(
            f"SELECT COUNT(*) FROM {tbl} WHERE scenario_id LIKE ?",
            (f"{sweep_prefix}%",),
        ).fetchone()
        results[tbl] = row[0]
    return results


# ------------------------------------------------------------------
#  Variety report: distinct values in key columns
# ------------------------------------------------------------------

VARIETY_QUERIES = {
    "omnichannel": {
        "channels": (
            "customer_journeys",
            "SELECT COUNT(DISTINCT channel) FROM customer_journeys WHERE scenario_id = ?",
        ),
        "abandonment_reasons": (
            "customer_journeys",
            "SELECT COUNT(DISTINCT abandonment_reason) FROM customer_journeys "
            "WHERE scenario_id = ? AND abandonment_reason IS NOT NULL",
        ),
        "hours_active": (
            "hourly_demand",
            "SELECT COUNT(DISTINCT hour_of_day) FROM hourly_demand WHERE scenario_id = ?",
        ),
        "outcome_types": (
            "customer_journeys",
            "SELECT COUNT(DISTINCT CASE "
            "  WHEN completed THEN 'completed' "
            "  WHEN abandoned AND payment_failed THEN 'payment_failed' "
            "  WHEN abandoned THEN 'abandoned' "
            "  ELSE 'in_progress' END) "
            "FROM customer_journeys WHERE scenario_id = ?",
        ),
    },
    "inventory": {
        "event_types": (
            "inventory_events",
            "SELECT COUNT(DISTINCT event_type) FROM inventory_events WHERE scenario_id = ?",
        ),
        "sku_count": (
            "inventory_events",
            "SELECT COUNT(DISTINCT sku) FROM inventory_events WHERE scenario_id = ?",
        ),
        "locations": (
            "inventory_events",
            "SELECT COUNT(DISTINCT location) FROM inventory_events WHERE scenario_id = ?",
        ),
        "suppliers": (
            "supplier_deliveries",
            "SELECT COUNT(DISTINCT supplier_id) FROM supplier_deliveries WHERE scenario_id = ?",
        ),
    },
    "engagement": {
        "event_types": (
            "engagement_events",
            "SELECT COUNT(DISTINCT event_type) FROM engagement_events WHERE scenario_id = ?",
        ),
        "segments": (
            "customer_snapshots",
            "SELECT COUNT(DISTINCT rfm_segment) FROM customer_snapshots WHERE scenario_id = ?",
        ),
        "value_tiers": (
            "engagement_events",
            "SELECT COUNT(DISTINCT value_tier) FROM engagement_events WHERE scenario_id = ?",
        ),
        "campaign_types": (
            "campaign_interactions",
            "SELECT COUNT(DISTINCT campaign_type) FROM campaign_interactions WHERE scenario_id = ?",
        ),
    },
}


def variety_report(conn, sweep_prefix: str, workflow_type: str, top_n: int):
    """Rank scenarios by diversity of data produced."""

    queries = VARIETY_QUERIES.get(workflow_type, {})
    if not queries:
        return []

    # Get all completed scenarios in this sweep
    scenarios = conn.execute(
        "SELECT scenario_id, config_json FROM simulation_scenarios "
        "WHERE scenario_id LIKE ? AND status = 'completed'",
        (f"{sweep_prefix}%",),
    ).fetchall()

    scored = []
    for scenario_id, config_json in scenarios:
        variety_score = 0
        detail = {}
        for metric_name, (tbl, sql) in queries.items():
            if not _table_exists(conn, tbl):
                continue
            row = conn.execute(sql, (scenario_id,)).fetchone()
            val = row[0] if row else 0
            detail[metric_name] = val
            variety_score += val

        scored.append((scenario_id, variety_score, detail, config_json))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_n]


# ------------------------------------------------------------------
#  Scenario-level summary metrics (from simulation_scenarios table)
# ------------------------------------------------------------------

def scenario_summary(conn, sweep_prefix: str, workflow_type: str, top_n: int):
    """Pull top scenarios by primary KPI per workflow type."""

    if workflow_type == "omnichannel":
        order_col = "total_revenue"
        cols = "total_customers, total_orders, total_revenue, conversion_rate"
    elif workflow_type == "inventory":
        order_col = "fill_rate"
        cols = "stockout_count, fill_rate, avg_lead_time"
    elif workflow_type == "engagement":
        order_col = "avg_clv"
        cols = "total_customers, churn_rate, campaign_response_rate, avg_clv"
    else:
        return []

    rows = conn.execute(
        f"SELECT scenario_id, {cols}, config_json "
        f"FROM simulation_scenarios "
        f"WHERE scenario_id LIKE ? AND status = 'completed' "
        f"ORDER BY {order_col} DESC NULLS LAST "
        f"LIMIT {top_n}",
        (f"{sweep_prefix}%",),
    ).fetchall()

    return rows


# ------------------------------------------------------------------
#  Pretty-print helpers
# ------------------------------------------------------------------

def _extract_params(config_json) -> dict:
    """Pull the swept parameters out of config_json."""
    if config_json is None:
        return {}
    if isinstance(config_json, str):
        config = json.loads(config_json)
    else:
        config = config_json
    return config.get("parameters", config)


def _fmt_params(params: dict, max_width: int = 60) -> str:
    """Format parameter dict as a compact string."""
    parts = []
    for k, v in params.items():
        if k.startswith("_"):
            continue
        if isinstance(v, float):
            parts.append(f"{k}={v:.3g}")
        else:
            parts.append(f"{k}={v}")
    out = ", ".join(parts)
    if len(out) > max_width:
        out = out[:max_width - 3] + "..."
    return out


def _hr(char="=", width=80):
    print(char * width)


def _section(title: str):
    print()
    _hr()
    print(f"  {title}")
    _hr()


# ------------------------------------------------------------------
#  Main report
# ------------------------------------------------------------------

def print_report(sweep_filter: str | None, top_n: int):
    conn = connect()

    sweeps = get_available_sweeps(conn)
    if not sweeps:
        print("No sweep data found. Run some sweeps first (e.g. make run-sweep-conversion).")
        conn.close()
        return

    # Filter to requested sweep if given
    if sweep_filter:
        sweeps = [s for s in sweeps if sweep_filter in s["sweep"]]
        if not sweeps:
            print(f"No sweep data found matching '{sweep_filter}'.")
            conn.close()
            return

    # Overview
    _section("SWEEP DATA OVERVIEW")
    print(f"  {'Sweep':<30} {'Workflow':<14} {'Scenarios':>10} {'Completed':>10}  Last Run")
    print(f"  {'-'*30} {'-'*14} {'-'*10} {'-'*10}  {'-'*19}")
    for s in sweeps:
        print(
            f"  {s['sweep']:<30} {s['workflow_type']:<14} "
            f"{s['n_scenarios']:>10} {s['n_completed']:>10}  "
            f"{s['last_run']}"
        )

    # Per-sweep detailed reports
    for s in sweeps:
        prefix = s["sweep"]
        wtype = s["workflow_type"]

        _section(f"SWEEP: {prefix.upper()}  ({wtype})")

        # Table breakdown
        tbl_counts = per_table_breakdown(conn, prefix, wtype)
        if tbl_counts:
            total = sum(tbl_counts.values())
            print(f"\n  Detail table row counts (total: {total:,}):")
            for tbl, cnt in tbl_counts.items():
                print(f"    {tbl:<30} {cnt:>10,} rows")

        # Volume ranking
        vol = volume_report(conn, prefix, wtype, top_n)
        if vol:
            print(f"\n  TOP {len(vol)} SCENARIOS BY DATA VOLUME:")
            print(f"  {'#':<4} {'Scenario':<28} {'Total Rows':>12} {'Tables':>8}  Parameters")
            print(f"  {'-'*4} {'-'*28} {'-'*12} {'-'*8}  {'-'*40}")
            for i, (sid, total_rows, n_tables, cfg) in enumerate(vol, 1):
                params = _extract_params(cfg)
                print(
                    f"  {i:<4} {sid:<28} {total_rows:>12,} {n_tables:>8}  "
                    f"{_fmt_params(params)}"
                )

        # Variety ranking
        var = variety_report(conn, prefix, wtype, top_n)
        if var:
            print(f"\n  TOP {len(var)} SCENARIOS BY DATA VARIETY:")
            detail_keys = list(var[0][2].keys()) if var else []
            header_detail = "  ".join(f"{k:>12}" for k in detail_keys)
            print(f"  {'#':<4} {'Scenario':<28} {'Score':>8}  {header_detail}")
            print(f"  {'-'*4} {'-'*28} {'-'*8}  {'  '.join('-'*12 for _ in detail_keys)}")
            for i, (sid, score, detail, cfg) in enumerate(var, 1):
                detail_vals = "  ".join(f"{detail.get(k, 0):>12}" for k in detail_keys)
                print(f"  {i:<4} {sid:<28} {score:>8}  {detail_vals}")
            # Show params for #1
            if var:
                params = _extract_params(var[0][3])
                print(f"\n  Best variety params: {_fmt_params(params, max_width=100)}")

        # Scenario KPI summary
        summary = scenario_summary(conn, prefix, wtype, top_n)
        if summary:
            print(f"\n  TOP {len(summary)} SCENARIOS BY PRIMARY KPI:")
            if wtype == "omnichannel":
                print(f"  {'#':<4} {'Scenario':<28} {'Customers':>10} {'Orders':>8} {'Revenue':>12} {'Conv%':>8}")
                print(f"  {'-'*4} {'-'*28} {'-'*10} {'-'*8} {'-'*12} {'-'*8}")
                for i, row in enumerate(summary, 1):
                    sid, cust, orders, rev, conv, _ = row
                    print(
                        f"  {i:<4} {sid:<28} {cust or 0:>10,} {orders or 0:>8,} "
                        f"${rev or 0:>11,.2f} {conv or 0:>7.1f}%"
                    )
            elif wtype == "inventory":
                print(f"  {'#':<4} {'Scenario':<28} {'Stockouts':>10} {'Fill%':>8} {'AvgLead':>10}")
                print(f"  {'-'*4} {'-'*28} {'-'*10} {'-'*8} {'-'*10}")
                for i, row in enumerate(summary, 1):
                    sid, stockouts, fill, lead, _ = row
                    print(
                        f"  {i:<4} {sid:<28} {stockouts or 0:>10,} "
                        f"{fill or 0:>7.1f}% {lead or 0:>9.1f}h"
                    )
            elif wtype == "engagement":
                print(f"  {'#':<4} {'Scenario':<28} {'Customers':>10} {'Churn%':>8} {'Response%':>10} {'AvgCLV':>10}")
                print(f"  {'-'*4} {'-'*28} {'-'*10} {'-'*8} {'-'*10} {'-'*10}")
                for i, row in enumerate(summary, 1):
                    sid, cust, churn, resp, clv, _ = row
                    print(
                        f"  {i:<4} {sid:<28} {cust or 0:>10,} "
                        f"{churn or 0:>7.1f}% {resp or 0:>9.1f}% ${clv or 0:>9,.2f}"
                    )

    print()
    _hr()
    print("  Report complete.")
    _hr()
    print()

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Sweep data volume & variety report")
    parser.add_argument("--sweep", type=str, default=None, help="Filter to a specific sweep name")
    parser.add_argument("--top", type=int, default=10, help="Number of top scenarios to show (default: 10)")
    args = parser.parse_args()

    print_report(args.sweep, args.top)


if __name__ == "__main__":
    main()
