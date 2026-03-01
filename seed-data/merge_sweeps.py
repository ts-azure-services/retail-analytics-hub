"""
Merge sweep-isolated DuckDB files back into the main databases.

Reads each sweep's postgres/cosmos DuckDB from sweeps/ and merges
ML/event tables into the main local_postgres.duckdb and local_cosmos.duckdb.

Only merges ML training tables (not seed/transactional data).

Usage:
    uv run seed-data/merge_sweeps.py
    uv run seed-data/merge_sweeps.py --dry-run
    uv run seed-data/merge_sweeps.py --sweeps-dir sweeps
"""

import argparse
import glob
import os
import sys
from pathlib import Path

import duckdb

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_POSTGRES_DB = str(REPO_ROOT / "local_postgres.duckdb")
MAIN_COSMOS_DB = str(REPO_ROOT / "local_cosmos.duckdb")
DEFAULT_SWEEPS_DIR = str(REPO_ROOT / "sweeps")

# ---------------------------------------------------------------------------
# Tables to merge (ML / sweep-generated only, not seed data)
# ---------------------------------------------------------------------------
POSTGRES_ML_TABLES = [
    "simulation_scenarios",
    "customer_journeys",
    "hourly_demand",
    "order_metrics",
    "inventory_events",
    "supplier_deliveries",
    "inventory_snapshots",
    "engagement_events",
    "customer_snapshots",
    "campaign_interactions",
]

COSMOS_EVENT_CONTAINERS = [
    "WorkflowEvents",
    "InventoryEvents",
    "EngagementEvents",
]


# Colors for output (reuse pattern from validate_data.py)
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'


def sweep_has_table(conn, table_name):
    """Check if a table exists in the attached 'sweep' database."""
    result = conn.execute(
        "SELECT COUNT(*) FROM duckdb_tables() "
        "WHERE database_name = 'sweep' AND table_name = ?",
        [table_name],
    ).fetchone()
    return result[0] > 0


def main_has_table(conn, table_name):
    """Check if a table exists in the main (opening) database."""
    db_name = conn.execute(
        "SELECT current_database()"
    ).fetchone()[0]
    result = conn.execute(
        "SELECT COUNT(*) FROM duckdb_tables() "
        "WHERE database_name = ? AND table_name = ?",
        [db_name, table_name],
    ).fetchone()
    return result[0] > 0


def ensure_table_from_sweep(conn, table_name):
    """Create a table in the main DB using the DDL from the sweep DB."""
    ddl = conn.execute(
        "SELECT sql FROM duckdb_tables() "
        "WHERE database_name = 'sweep' AND table_name = ?",
        [table_name],
    ).fetchone()
    if ddl and ddl[0]:
        conn.execute(ddl[0])
        return True
    return False


def merge_postgres_sweep(main_conn, sweep_path, dry_run=False):
    """Merge ML tables from a sweep postgres DB into the main DB."""
    sweep_name = Path(sweep_path).stem.replace("_postgres", "")
    print(f"\n  {Colors.CYAN}{sweep_name}{Colors.END} ({Path(sweep_path).name})")

    main_conn.execute(f"ATTACH '{sweep_path}' AS sweep (READ_ONLY)")

    total_merged = 0
    for table in POSTGRES_ML_TABLES:
        if not sweep_has_table(main_conn, table):
            continue

        count = main_conn.execute(
            f"SELECT COUNT(*) FROM sweep.{table}"
        ).fetchone()[0]
        if count == 0:
            continue

        if dry_run:
            print(f"    {table}: {Colors.YELLOW}{count} rows to merge{Colors.END}")
            total_merged += count
        else:
            # Create the table in main DB if it doesn't exist yet
            if not main_has_table(main_conn, table):
                ensure_table_from_sweep(main_conn, table)

            before = main_conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            main_conn.execute(
                f"INSERT INTO {table} SELECT * FROM sweep.{table} "
                f"ON CONFLICT DO NOTHING"
            )
            after = main_conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            added = after - before
            if added > 0:
                print(f"    {table}: {Colors.GREEN}+{added}{Colors.END} new rows (of {count} in sweep)")
            else:
                print(f"    {table}: 0 new rows ({count} already present)")
            total_merged += added

    main_conn.execute("DETACH sweep")
    return total_merged


def merge_cosmos_sweep(main_conn, sweep_path, dry_run=False):
    """Merge event containers from a sweep cosmos DB into the main DB."""
    sweep_name = Path(sweep_path).stem.replace("_cosmos", "")
    print(f"\n  {Colors.CYAN}{sweep_name}{Colors.END} ({Path(sweep_path).name})")

    main_conn.execute(f"ATTACH '{sweep_path}' AS sweep (READ_ONLY)")

    total_merged = 0
    for container in COSMOS_EVENT_CONTAINERS:
        if not sweep_has_table(main_conn, container):
            continue

        count = main_conn.execute(
            f'SELECT COUNT(*) FROM sweep."{container}"'
        ).fetchone()[0]

        # Subtract seed data: count only rows whose id does NOT exist in main
        if main_has_table(main_conn, container):
            new_count = main_conn.execute(
                f'SELECT COUNT(*) FROM sweep."{container}" s '
                f'WHERE NOT EXISTS ('
                f'  SELECT 1 FROM "{container}" m WHERE m.id = s.id'
                f')'
            ).fetchone()[0]
        else:
            new_count = count

        if new_count == 0:
            continue

        if dry_run:
            print(f"    {container}: {Colors.YELLOW}{new_count} rows to merge{Colors.END} ({count} total in sweep)")
            total_merged += new_count
        else:
            before = main_conn.execute(
                f'SELECT COUNT(*) FROM "{container}"'
            ).fetchone()[0]
            main_conn.execute(
                f'INSERT INTO "{container}" '
                f'SELECT * FROM sweep."{container}" '
                f"ON CONFLICT DO NOTHING"
            )
            after = main_conn.execute(
                f'SELECT COUNT(*) FROM "{container}"'
            ).fetchone()[0]
            added = after - before
            if added > 0:
                print(f"    {container}: {Colors.GREEN}+{added}{Colors.END} new rows (of {count} in sweep)")
            else:
                print(f"    {container}: 0 new rows ({count} already present)")
            total_merged += added

    main_conn.execute("DETACH sweep")
    return total_merged


def main():
    parser = argparse.ArgumentParser(
        description="Merge sweep DuckDB files into main databases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Merge all sweep results
  python merge_sweeps.py

  # Preview what would be merged (no writes)
  python merge_sweeps.py --dry-run

  # Use a custom sweeps directory
  python merge_sweeps.py --sweeps-dir /path/to/sweeps
        """,
    )
    parser.add_argument(
        "--sweeps-dir",
        default=DEFAULT_SWEEPS_DIR,
        help=f"Directory containing sweep DBs (default: {DEFAULT_SWEEPS_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be merged without writing",
    )
    args = parser.parse_args()

    sweeps_dir = args.sweeps_dir

    if not os.path.isdir(sweeps_dir):
        print(f"No sweeps directory found at {sweeps_dir}")
        print("Run sweeps first, then merge.")
        sys.exit(1)

    # Find sweep DB files
    pg_files = sorted(glob.glob(os.path.join(sweeps_dir, "*_postgres.duckdb")))
    cosmos_files = sorted(glob.glob(os.path.join(sweeps_dir, "*_cosmos.duckdb")))

    if not pg_files and not cosmos_files:
        print(f"No sweep DB files found in {sweeps_dir}/")
        sys.exit(1)

    mode = f"{Colors.YELLOW}DRY RUN{Colors.END}" if args.dry_run else "LIVE"
    print(f"\n{Colors.BOLD}{'=' * 60}{Colors.END}")
    print(f"{Colors.BOLD}MERGE SWEEP RESULTS ({mode}){Colors.END}")
    print(f"{Colors.BOLD}{'=' * 60}{Colors.END}")
    print(f"Sweeps dir:  {sweeps_dir}")
    print(f"Postgres DBs: {len(pg_files)}")
    print(f"Cosmos DBs:   {len(cosmos_files)}")

    # Merge postgres sweep DBs
    total_pg = 0
    if pg_files:
        if not os.path.exists(MAIN_POSTGRES_DB):
            print(f"\n{Colors.RED}Main postgres DB not found: {MAIN_POSTGRES_DB}{Colors.END}")
            print("Run 'make seed-local' first.")
            sys.exit(1)

        print(f"\n{Colors.BOLD}Postgres ML tables -> {MAIN_POSTGRES_DB}{Colors.END}")
        main_pg = duckdb.connect(MAIN_POSTGRES_DB)
        for sweep_path in pg_files:
            try:
                total_pg += merge_postgres_sweep(main_pg, sweep_path, args.dry_run)
            except Exception as e:
                print(f"    {Colors.RED}ERROR merging {sweep_path}: {e}{Colors.END}")
        main_pg.close()

    # Merge cosmos sweep DBs
    total_cosmos = 0
    if cosmos_files:
        if not os.path.exists(MAIN_COSMOS_DB):
            print(f"\n{Colors.RED}Main cosmos DB not found: {MAIN_COSMOS_DB}{Colors.END}")
            print("Run 'make seed-local' first.")
            sys.exit(1)

        print(f"\n{Colors.BOLD}Cosmos event containers -> {MAIN_COSMOS_DB}{Colors.END}")
        main_cosmos = duckdb.connect(MAIN_COSMOS_DB)
        for sweep_path in cosmos_files:
            try:
                total_cosmos += merge_cosmos_sweep(main_cosmos, sweep_path, args.dry_run)
            except Exception as e:
                print(f"    {Colors.RED}ERROR merging {sweep_path}: {e}{Colors.END}")
        main_cosmos.close()

    # Summary
    action = "to merge" if args.dry_run else "merged"
    print(f"\n{Colors.BOLD}{'=' * 60}{Colors.END}")
    print(f"Postgres rows {action}: {Colors.GREEN}{total_pg}{Colors.END}")
    print(f"Cosmos rows {action}:   {Colors.GREEN}{total_cosmos}{Colors.END}")
    print(f"{Colors.BOLD}{'=' * 60}{Colors.END}\n")


if __name__ == "__main__":
    main()
