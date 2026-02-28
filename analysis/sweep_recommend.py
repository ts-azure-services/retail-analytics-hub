"""
Sweep recommendation engine: score scenarios and recommend config updates.

Reads sweep results from DuckDB, scores each scenario by a weighted
composite of data volume, data variety, and primary KPI, then produces
ranked recommendations.  For each swept parameter the engine determines
whether to recommend a fixed value (top scenarios converge) or a range
(top scenarios span diverse values that all produce good data).

Usage:
    uv run python analysis/sweep_recommend.py
    uv run python analysis/sweep_recommend.py --top 5
    uv run python analysis/sweep_recommend.py --weights 0.3,0.3,0.4
    uv run python analysis/sweep_recommend.py --output recommendations.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import duckdb

# Re-use helpers from sweep_report
from sweep_report import (
    DETAIL_TABLES,
    POSTGRES_DB_PATH,
    VARIETY_QUERIES,
    _extract_params,
    _fmt_params,
    _table_exists,
    connect,
    get_available_sweeps,
)

SWEEP_WORKFLOW_MAP = {
    "conversion": "omnichannel",
    "demand": "omnichannel",
    "fulfillment": "omnichannel",
    "inventory_supply": "inventory",
    "inventory_policy": "inventory",
    "inventory_demand": "inventory",
    "engagement_campaign": "engagement",
    "engagement_retention": "engagement",
    "engagement_loyalty": "engagement",
}

# Map sweep param names to the config section they belong to
PARAM_SECTION_MAP = {
    # DistributionConfig
    "abandonment_rate_online": "distributions",
    "abandonment_rate_in_store": "distributions",
    "payment_failure_rate": "distributions",
    "arrival_rate_online": "distributions",
    "arrival_rate_in_store": "distributions",
    "basket_size_mean": "distributions",
    "fulfillment_delay_max": "distributions",
    "service_time_packing_mode": "distributions",
    "bopis_prep_time_mode": "distributions",
    # InventoryAssumptions
    "daily_shrinkage_rate": "inventory",
    # EngagementAssumptions
    "base_email_response_rate": "engagement",
    "vip_response_boost": "engagement",
    "click_to_conversion_rate": "engagement",
    "retention_response_rate": "engagement",
    "churned_threshold_days": "engagement",
    "lapsed_threshold_days": "engagement",
    "points_per_dollar": "engagement",
    "redemption_threshold": "engagement",
    "points_to_dollar_ratio": "engagement",
}


# ------------------------------------------------------------------
#  Scoring helpers
# ------------------------------------------------------------------

def _volume_score(conn, scenario_id: str, workflow_type: str) -> float:
    """Count total rows across detail tables for a scenario."""
    tables = DETAIL_TABLES.get(workflow_type, [])
    total = 0
    for tbl in tables:
        if not _table_exists(conn, tbl):
            continue
        row = conn.execute(
            f"SELECT COUNT(*) FROM {tbl} WHERE scenario_id = ?",
            (scenario_id,),
        ).fetchone()
        total += row[0] if row else 0
    return float(total)


def _variety_score(conn, scenario_id: str, workflow_type: str) -> float:
    """Sum of distinct value counts across variety dimensions."""
    queries = VARIETY_QUERIES.get(workflow_type, {})
    total = 0
    for _, (tbl, sql) in queries.items():
        if not _table_exists(conn, tbl):
            continue
        row = conn.execute(sql, (scenario_id,)).fetchone()
        total += row[0] if row else 0
    return float(total)


def _kpi_score(conn, scenario_id: str, workflow_type: str) -> float:
    """Primary KPI value for a scenario."""
    if workflow_type == "omnichannel":
        col = "total_revenue"
    elif workflow_type == "inventory":
        col = "fill_rate"
    elif workflow_type == "engagement":
        col = "avg_clv"
    else:
        return 0.0

    row = conn.execute(
        f"SELECT {col} FROM simulation_scenarios WHERE scenario_id = ?",
        (scenario_id,),
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0


def _normalize(values: list[float]) -> list[float]:
    """Min-max normalize a list of floats to 0-1."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [1.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


# ------------------------------------------------------------------
#  Recommendation logic
# ------------------------------------------------------------------

def score_sweep(
    conn,
    sweep_prefix: str,
    workflow_type: str,
    volume_weight: float = 0.3,
    variety_weight: float = 0.3,
    kpi_weight: float = 0.4,
) -> list[dict]:
    """Score and rank all completed scenarios in a sweep."""

    scenarios = conn.execute(
        "SELECT scenario_id, config_json FROM simulation_scenarios "
        "WHERE scenario_id LIKE ? AND status = 'completed'",
        (f"{sweep_prefix}%",),
    ).fetchall()

    if not scenarios:
        return []

    raw: list[dict] = []
    for scenario_id, config_json in scenarios:
        params = _extract_params(config_json)
        raw.append({
            "scenario_id": scenario_id,
            "params": params,
            "volume": _volume_score(conn, scenario_id, workflow_type),
            "variety": _variety_score(conn, scenario_id, workflow_type),
            "kpi": _kpi_score(conn, scenario_id, workflow_type),
        })

    # Normalize each dimension
    vol_norm = _normalize([r["volume"] for r in raw])
    var_norm = _normalize([r["variety"] for r in raw])
    kpi_norm = _normalize([r["kpi"] for r in raw])

    for i, r in enumerate(raw):
        r["volume_norm"] = vol_norm[i]
        r["variety_norm"] = var_norm[i]
        r["kpi_norm"] = kpi_norm[i]
        r["composite"] = (
            volume_weight * vol_norm[i]
            + variety_weight * var_norm[i]
            + kpi_weight * kpi_norm[i]
        )

    raw.sort(key=lambda x: x["composite"], reverse=True)
    return raw


def recommend_params(scored: list[dict], top_n: int = 5) -> dict[str, Any]:
    """Analyze top scenarios and recommend param values.

    Returns dict of param_name -> value (fixed) or [min, max] (range).
    """
    top = scored[:top_n]
    if not top:
        return {}

    # Collect values per param across top scenarios
    param_values: dict[str, list] = {}
    for entry in top:
        for k, v in entry["params"].items():
            if k.startswith("_"):
                continue
            param_values.setdefault(k, []).append(v)

    recommendations: dict[str, Any] = {}
    for param, values in param_values.items():
        unique = sorted(set(values))
        if len(unique) == 1:
            # All top scenarios agree on this value
            recommendations[param] = {"type": "fixed", "value": unique[0]}
        else:
            # Top scenarios span a range — recommend the range
            recommendations[param] = {
                "type": "range",
                "min": min(unique),
                "max": max(unique),
                "values_seen": unique,
            }

    return recommendations


# ------------------------------------------------------------------
#  Output
# ------------------------------------------------------------------

def generate_recommendations(
    sweep_filter: str | None = None,
    top_n: int = 5,
    weights: tuple[float, float, float] = (0.3, 0.3, 0.4),
) -> dict:
    """Generate recommendations across all completed sweeps."""
    conn = connect()
    sweeps = get_available_sweeps(conn)

    if sweep_filter:
        sweeps = [s for s in sweeps if sweep_filter in s["sweep"]]

    output: dict = {
        "top_n": top_n,
        "weights": {"volume": weights[0], "variety": weights[1], "kpi": weights[2]},
        "sweeps": {},
    }

    for s in sweeps:
        prefix = s["sweep"]
        wtype = s["workflow_type"]

        scored = score_sweep(conn, prefix, wtype, *weights)
        if not scored:
            continue

        recs = recommend_params(scored, top_n)

        # Group recommendations by config section
        by_section: dict[str, dict] = {}
        for param_name, rec in recs.items():
            section = PARAM_SECTION_MAP.get(param_name, "unknown")
            by_section.setdefault(section, {})[param_name] = rec

        output["sweeps"][prefix] = {
            "workflow_type": wtype,
            "n_scenarios_scored": len(scored),
            "top_scenario": scored[0]["scenario_id"],
            "top_composite_score": round(scored[0]["composite"], 4),
            "top_params": scored[0]["params"],
            "recommendations": recs,
            "recommendations_by_section": by_section,
            "top_n_details": [
                {
                    "scenario_id": e["scenario_id"],
                    "composite": round(e["composite"], 4),
                    "volume": e["volume"],
                    "variety": e["variety"],
                    "kpi": round(e["kpi"], 2),
                    "params": e["params"],
                }
                for e in scored[:top_n]
            ],
        }

    conn.close()
    return output


def print_recommendations(recs: dict):
    """Pretty-print recommendations to console."""
    weights = recs["weights"]
    top_n = recs["top_n"]
    print()
    print("=" * 80)
    print(f"  SWEEP RECOMMENDATIONS  (top {top_n}, weights: vol={weights['volume']}, var={weights['variety']}, kpi={weights['kpi']})")
    print("=" * 80)

    for sweep_name, sweep_data in recs["sweeps"].items():
        print(f"\n  SWEEP: {sweep_name.upper()}  ({sweep_data['workflow_type']})")
        print(f"  Scored {sweep_data['n_scenarios_scored']} scenarios")
        print(f"  Best: {sweep_data['top_scenario']} (composite={sweep_data['top_composite_score']:.4f})")
        print()

        # Top scenarios table
        print(f"  {'#':<4} {'Scenario':<28} {'Composite':>10} {'Volume':>10} {'Variety':>10} {'KPI':>10}")
        print(f"  {'-'*4} {'-'*28} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")
        for i, detail in enumerate(sweep_data["top_n_details"], 1):
            print(
                f"  {i:<4} {detail['scenario_id']:<28} "
                f"{detail['composite']:>10.4f} {detail['volume']:>10.0f} "
                f"{detail['variety']:>10.0f} {detail['kpi']:>10.2f}"
            )

        # Parameter recommendations
        print(f"\n  PARAMETER RECOMMENDATIONS:")
        for param, rec in sweep_data["recommendations"].items():
            section = PARAM_SECTION_MAP.get(param, "?")
            if rec["type"] == "fixed":
                val = rec["value"]
                if isinstance(val, float):
                    print(f"    {section}.{param} = {val:.4g}  (fixed — top scenarios agree)")
                else:
                    print(f"    {section}.{param} = {val}  (fixed — top scenarios agree)")
            else:
                print(
                    f"    {section}.{param} = [{rec['min']}, {rec['max']}]  "
                    f"(range — values: {rec['values_seen']})"
                )

    print()
    print("=" * 80)
    print("  Recommendation complete.")
    print("=" * 80)
    print()


def main():
    parser = argparse.ArgumentParser(description="Generate sweep recommendations")
    parser.add_argument("--sweep", type=str, default=None, help="Filter to a specific sweep")
    parser.add_argument("--top", type=int, default=5, help="Top N scenarios to analyze (default: 5)")
    parser.add_argument(
        "--weights", type=str, default="0.3,0.3,0.4",
        help="Scoring weights: volume,variety,kpi (default: 0.3,0.3,0.4)",
    )
    parser.add_argument("--output", type=str, default=None, help="Write recommendations to JSON file")
    args = parser.parse_args()

    weights = tuple(float(w) for w in args.weights.split(","))
    if len(weights) != 3:
        print("Error: --weights must have exactly 3 comma-separated values")
        sys.exit(1)

    recs = generate_recommendations(args.sweep, args.top, weights)

    if not recs["sweeps"]:
        print("No sweep data found. Run some sweeps first (e.g. make run-sweep-conversion).")
        sys.exit(0)

    print_recommendations(recs)

    if args.output:
        output_path = Path(args.output)
        with open(output_path, "w") as f:
            json.dump(recs, f, indent=2, default=str)
        print(f"Recommendations written to {output_path}")


if __name__ == "__main__":
    main()
