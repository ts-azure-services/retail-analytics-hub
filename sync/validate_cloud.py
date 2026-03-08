"""
Compare local DuckDB data against cloud Azure Postgres and Cosmos DB.

Connects to both local DuckDB files and cloud services, pulls table/container
row counts, and reports differences.
"""

import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

import duckdb

from sync.config import LOCAL_POSTGRES_DB, LOCAL_COSMOS_DB

# ---------------------------------------------------------------------------
# Load cloud .env
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]
_CLOUD_ENV = _REPO_ROOT / "infra" / ".env"
if _CLOUD_ENV.exists():
    load_dotenv(_CLOUD_ENV, override=False)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
class C:
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    END = "\033[0m"


def _header(text: str):
    print(f"\n{C.BOLD}{'=' * 64}{C.END}")
    print(f"{C.CYAN}{C.BOLD}{text}{C.END}")
    print(f"{C.BOLD}{'=' * 64}{C.END}\n")


def _row(table: str, local: int, cloud: int):
    diff = cloud - local
    if diff == 0:
        tag = f"{C.GREEN}match{C.END}"
    elif diff > 0:
        tag = f"{C.YELLOW}+{diff} in cloud{C.END}"
    else:
        tag = f"{C.RED}{diff} in cloud{C.END}"
    print(f"  {table:40s}  local {local:>8,}  cloud {cloud:>8,}  {tag}")


# ---------------------------------------------------------------------------
# Local DuckDB counts
# ---------------------------------------------------------------------------
def _local_counts(db_path: str) -> dict[str, int]:
    if not os.path.exists(db_path):
        print(f"  {C.RED}Not found: {db_path}{C.END}")
        return {}
    conn = duckdb.connect(db_path, read_only=True)
    tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
    counts = {}
    for t in tables:
        counts[t] = conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
    conn.close()
    return counts


# ---------------------------------------------------------------------------
# Cloud Postgres counts
# ---------------------------------------------------------------------------
def _cloud_postgres_counts() -> dict[str, int]:
    fqdn = os.environ.get("POSTGRES_FQDN", "")
    db_name = os.environ.get("POSTGRES_DB_NAME", "")
    user = os.environ.get("POSTGRES_ADMIN_LOGIN", "")
    password = os.environ.get("POSTGRES_ADMIN_PASSWORD", "")

    if not all([fqdn, db_name, user, password]):
        print(f"  {C.RED}Missing Postgres env vars (POSTGRES_FQDN, POSTGRES_DB_NAME, etc.){C.END}")
        return {}

    try:
        import psycopg2
        conn = psycopg2.connect(
            host=fqdn, dbname=db_name, user=user, password=password,
            sslmode="require", connect_timeout=10,
        )
    except ImportError:
        try:
            import psycopg
            conn = psycopg.connect(
                host=fqdn, dbname=db_name, user=user, password=password,
                sslmode="require", connect_timeout=10,
            )
        except Exception as e:
            print(f"  {C.RED}Cannot connect to cloud Postgres: {e}{C.END}")
            return {}
    except Exception as e:
        print(f"  {C.RED}Cannot connect to cloud Postgres: {e}{C.END}")
        return {}

    cur = conn.cursor()
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' ORDER BY table_name"
    )
    tables = [r[0] for r in cur.fetchall()]

    counts = {}
    for t in tables:
        cur.execute(f'SELECT count(*) FROM "{t}"')
        counts[t] = cur.fetchone()[0]

    cur.close()
    conn.close()
    return counts


# ---------------------------------------------------------------------------
# Cloud Cosmos counts
# ---------------------------------------------------------------------------
def _cloud_cosmos_counts() -> dict[str, int]:
    endpoint = os.environ.get("COSMOSDB_ENDPOINT", "")
    db_name = os.environ.get("COSMOSDB_DATABASE_NAME", "")

    if not endpoint or not db_name:
        print(f"  {C.RED}Missing Cosmos env vars (COSMOSDB_ENDPOINT, COSMOSDB_DATABASE_NAME){C.END}")
        return {}

    try:
        from azure.cosmos import CosmosClient
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
        client = CosmosClient(url=endpoint, credential=credential)
        database = client.get_database_client(db_name)
    except Exception as e:
        print(f"  {C.RED}Cannot connect to cloud Cosmos DB: {e}{C.END}")
        return {}

    counts = {}
    for container_props in database.list_containers():
        name = container_props["id"]
        container = database.get_container_client(name)
        result = list(container.query_items(
            query="SELECT VALUE COUNT(1) FROM c",
            enable_cross_partition_query=True,
        ))
        counts[name] = result[0] if result else 0

    return counts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _compare(header: str, local: dict[str, int], cloud: dict[str, int]) -> bool:
    """Print comparison table, return True if any differences."""
    _header(header)
    all_keys = sorted(set(local) | set(cloud))
    if not all_keys:
        print("  No tables to compare.")
        return False
    has_diff = False
    for t in all_keys:
        l = local.get(t, 0)
        c = cloud.get(t, 0)
        _row(t, l, c)
        if l != c:
            has_diff = True
    return has_diff


def validate_postgres() -> bool:
    """Compare local Postgres DuckDB vs. cloud Azure Postgres."""
    local_pg = _local_counts(LOCAL_POSTGRES_DB)
    cloud_pg = _cloud_postgres_counts()
    return _compare("PostgreSQL: local DuckDB vs. cloud Azure Postgres", local_pg, cloud_pg)


def validate_cosmos() -> bool:
    """Compare local Cosmos DuckDB vs. cloud Azure Cosmos."""
    local_cosmos = _local_counts(LOCAL_COSMOS_DB)
    cloud_cosmos = _cloud_cosmos_counts()
    return _compare("Cosmos DB: local DuckDB vs. cloud Azure Cosmos", local_cosmos, cloud_cosmos)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Compare local DuckDB vs. cloud data")
    parser.add_argument("--postgres", action="store_true", help="Compare Postgres only")
    parser.add_argument("--cosmos", action="store_true", help="Compare Cosmos only")
    args = parser.parse_args()

    # Default to both if neither specified
    do_postgres = args.postgres or not (args.postgres or args.cosmos)
    do_cosmos = args.cosmos or not (args.postgres or args.cosmos)

    has_diff = False
    if do_postgres:
        has_diff |= validate_postgres()
    if do_cosmos:
        has_diff |= validate_cosmos()

    print()
    if has_diff:
        print(f"{C.YELLOW}Differences detected. Run 'make sync-all' to synchronize.{C.END}")
    else:
        print(f"{C.GREEN}Local and cloud data are in sync.{C.END}")
    print()


if __name__ == "__main__":
    main()
