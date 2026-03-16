#!/usr/bin/env python3
"""
Seed Azure PostgreSQL and CosmosDB with the same data that seed_local.py
writes to local DuckDB files.

Reuses all data generators from seed_local.py.

Usage:
    uv run seed-data/seed_cloud.py           # seed both PG + Cosmos
    uv run seed-data/seed_cloud.py --clean   # drop tables / containers first
"""

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from faker import Faker

# Load env vars from local.env at repo root
REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / "local.env")

# Reuse generators from seed_local.py
from seed_local import (
    generate_customers,
    generate_products,
    generate_suppliers,
    generate_inventory,
    generate_replenishment_policies,
    generate_orders,
    generate_purchase_history,
    generate_carts,
    generate_workflow_events,
    PG_DDL,
)


# ===================================================================
# PostgreSQL seeding (Azure Flexible Server)
# ===================================================================

def seed_postgres_cloud(customers, products, suppliers):
    """Create tables and insert data into Azure PostgreSQL using batched inserts."""
    import psycopg
    from psycopg.rows import tuple_row

    host = os.getenv("POSTGRESQL_SERVER_FQDN")
    database = os.getenv("POSTGRESQL_DATABASE_NAME")
    user = os.getenv("POSTGRESQL_ADMIN_LOGIN")
    password = os.getenv("POSTGRESQL_ADMIN_PASSWORD")

    if not all([host, database, user, password]):
        print("  ✗ Missing PostgreSQL env vars")
        sys.exit(1)

    print(f"\n📦 Seeding Azure PostgreSQL → {host}/{database}")

    conn = psycopg.connect(
        host=host, dbname=database, user=user, password=password,
        port=5432, sslmode="require", connect_timeout=10,
    )
    conn.autocommit = True

    # Create tables — translate DuckDB DDL to PostgreSQL
    pg_ddl = PG_DDL
    for line in pg_ddl.split(";"):
        line = line.strip()
        if not line or line.startswith("CREATE SEQUENCE"):
            continue
        line = line.replace(" DOUBLE,", " DOUBLE PRECISION,")
        line = line.replace(" DOUBLE NOT NULL", " DOUBLE PRECISION NOT NULL")
        line = line.replace(" DOUBLE DEFAULT", " DOUBLE PRECISION DEFAULT")
        # Auto-increment columns that the cloud PostgresWriter expects
        # (it omits these PKs from INSERT and uses RETURNING)
        line = line.replace("order_id           INTEGER PRIMARY KEY", "order_id           SERIAL PRIMARY KEY")
        line = line.replace("order_item_id INTEGER PRIMARY KEY", "order_item_id SERIAL PRIMARY KEY")
        line = line.replace("payment_id    INTEGER PRIMARY KEY", "payment_id    SERIAL PRIMARY KEY")
        line = line.replace("po_line_id  INTEGER PRIMARY KEY", "po_line_id  SERIAL PRIMARY KEY")
        try:
            conn.execute(line)
        except Exception as e:
            if "already exists" not in str(e):
                print(f"  ⚠ DDL warning: {e}")
    print("  ✓ Tables created/verified")

    cur = conn.cursor()

    # Products
    cur.executemany(
        """INSERT INTO products (product_id, name, description, category, price, stock_quantity, sku)
           VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (product_id) DO NOTHING""",
        [(p["product_id"], p["name"], p["description"], p["category"],
          p["price"], p["stock_quantity"], p["sku"]) for p in products],
    )
    conn.commit()
    print(f"  ✓ {len(products)} products")

    product_skus = [p["sku"] for p in products]

    # Suppliers
    cur.executemany(
        """INSERT INTO suppliers (supplier_id, name, mean_lead_time_days, reliability, min_order_qty)
           VALUES (%s,%s,%s,%s,%s) ON CONFLICT (supplier_id) DO NOTHING""",
        [(s["supplier_id"], s["name"], s["mean_lead_time_days"],
          s["reliability"], s["min_order_qty"]) for s in suppliers],
    )
    conn.commit()
    print(f"  ✓ {len(suppliers)} suppliers")

    supplier_ids = [s["supplier_id"] for s in suppliers]

    # Customers
    cur.executemany(
        """INSERT INTO customers (customer_id, name, email, created_at)
           VALUES (%s,%s,%s,%s) ON CONFLICT (customer_id) DO NOTHING""",
        [(c["customerId"], c["name"], c["email"], c.get("accountCreated"))
         for c in customers],
    )
    conn.commit()
    print(f"  ✓ {len(customers)} customers")

    customer_ids = [c["customerId"] for c in customers]

    # Inventory
    inv = generate_inventory(product_skus)
    cur.executemany(
        """INSERT INTO inventory (sku, location_id, quantity_on_hand, quantity_reserved, on_order_qty, reorder_point)
           VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (sku, location_id) DO NOTHING""",
        inv,
    )
    conn.commit()
    print(f"  ✓ {len(inv)} inventory records")

    # Replenishment policies
    policies = generate_replenishment_policies(product_skus, supplier_ids)
    cur.executemany(
        """INSERT INTO replenishment_policy (sku, location_id, supplier_id, reorder_point, order_quantity, safety_stock, lead_time_days)
           VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (sku, location_id) DO NOTHING""",
        policies,
    )
    conn.commit()
    print(f"  ✓ {len(policies)} replenishment policies")

    # Orders + items (use pipeline for maximum throughput)
    orders, items = generate_orders(customer_ids, len(products), count=500)
    with conn.pipeline():
        cur.executemany(
            """INSERT INTO orders (order_id, customer_id, order_date, total_amount, status, channel,
                                   payment_status, fulfillment_status, workflow_source, shipping_address, payment_method)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (order_id) DO NOTHING""",
            orders,
        )
        cur.executemany(
            """INSERT INTO order_items (order_item_id, order_id, product_id, sku, quantity, unit_price, subtotal)
               VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (order_item_id) DO NOTHING""",
            items,
        )
    conn.commit()
    print(f"  ✓ {len(orders)} orders, {len(items)} order items")

    # Purchase history (largest table — use pipeline)
    txns = generate_purchase_history(customer_ids, products)
    with conn.pipeline():
        cur.executemany(
            """INSERT INTO customer_purchase_history
               (purchase_id, customer_id, order_id, sku, product_name, quantity, unit_price, line_total, purchase_date)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (purchase_id) DO NOTHING""",
            txns,
        )
    conn.commit()
    print(f"  ✓ {len(txns)} purchase history transactions")

    # Sync SERIAL sequences to max inserted IDs so simulation INSERTs don't collide
    for table, col in [
        ("orders", "order_id"),
        ("order_items", "order_item_id"),
        ("payments", "payment_id"),
        ("purchase_order_lines", "po_line_id"),
    ]:
        cur.execute(
            "SELECT setval(pg_get_serial_sequence(%s, %s), "
            "COALESCE((SELECT MAX({col}) FROM {table}), 1))".format(col=col, table=table),
            (table, col),
        )
    conn.commit()
    print("  ✓ SERIAL sequences synced")

    cur.close()
    conn.close()
    print(f"  ✓ Azure PostgreSQL seeded")


# ===================================================================
# CosmosDB seeding
# ===================================================================

def seed_cosmos_cloud(customers, products):
    """Create containers and insert data into Azure CosmosDB."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from azure.cosmos import CosmosClient, PartitionKey
    from azure.identity import DefaultAzureCredential

    endpoint = os.getenv("COSMOSDB_ENDPOINT")
    database_name = os.getenv("COSMOSDB_DATABASE_NAME")

    if not endpoint or not database_name:
        print("  ✗ Missing CosmosDB env vars")
        sys.exit(1)

    print(f"\n📦 Seeding Azure CosmosDB → {database_name}")

    client = CosmosClient(endpoint, credential=DefaultAzureCredential())
    database = client.get_database_client(database_name)

    # Create containers with partition keys
    container_configs = {
        "Customers": "/customerId",
        "Carts": "/cartId",
        "WorkflowEvents": "/orderId",
        "FulfillmentState": "/orderId",
        "InventoryEvents": "/sku",
        "EngagementEvents": "/customerId",
    }

    containers = {}
    for name, pk_path in container_configs.items():
        try:
            containers[name] = database.create_container_if_not_exists(
                id=name, partition_key=PartitionKey(path=pk_path)
            )
        except Exception as e:
            containers[name] = database.get_container_client(name)
    print(f"  ✓ {len(containers)} containers created/verified")

    def _bulk_upsert(container, items, label):
        """Upsert items in parallel threads for throughput."""
        done = 0
        total = len(items)
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(container.upsert_item, item): item for item in items}
            for f in as_completed(futures):
                f.result()  # raise on error
                done += 1
                if done % 100 == 0 or done == total:
                    print(f"    {label}: {done}/{total}", flush=True)

    customer_ids = [c["customerId"] for c in customers]

    # Customers
    _bulk_upsert(containers["Customers"], customers, "customers")
    print(f"  ✓ {len(customers)} customer documents")

    # Carts
    carts = generate_carts(customer_ids, products, count=80)
    _bulk_upsert(containers["Carts"], carts, "carts")
    print(f"  ✓ {len(carts)} cart documents")

    # Workflow events
    events = generate_workflow_events(count=50)
    _bulk_upsert(containers["WorkflowEvents"], events, "events")
    print(f"  ✓ {len(events)} workflow event documents")

    print(f"  ✓ Azure CosmosDB seeded")


# ===================================================================
# Main
# ===================================================================

def main():
    parser = argparse.ArgumentParser(description="Seed Azure cloud databases")
    parser.add_argument("--clean", action="store_true",
                        help="Clean databases before seeding (drop tables/containers)")
    args = parser.parse_args()

    print("=" * 60)
    print("🌱 Cloud Database Seeding Script")
    print("=" * 60)

    if args.clean:
        print("\n🧹 Cleaning cloud databases first...")
        from cleanup_postgres import cleanup_postgres
        from cleanup_cosmos import cleanup_cosmos
        try:
            cleanup_postgres()
        except SystemExit:
            print("  ⚠ PostgreSQL cleanup had issues (continuing)")
        try:
            cleanup_cosmos()
        except SystemExit:
            print("  ⚠ CosmosDB cleanup had issues (continuing)")

    # Deterministic seed — matches seed_local.py
    random.seed(42)
    Faker.seed(42)

    start = time.time()

    # Generate shared data (identical to seed_local.py)
    print("\n🎲 Generating data...")
    customers = generate_customers(count=500)
    products = generate_products(count=50)
    suppliers = generate_suppliers(count=50)
    print(f"  ✓ {len(customers)} customers, {len(products)} products, {len(suppliers)} suppliers")

    # Seed both cloud databases
    seed_postgres_cloud(customers, products, suppliers)
    seed_cosmos_cloud(customers, products)

    elapsed = time.time() - start
    print(f"\n{'=' * 60}")
    print(f"✓ Cloud seeding completed in {elapsed:.1f}s")
    print(f"  PostgreSQL → {os.getenv('POSTGRESQL_SERVER_FQDN')}/{os.getenv('POSTGRESQL_DATABASE_NAME')}")
    print(f"  CosmosDB   → {os.getenv('COSMOSDB_DATABASE_NAME')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
