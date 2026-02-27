"""
Seed local DuckDB databases with the same data that would go to
Azure PostgreSQL + CosmosDB.

Creates:
  - local_postgres.duckdb  (tables + products, suppliers, inventory, etc.)
  - local_cosmos.duckdb    (Customers, Carts, WorkflowEvents, etc.)

Usage:
    uv run seed-data/seed_local.py                  # full seed (base + history)
    uv run seed-data/seed_local.py --skip-history   # base data only
    uv run seed-data/seed_local.py --clean           # delete .duckdb files first
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple
from uuid import uuid4

import duckdb
from faker import Faker

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_DB = str(REPO_ROOT / "local_postgres.duckdb")
COSMOS_DB = str(REPO_ROOT / "local_cosmos.duckdb")

fake = Faker()

# ===================================================================
# PostgreSQL-equivalent tables in DuckDB
# ===================================================================

PG_DDL = """
-- Customers
CREATE TABLE IF NOT EXISTS customers (
    customer_id VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL,
    email       VARCHAR,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Products
CREATE TABLE IF NOT EXISTS products (
    product_id     INTEGER PRIMARY KEY,
    name           VARCHAR NOT NULL,
    description    TEXT,
    category       VARCHAR,
    price          DOUBLE NOT NULL,
    stock_quantity INTEGER DEFAULT 0,
    sku            VARCHAR UNIQUE NOT NULL,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Inventory
CREATE TABLE IF NOT EXISTS inventory (
    sku              VARCHAR NOT NULL,
    location_id      VARCHAR NOT NULL,
    quantity_on_hand INTEGER NOT NULL DEFAULT 0,
    quantity_reserved INTEGER NOT NULL DEFAULT 0,
    on_order_qty     INTEGER NOT NULL DEFAULT 0,
    reorder_point    INTEGER NOT NULL DEFAULT 10,
    last_updated     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (sku, location_id)
);

-- Suppliers
CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id        VARCHAR PRIMARY KEY,
    name               VARCHAR NOT NULL,
    mean_lead_time_days DOUBLE NOT NULL,
    reliability        DOUBLE NOT NULL DEFAULT 0.95,
    min_order_qty      INTEGER NOT NULL DEFAULT 100,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Replenishment policy
CREATE TABLE IF NOT EXISTS replenishment_policy (
    sku             VARCHAR NOT NULL,
    location_id     VARCHAR NOT NULL,
    supplier_id     VARCHAR NOT NULL,
    reorder_point   INTEGER NOT NULL,
    order_quantity  INTEGER NOT NULL,
    safety_stock    INTEGER NOT NULL,
    lead_time_days  DOUBLE NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (sku, location_id)
);

-- Purchase orders
CREATE TABLE IF NOT EXISTS purchase_orders (
    po_number              VARCHAR PRIMARY KEY,
    supplier_id            VARCHAR NOT NULL,
    status                 VARCHAR NOT NULL DEFAULT 'PENDING',
    expected_delivery_date TIMESTAMP,
    created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS purchase_order_lines (
    po_line_id  INTEGER PRIMARY KEY,
    po_number   VARCHAR NOT NULL,
    sku         VARCHAR NOT NULL,
    location_id VARCHAR NOT NULL,
    order_qty   INTEGER NOT NULL,
    received_qty INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Orders
CREATE TABLE IF NOT EXISTS orders (
    order_id           INTEGER PRIMARY KEY,
    customer_id        VARCHAR NOT NULL,
    order_date         TIMESTAMP NOT NULL,
    total_amount       DOUBLE NOT NULL,
    status             VARCHAR NOT NULL,
    channel            VARCHAR NOT NULL DEFAULT 'online',
    payment_status     VARCHAR DEFAULT 'pending',
    fulfillment_status VARCHAR DEFAULT 'pending',
    workflow_source    VARCHAR DEFAULT 'manual',
    shipping_address   TEXT,
    payment_method     VARCHAR,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL,
    product_id    INTEGER,
    sku           VARCHAR,
    quantity      INTEGER NOT NULL,
    unit_price    DOUBLE NOT NULL,
    subtotal      DOUBLE NOT NULL
);

-- Payments
CREATE TABLE IF NOT EXISTS payments (
    payment_id    INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL,
    amount        DOUBLE NOT NULL,
    payment_method VARCHAR NOT NULL,
    status        VARCHAR NOT NULL DEFAULT 'pending',
    auth_code     VARCHAR,
    payment_time  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Loyalty / engagement tables
CREATE TABLE IF NOT EXISTS loyalty_account (
    customer_id     VARCHAR PRIMARY KEY,
    current_points  INTEGER NOT NULL DEFAULT 0,
    lifetime_points INTEGER NOT NULL DEFAULT 0,
    tier            VARCHAR DEFAULT 'standard',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS customer_preferences (
    customer_id         VARCHAR PRIMARY KEY,
    preferred_categories TEXT,
    marketing_opt_in    BOOLEAN DEFAULT true,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS customer_stats (
    customer_id       VARCHAR PRIMARY KEY,
    total_spend       DOUBLE DEFAULT 0,
    last_purchase_date TIMESTAMP,
    purchase_count    INTEGER DEFAULT 0,
    avg_order_value   DOUBLE DEFAULT 0,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS customer_scores (
    customer_id      VARCHAR PRIMARY KEY,
    segment          VARCHAR,
    value_tier       VARCHAR,
    churn_risk_score DOUBLE DEFAULT 0,
    activity_state   VARCHAR,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS points_transactions (
    transaction_id   INTEGER PRIMARY KEY,
    customer_id      VARCHAR NOT NULL,
    points_change    INTEGER NOT NULL,
    reason           VARCHAR,
    transaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS support_tickets (
    ticket_id           VARCHAR PRIMARY KEY,
    customer_id         VARCHAR NOT NULL,
    issue_type          VARCHAR,
    status              VARCHAR DEFAULT 'open',
    satisfaction_rating INTEGER,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at         TIMESTAMP
);

CREATE TABLE IF NOT EXISTS returns (
    return_id    INTEGER PRIMARY KEY,
    customer_id  VARCHAR NOT NULL,
    order_id     INTEGER,
    sku          VARCHAR,
    refund_amount DOUBLE,
    return_date  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reason       VARCHAR
);

CREATE TABLE IF NOT EXISTS recommendations_cache (
    customer_id VARCHAR PRIMARY KEY,
    sku_rank_1  VARCHAR,
    sku_rank_2  VARCHAR,
    sku_rank_3  VARCHAR,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS customer_purchase_history (
    purchase_id   INTEGER PRIMARY KEY,
    customer_id   VARCHAR NOT NULL,
    order_id      VARCHAR NOT NULL,
    sku           VARCHAR NOT NULL,
    product_name  VARCHAR,
    quantity      INTEGER NOT NULL DEFAULT 1,
    unit_price    DOUBLE NOT NULL,
    line_total    DOUBLE NOT NULL,
    purchase_date TIMESTAMP NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sequences used by the DuckDB adapter for auto-increment emulation
CREATE SEQUENCE IF NOT EXISTS orders_order_id_seq START 10000;
CREATE SEQUENCE IF NOT EXISTS order_items_order_item_id_seq START 10000;
CREATE SEQUENCE IF NOT EXISTS payments_payment_id_seq START 10000;
CREATE SEQUENCE IF NOT EXISTS points_transactions_transaction_id_seq START 10000;
CREATE SEQUENCE IF NOT EXISTS returns_return_id_seq START 10000;
CREATE SEQUENCE IF NOT EXISTS purchase_order_lines_po_line_id_seq START 10000;
"""


# ===================================================================
# Data generators  (reuse logic from seed_postgres.py / seed_cosmos.py)
# ===================================================================

CHOCOLATE_PRODUCTS = [
    ("Dark Chocolate Sea Salt Caramels", "Rich 70% dark chocolate filled with buttery caramel and sprinkled with sea salt crystals", "Dark Chocolate", 24.99),
    ("Extra Dark 85% Cacao Bar", "Intense dark chocolate bar with 85% cacao content from single-origin beans", "Dark Chocolate", 12.99),
    ("Dark Chocolate Espresso Bites", "Bold dark chocolate infused with premium espresso for coffee lovers", "Dark Chocolate", 18.50),
    ("Dark Cherry Cordials", "Sweet cherries enrobed in rich dark chocolate with liquid center", "Dark Chocolate", 22.99),
    ("Dark Chocolate Orange Peel", "Candied orange peel dipped in premium dark chocolate", "Dark Chocolate", 16.99),
    ("Midnight Dark Raspberry", "72% dark chocolate with freeze-dried raspberry pieces", "Dark Chocolate", 19.99),
    ("Dark Chocolate Almond Bark", "Roasted almonds covered in smooth dark chocolate", "Dark Chocolate", 15.99),
    ("Dark Mint Thins", "Crisp mint cream sandwiched between layers of dark chocolate", "Dark Chocolate", 14.50),
    ("Classic Milk Chocolate Bar", "Smooth and creamy milk chocolate made with premium cocoa beans", "Milk Chocolate", 8.99),
    ("Milk Chocolate Peanut Clusters", "Roasted peanuts covered in rich milk chocolate", "Milk Chocolate", 12.99),
    ("Milk Chocolate Caramel Squares", "Soft caramel centers wrapped in creamy milk chocolate", "Milk Chocolate", 16.99),
    ("Honeycomb Milk Chocolate", "Crunchy honeycomb candy coated in smooth milk chocolate", "Milk Chocolate", 13.99),
    ("Milk Chocolate Hazelnut Bar", "Whole roasted hazelnuts in creamy milk chocolate", "Milk Chocolate", 11.99),
    ("Milk Chocolate Pretzel Bites", "Crunchy pretzels covered in smooth milk chocolate", "Milk Chocolate", 14.99),
    ("Toffee Milk Chocolate Squares", "Buttery English toffee pieces in milk chocolate", "Milk Chocolate", 17.99),
    ("Milk Chocolate Raisins", "Plump raisins covered in premium milk chocolate", "Milk Chocolate", 9.99),
    ("White Chocolate Raspberry Bark", "White chocolate with dried raspberries and almond pieces", "White Chocolate", 15.99),
    ("White Chocolate Macadamia", "Premium white chocolate with roasted macadamia nuts", "White Chocolate", 21.99),
    ("White Chocolate Lemon Truffles", "Creamy white chocolate ganache infused with fresh lemon", "White Chocolate", 19.99),
    ("White Chocolate Coconut Dreams", "Toasted coconut flakes in smooth white chocolate", "White Chocolate", 13.99),
    ("White Chocolate Strawberry Cream", "White chocolate filled with strawberry cream center", "White Chocolate", 16.50),
    ("White Chocolate Peppermint", "Cool peppermint in white chocolate coating", "White Chocolate", 14.99),
    ("White Chocolate Pistachio", "Roasted pistachios covered in premium white chocolate", "White Chocolate", 18.99),
    ("White Chocolate Cranberry", "Dried cranberries in smooth white chocolate", "White Chocolate", 14.50),
    ("Champagne Truffles", "Delicate champagne-infused ganache rolled in cocoa powder", "Artisan Truffles", 32.99),
    ("Salted Caramel Truffles", "Silky caramel ganache with French sea salt", "Artisan Truffles", 28.99),
    ("Lavender Honey Truffles", "Floral lavender and honey in dark chocolate ganache", "Artisan Truffles", 29.99),
    ("Earl Grey Tea Truffles", "Bergamot-infused chocolate ganache with tea notes", "Artisan Truffles", 27.99),
    ("Bourbon Barrel Truffles", "Rich ganache with aged bourbon and vanilla notes", "Artisan Truffles", 34.99),
    ("Matcha Green Tea Truffles", "Premium matcha powder in white chocolate ganache", "Artisan Truffles", 30.99),
    ("Hazelnut Praline Truffles", "Roasted hazelnut praline in milk chocolate", "Artisan Truffles", 31.99),
    ("Passion Fruit Truffles", "Tropical passion fruit ganache in dark chocolate", "Artisan Truffles", 29.99),
    ("Classic Milk Chocolate Bar 100g", "Traditional milk chocolate bar, perfect for sharing", "Chocolate Bars", 7.99),
    ("Dark Chocolate Almond Bar", "Whole almonds in 60% dark chocolate bar", "Chocolate Bars", 9.99),
    ("Sea Salt Caramel Bar", "Milk chocolate bar with caramel and sea salt swirls", "Chocolate Bars", 10.99),
    ("Cookie Crunch Chocolate Bar", "Milk chocolate with crunchy cookie pieces", "Chocolate Bars", 8.99),
    ("Mint Dark Chocolate Bar", "Refreshing mint in smooth dark chocolate bar", "Chocolate Bars", 9.50),
    ("Raspberry Dark Chocolate Bar", "Tart raspberry pieces in rich dark chocolate", "Chocolate Bars", 10.50),
    ("Peanut Butter Chocolate Bar", "Creamy peanut butter layered in milk chocolate", "Chocolate Bars", 9.99),
    ("Toffee Crunch Bar", "English toffee bits throughout milk chocolate bar", "Chocolate Bars", 11.50),
    ("Cherry Cordial Collection", "Assorted cherry cordials with liqueur centers", "Filled Chocolates", 25.99),
    ("Assorted Cream Centers", "Variety of cream-filled chocolates in milk and dark", "Filled Chocolates", 22.99),
    ("Caramel Filled Chocolates", "Soft caramel centers in premium chocolate shells", "Filled Chocolates", 24.50),
    ("Nut Cluster Assortment", "Mixed nuts in milk, dark, and white chocolate", "Filled Chocolates", 26.99),
    ("Fruit Cream Collection", "Fruit-flavored cream centers in chocolate shells", "Filled Chocolates", 23.99),
    ("Coffee Cream Chocolates", "Espresso cream filling in dark chocolate cups", "Filled Chocolates", 21.99),
    ("Nougat Filled Chocolates", "Soft nougat centers wrapped in milk chocolate", "Filled Chocolates", 20.99),
    ("Marzipan Chocolates", "Almond marzipan covered in dark chocolate", "Filled Chocolates", 27.99),
    ("Coconut Cream Bonbons", "Creamy coconut filling in milk chocolate shells", "Filled Chocolates", 22.50),
    ("Peanut Butter Cups", "Smooth peanut butter in dark chocolate cups", "Filled Chocolates", 19.99),
]

SUPPLIER_NAMES = [
    "Global Supply Co.", "Pacific Distributors", "Metro Wholesale",
    "Premier Vendors", "United Suppliers", "Alliance Trading",
    "Continental Imports", "Eastern Distribution", "Western Logistics",
    "National Wholesale Group", "Premier Trading Partners", "Apex Distributors",
    "Summit Supply Chain", "Vertex Wholesale", "Horizon Imports",
    "Cascade Distribution", "Pinnacle Logistics", "Elite Suppliers Inc.",
    "Meridian Trading Co.", "Quantum Wholesale", "Nexus Supply Group",
    "Titan Distributors", "Phoenix Trading", "Atlas Supply Chain",
    "Sterling Wholesale", "Crown Distributors", "Sovereign Imports",
    "Empire Trading Partners", "Legacy Supply Co.", "Prime Logistics Group",
    "Odyssey Distributors", "Zenith Wholesale", "Nova Supply Chain",
    "Everest Trading Co.", "Keystone Distributors", "Frontier Imports",
    "Ascent Supply Group", "Prestige Wholesale", "Dynasty Trading",
    "Triumph Distributors", "Excellence Supply Co.", "Vanguard Logistics",
    "Prosperity Trading", "Fortune Wholesale", "Synergy Distributors",
    "Unity Supply Chain", "Infinity Trading Co.", "Victory Wholesale",
    "Omega Distributors", "Alpha Supply Group",
]

LOCATIONS = ["WAREHOUSE-001", "STORE-NYC", "STORE-LA", "STORE-CHI", "STORE-MIA"]


def generate_customers(count: int = 500) -> List[Dict]:
    """Generate customer records for both Postgres and Cosmos."""
    customers = []
    for _ in range(count):
        cid = fake.uuid4()
        first = fake.first_name()
        last = fake.last_name()
        customers.append({
            "id": cid,
            "customerId": cid,
            "firstName": first,
            "lastName": last,
            "name": f"{first} {last}",
            "email": fake.email(),
            "phone": fake.phone_number(),
            "address": {
                "street": fake.street_address(),
                "city": fake.city(),
                "state": fake.state_abbr(),
                "zipCode": fake.zipcode(),
                "country": "USA",
            },
            "dateOfBirth": fake.date_of_birth(minimum_age=18, maximum_age=80).isoformat(),
            "accountCreated": fake.date_time_this_decade().isoformat(),
            "accountBalance": round(random.uniform(100, 50000), 2),
            "creditScore": random.randint(300, 850),
            "isActive": random.random() < 0.85,
            "preferredContactMethod": random.choice(["email", "phone", "sms"]),
            "tags": random.sample(["premium", "standard", "vip", "new", "loyal"],
                                  k=random.randint(1, 3)),
        })
    return customers


def generate_products(count: int = 50) -> List[Dict]:
    """Return product dicts with product_id set."""
    products = []
    for i, (name, desc, cat, base_price) in enumerate(CHOCOLATE_PRODUCTS[:count], 1):
        price = round(base_price * random.uniform(0.85, 1.15), 2)
        sku = fake.bothify(text="SKU-####-????").upper()
        products.append({
            "product_id": i,
            "name": name,
            "description": desc,
            "category": cat,
            "price": price,
            "stock_quantity": random.randint(0, 500),
            "sku": sku,
        })
    return products


def generate_suppliers(count: int = 50) -> List[Dict]:
    suppliers = []
    for i in range(count):
        suppliers.append({
            "supplier_id": f"SUP-{i+1:03d}",
            "name": SUPPLIER_NAMES[i] if i < len(SUPPLIER_NAMES) else fake.company(),
            "mean_lead_time_days": round(random.uniform(0.2, 1.4), 2),
            "reliability": round(random.uniform(0.85, 0.99), 2),
            "min_order_qty": random.choice([50, 100, 200, 500]),
        })
    return suppliers


def generate_inventory(product_skus: List[str]) -> List[tuple]:
    location_profiles = {
        "WAREHOUSE-001": {"bias": "overstock", "qty_range": (200, 800), "rop_range": (50, 100)},
        "STORE-NYC": {"bias": "normal", "qty_range": (30, 150), "rop_range": (15, 40)},
        "STORE-LA": {"bias": "low", "qty_range": (5, 40), "rop_range": (20, 50)},
        "STORE-CHI": {"bias": "overstock", "qty_range": (100, 300), "rop_range": (10, 25)},
        "STORE-MIA": {"bias": "low", "qty_range": (8, 35), "rop_range": (25, 45)},
    }
    records = []
    for idx, sku in enumerate(product_skus):
        for loc in LOCATIONS:
            prof = location_profiles[loc]
            roll = (idx + hash(loc)) % 10
            if prof["bias"] == "overstock":
                if roll < 7:
                    qty = random.randint(*prof["qty_range"])
                    rop = random.randint(*prof["rop_range"])
                else:
                    qty = random.randint(50, 120)
                    rop = random.randint(30, 60)
            elif prof["bias"] == "low":
                if roll < 6:
                    rop = random.randint(*prof["rop_range"])
                    qty = random.randint(max(3, rop - 15), rop + 5)
                else:
                    qty = random.randint(40, 100)
                    rop = random.randint(15, 35)
            else:
                qty = random.randint(*prof["qty_range"])
                rop = random.randint(*prof["rop_range"])
            records.append((sku, loc, qty, 0, 0, rop))
    return records


def generate_replenishment_policies(product_skus, supplier_ids):
    policies = []
    for sku in product_skus:
        for loc in LOCATIONS:
            if "WAREHOUSE" in loc or random.random() < 0.6:
                sid = random.choice(supplier_ids)
                if "WAREHOUSE" in loc:
                    rop = random.randint(100, 300)
                    oq = random.randint(500, 2000)
                    ss = random.randint(50, 150)
                else:
                    rop = random.randint(10, 50)
                    oq = random.randint(100, 500)
                    ss = random.randint(5, 30)
                policies.append((sku, loc, sid, rop, oq, ss,
                                 round(random.uniform(2.0, 10.0), 2)))
    return policies


def generate_purchase_history(customer_ids, products):
    """Generate purchase history for RFM segmentation."""
    now = datetime.now()
    transactions = []
    pid = 1
    for i, cid in enumerate(customer_ids):
        pct = i / len(customer_ids)
        if pct < 0.20:
            n_orders, days_back = random.randint(8, 20), random.randint(5, 25)
        elif pct < 0.50:
            n_orders, days_back = random.randint(4, 8), random.randint(30, 55)
        elif pct < 0.80:
            n_orders, days_back = random.randint(1, 3), random.randint(60, 85)
        else:
            continue  # 20% "needs attention" – no purchases

        for _ in range(n_orders):
            oid = f"ORD-{cid[:8]}-{uuid4().hex[:8]}"
            pdate = now - timedelta(days=random.uniform(0, days_back))
            for __ in range(random.randint(1, 4)):
                prod = random.choice(products)
                qty = random.choices([1, 2, 3, 4], weights=[60, 30, 8, 2])[0]
                up = round(prod["price"] * random.uniform(0.95, 1.0), 2)
                lt = round(up * qty, 2)
                transactions.append((pid, cid, oid, prod["sku"], prod["name"],
                                     qty, up, lt, pdate))
                pid += 1
    return transactions


def generate_orders(customer_ids, product_count, count=500):
    orders, items = [], []
    statuses = ["pending", "processing", "shipped", "delivered", "cancelled"]
    channels = ["in_store", "online", "bopis"]
    pstatuses = ["pending", "authorized", "captured", "failed"]
    fstatuses = ["pending", "picking", "packed", "shipped", "delivered",
                 "ready_for_pickup", "picked_up"]
    pmethods = ["credit_card", "debit_card", "paypal", "bank_transfer"]
    item_id = 1
    for oid in range(1, count + 1):
        ch = random.choice(channels)
        total = 0
        n_items = random.randint(1, 5)
        for _ in range(n_items):
            pid = random.randint(1, product_count)
            qty = random.randint(1, 5)
            up = round(random.uniform(9.99, 299.99), 2)
            st = round(up * qty, 2)
            total += st
            items.append((item_id, oid, pid, None, qty, up, st))
            item_id += 1
        orders.append((
            oid,
            random.choice(customer_ids) if customer_ids else fake.uuid4(),
            fake.date_time_this_year(),
            round(total, 2),
            random.choice(statuses),
            ch,
            random.choice(pstatuses),
            random.choice(fstatuses),
            "seed_data",
            fake.address() if ch != "in_store" else None,
            random.choice(pmethods),
        ))
    return orders, items


def generate_carts(customer_ids, products, count=80):
    """Generate shopping carts for Cosmos."""
    carts = []
    n = min(count, len(customer_ids))
    selected = random.sample(customer_ids, n)
    for cid in selected:
        n_items = random.randint(1, 8)
        items = []
        for _ in range(n_items):
            p = random.choice(products)
            items.append({
                "sku": p["sku"],
                "productName": p["name"],
                "quantity": random.randint(1, 5),
                "price": p["price"],
            })
        carts.append({
            "id": fake.uuid4(),
            "cartId": fake.uuid4(),
            "userId": cid,
            "channel": random.choice(["online", "mobile_app", "in_store"]),
            "items": items,
            "lastUpdateTime": fake.date_time_this_month().isoformat(),
            "status": random.choice(["active", "abandoned", "checked_out"]),
        })
    return carts


def generate_workflow_events(count=50):
    event_types = {
        "cart": ["item_added", "item_removed", "quantity_changed",
                 "cart_abandoned", "checkout_started"],
        "order": ["order_placed", "payment_confirmed", "picking_started",
                  "packed", "shipped", "delivered", "picked_up"],
        "fulfillment": ["assigned_to_warehouse", "out_for_delivery",
                        "delivery_attempted", "delivery_failed", "returned"],
    }
    events = []
    for _ in range(count):
        wt = random.choice(list(event_types.keys()))
        events.append({
            "id": fake.uuid4(),
            "orderId": fake.uuid4(),
            "workflowType": wt,
            "eventType": random.choice(event_types[wt]),
            "timestamp": fake.date_time_this_month().isoformat(),
            "details": {},
            "metadata": {"source": "seed_data", "version": "1.0"},
        })
    return events


# ===================================================================
# Seeding functions
# ===================================================================

def seed_postgres_db(customers, products, suppliers):
    """Create tables and insert data into local_postgres.duckdb."""
    print(f"\n📦 Seeding PostgreSQL-equivalent DuckDB → {POSTGRES_DB}")
    conn = duckdb.connect(POSTGRES_DB)

    # Create tables
    for stmt in PG_DDL.split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    print("  ✓ Tables created")

    # Products
    for p in products:
        conn.execute(
            "INSERT INTO products VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            (p["product_id"], p["name"], p["description"], p["category"],
             p["price"], p["stock_quantity"], p["sku"]),
        )
    print(f"  ✓ {len(products)} products")

    product_skus = [p["sku"] for p in products]

    # Suppliers
    for s in suppliers:
        conn.execute(
            "INSERT INTO suppliers VALUES (?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            (s["supplier_id"], s["name"], s["mean_lead_time_days"],
             s["reliability"], s["min_order_qty"]),
        )
    print(f"  ✓ {len(suppliers)} suppliers")

    supplier_ids = [s["supplier_id"] for s in suppliers]

    # Customers (Postgres mirror)
    for c in customers:
        conn.execute(
            "INSERT INTO customers VALUES (?,?,?,?)",
            (c["customerId"], c["name"], c["email"],
             c.get("accountCreated")),
        )
    print(f"  ✓ {len(customers)} customers")

    customer_ids = [c["customerId"] for c in customers]

    # Inventory
    inv = generate_inventory(product_skus)
    conn.executemany(
        "INSERT INTO inventory VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)", inv
    )
    print(f"  ✓ {len(inv)} inventory records")

    # Replenishment policies
    policies = generate_replenishment_policies(product_skus, supplier_ids)
    conn.executemany(
        "INSERT INTO replenishment_policy VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
        policies,
    )
    print(f"  ✓ {len(policies)} replenishment policies")

    # Orders
    orders, items = generate_orders(customer_ids, len(products), count=500)
    conn.executemany(
        "INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)", orders
    )
    conn.executemany(
        "INSERT INTO order_items VALUES (?,?,?,?,?,?,?)", items
    )
    print(f"  ✓ {len(orders)} orders, {len(items)} order items")

    # Purchase history
    txns = generate_purchase_history(customer_ids, products)
    conn.executemany(
        "INSERT INTO customer_purchase_history VALUES (?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
        txns,
    )
    print(f"  ✓ {len(txns)} purchase history transactions")

    conn.close()
    print(f"  ✓ PostgreSQL DuckDB seeded ({POSTGRES_DB})")


def seed_cosmos_db(customers, products):
    """Create containers (tables) and insert data into local_cosmos.duckdb."""
    print(f"\n📦 Seeding CosmosDB-equivalent DuckDB → {COSMOS_DB}")
    conn = duckdb.connect(COSMOS_DB)

    # Create container tables
    containers = ["Customers", "Carts", "WorkflowEvents",
                  "FulfillmentState", "InventoryEvents", "EngagementEvents"]
    for name in containers:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS "{name}" (
                id            VARCHAR PRIMARY KEY,
                partition_key VARCHAR,
                data          JSON
            )
        """)
    print(f"  ✓ {len(containers)} container tables created")

    customer_ids = [c["customerId"] for c in customers]

    # Customers
    for c in customers:
        conn.execute(
            'INSERT INTO "Customers" VALUES (?,?,?)',
            (c["id"], c["customerId"], json.dumps(c)),
        )
    print(f"  ✓ {len(customers)} customer documents")

    # Carts
    carts = generate_carts(customer_ids, products, count=80)
    for cart in carts:
        conn.execute(
            'INSERT INTO "Carts" VALUES (?,?,?)',
            (cart["id"], cart["cartId"], json.dumps(cart)),
        )
    print(f"  ✓ {len(carts)} cart documents")

    # Workflow events
    events = generate_workflow_events(count=50)
    for ev in events:
        conn.execute(
            'INSERT INTO "WorkflowEvents" VALUES (?,?,?)',
            (ev["id"], ev["orderId"], json.dumps(ev)),
        )
    print(f"  ✓ {len(events)} workflow event documents")

    conn.close()
    print(f"  ✓ CosmosDB DuckDB seeded ({COSMOS_DB})")


# ===================================================================
# Main
# ===================================================================

def main():
    parser = argparse.ArgumentParser(description="Seed local DuckDB databases")
    parser.add_argument("--clean", action="store_true",
                        help="Delete existing .duckdb files before seeding")
    parser.add_argument("--skip-history", action="store_true",
                        help="Skip purchase history generation")
    args = parser.parse_args()

    print("=" * 60)
    print("🌱 Local DuckDB Seeding Script")
    print("=" * 60)

    if args.clean:
        for p in [POSTGRES_DB, COSMOS_DB]:
            for ext in ["", ".wal"]:
                f = p + ext
                if os.path.exists(f):
                    os.remove(f)
                    print(f"  🗑  Deleted {f}")

    # Deterministic seed for reproducibility
    random.seed(42)
    Faker.seed(42)

    start = time.time()

    # Generate shared data
    print("\n🎲 Generating data...")
    customers = generate_customers(count=500)
    products = generate_products(count=50)
    suppliers = generate_suppliers(count=50)
    print(f"  ✓ {len(customers)} customers, {len(products)} products, {len(suppliers)} suppliers")

    # Seed both databases
    seed_postgres_db(customers, products, suppliers)
    seed_cosmos_db(customers, products)

    elapsed = time.time() - start
    print(f"\n{'=' * 60}")
    print(f"✓ Local seeding completed in {elapsed:.1f}s")
    print(f"  PostgreSQL → {POSTGRES_DB}")
    print(f"  CosmosDB   → {COSMOS_DB}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
