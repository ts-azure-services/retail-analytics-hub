"""
Pre-flight connectivity check for cloud-direct simulation mode.

Validates that PostgreSQL, CosmosDB, and Event Hub are reachable
before starting a simulation with SIMULATION_TARGET=cloud.

Usage:
    uv run python -m simulation.check_cloud
"""

import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv("local.env")

# Suppress verbose Azure SDK logging during connectivity checks
for _logger_name in ("azure", "azure.core", "azure.identity", "azure.cosmos", "azure.eventhub"):
    logging.getLogger(_logger_name).setLevel(logging.WARNING)

from simulation.shared.config import DatabaseConfig


def _check_postgres(cfg: DatabaseConfig) -> bool:
    """Verify PostgreSQL connectivity with a simple SELECT 1."""
    import psycopg

    if not all([cfg.postgres_host, cfg.postgres_database, cfg.postgres_user, cfg.postgres_password]):
        print("  \033[0;31m✗ PostgreSQL config incomplete (missing POSTGRESQL_* env vars)\033[0m")
        return False

    try:
        conn = psycopg.connect(
            host=cfg.postgres_host,
            dbname=cfg.postgres_database,
            user=cfg.postgres_user,
            password=cfg.postgres_password,
            port=5432,
            sslmode="require",
            connect_timeout=10,
        )
        conn.execute("SELECT 1")
        conn.close()
        print(f"  \033[0;32m✓ PostgreSQL: {cfg.postgres_host}/{cfg.postgres_database}\033[0m")
        return True
    except Exception as e:
        print(f"  \033[0;31m✗ PostgreSQL: {e}\033[0m")
        print("    💡 If firewall-blocked, run: make check-pg-firewall / make add-pg-firewall")
        return False


def _check_cosmos(cfg: DatabaseConfig) -> bool:
    """Verify CosmosDB connectivity by reading the database."""
    from azure.cosmos import CosmosClient
    from azure.identity import DefaultAzureCredential

    if not cfg.cosmos_endpoint or not cfg.cosmos_database:
        print("  \033[0;31m✗ CosmosDB config incomplete (missing COSMOSDB_* env vars)\033[0m")
        return False

    try:
        client = CosmosClient(cfg.cosmos_endpoint, credential=DefaultAzureCredential())
        db = client.get_database_client(cfg.cosmos_database)
        db.read()
        print(f"  \033[0;32m✓ CosmosDB: {cfg.cosmos_database}\033[0m")
        return True
    except Exception as e:
        print(f"  \033[0;31m✗ CosmosDB: {e}\033[0m")
        print("    💡 Ensure your identity has Cosmos DB Built-in Data Contributor role.")
        print("    💡 Run: make create-agent-sp  (assigns role to both SP and current user)")
        return False


def _check_eventhub(cfg: DatabaseConfig) -> bool:
    """Verify Event Hub connectivity by reading hub properties."""
    from azure.eventhub import EventHubProducerClient
    from azure.identity import DefaultAzureCredential

    if not cfg.eventhub_connection_string or not cfg.eventhub_name:
        print("  \033[0;31m✗ Event Hub config incomplete (missing EVENTHUB_* env vars)\033[0m")
        return False

    try:
        # Extract namespace FQDN from connection string
        namespace = cfg.eventhub_connection_string.split("//")[1].split("/")[0]
        credential = DefaultAzureCredential()
        producer = EventHubProducerClient(
            fully_qualified_namespace=namespace,
            eventhub_name=cfg.eventhub_name,
            credential=credential,
        )
        props = producer.get_eventhub_properties()
        producer.close()
        # SDK may return dict or object depending on version
        eh_name = props.get('eventhub_name', cfg.eventhub_name) if isinstance(props, dict) else getattr(props, 'name', cfg.eventhub_name)
        partitions = props.get('partition_ids', []) if isinstance(props, dict) else getattr(props, 'partition_ids', [])
        print(f"  \033[0;32m✓ Event Hub: {eh_name} ({len(partitions)} partitions)\033[0m")
        return True
    except Exception as e:
        print(f"  \033[0;31m✗ Event Hub: {e}\033[0m")
        return False


def check_cloud_connectivity() -> bool:
    """
    Run all three connectivity checks.

    Returns True if all pass, False otherwise.
    """
    cfg = DatabaseConfig()

    print()
    print("=" * 60)
    print("☁️  Cloud Connectivity Check")
    print("=" * 60)

    pg_ok = _check_postgres(cfg)
    cosmos_ok = _check_cosmos(cfg)
    eh_ok = _check_eventhub(cfg)

    print()
    if pg_ok and cosmos_ok and eh_ok:
        print("\033[0;32m✓ All cloud services reachable — ready for cloud-direct simulation\033[0m")
    else:
        print("\033[0;31m✗ One or more cloud services unreachable — fix issues above before running\033[0m")
    print("=" * 60)
    print()

    return pg_ok and cosmos_ok and eh_ok


def main() -> int:
    ok = check_cloud_connectivity()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
