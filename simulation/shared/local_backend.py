"""
Local DuckDB backend adapters for PostgreSQL, CosmosDB, and Event Hub.

Drop-in replacements that mimic the same method signatures as the real
Azure-backed writers, but persist everything into local DuckDB files:
  - local_postgres.duckdb  (replaces Azure PostgreSQL)
  - local_cosmos.duckdb    (replaces Azure CosmosDB)

Toggle: Set  USE_LOCAL_DB = True  in persistence.py (or config) to
route all writes here.  Comment it out / set False to revert to Azure.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import uuid4
from decimal import Decimal
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths – databases live at the repo root
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
POSTGRES_DB_PATH = str(_REPO_ROOT / "local_postgres.duckdb")
COSMOS_DB_PATH = str(_REPO_ROOT / "local_cosmos.duckdb")


def _decimal_to_float(obj: Any) -> Any:
    """Recursively convert Decimal → float for DuckDB / JSON compat."""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_decimal_to_float(i) for i in obj]
    return obj


# ===================================================================
#  DuckDB  ↔  PostgreSQL adapter
# ===================================================================

class DuckDBPostgresWriter:
    """
    Drop-in replacement for PostgresWriter.
    Same public API; backed by a local DuckDB file.
    """

    def __init__(self, config=None):
        self.db_path = POSTGRES_DB_PATH
        self._conn = duckdb.connect(self.db_path)
        # Enable returning auto-increment ids
        self._ensure_sequences()
        # Create ML/sweep tables for parameter sweep and ML training
        self._ensure_ml_tables()
        logger.info(f"DuckDBPostgresWriter initialised → {self.db_path}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_sequences(self):
        """Create sequences used for SERIAL emulation if missing."""
        for seq in [
            "orders_order_id_seq",
            "order_items_order_item_id_seq",
            "payments_payment_id_seq",
            "points_transactions_transaction_id_seq",
            "returns_return_id_seq",
            "purchase_order_lines_po_line_id_seq",
        ]:
            try:
                self._conn.execute(f"CREATE SEQUENCE IF NOT EXISTS {seq} START 1")
            except Exception:
                pass  # sequence may already exist

    def _ensure_ml_tables(self):
        """Create tables for parameter sweeps and ML training data."""
        # Scenario tracking for parameter sweeps
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS simulation_scenarios (
                scenario_id VARCHAR PRIMARY KEY,
                scenario_name VARCHAR,
                workflow_type VARCHAR DEFAULT 'omnichannel',
                run_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                duration_hours DOUBLE,
                random_seed INTEGER,
                config_json JSON,
                status VARCHAR DEFAULT 'running',
                total_customers INTEGER,
                total_orders INTEGER,
                total_revenue DOUBLE,
                conversion_rate DOUBLE,
                stockout_count INTEGER,
                fill_rate DOUBLE,
                avg_lead_time DOUBLE,
                churn_rate DOUBLE,
                campaign_response_rate DOUBLE,
                avg_clv DOUBLE
            )
        """)

        # Customer journey records (for ML training)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_journeys (
                journey_id VARCHAR PRIMARY KEY,
                scenario_id VARCHAR NOT NULL,
                customer_id VARCHAR NOT NULL,
                channel VARCHAR NOT NULL,
                arrival_time DOUBLE,
                arrival_hour INTEGER,
                day_of_week INTEGER,
                browsing_duration DOUBLE,
                basket_size INTEGER,
                queue_wait_time DOUBLE,
                checkout_time DOUBLE,
                total_amount DOUBLE,
                abandoned BOOLEAN DEFAULT FALSE,
                abandonment_reason VARCHAR,
                payment_failed BOOLEAN DEFAULT FALSE,
                completed BOOLEAN DEFAULT FALSE,
                order_id INTEGER,
                total_journey_time DOUBLE
            )
        """)

        # Hourly aggregates for demand forecasting
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS hourly_demand (
                id VARCHAR PRIMARY KEY,
                scenario_id VARCHAR NOT NULL,
                hour_of_simulation DOUBLE,
                hour_of_day INTEGER,
                day_of_week INTEGER,
                channel VARCHAR,
                arrival_count INTEGER,
                order_count INTEGER,
                revenue DOUBLE,
                abandonment_count INTEGER,
                avg_basket_size DOUBLE
            )
        """)

        # Order-level metrics
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS order_metrics (
                order_id INTEGER PRIMARY KEY,
                scenario_id VARCHAR NOT NULL,
                channel VARCHAR,
                order_time DOUBLE,
                order_hour INTEGER,
                day_of_week INTEGER,
                fulfillment_start_time DOUBLE,
                fulfillment_complete_time DOUBLE,
                fulfillment_duration DOUBLE,
                on_time BOOLEAN,
                returned BOOLEAN DEFAULT FALSE
            )
        """)

        # ===== INVENTORY WORKFLOW TABLES =====

        # Inventory events for ML training (stockout prediction, demand forecasting)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory_events (
                event_id VARCHAR PRIMARY KEY,
                scenario_id VARCHAR NOT NULL,
                sku VARCHAR NOT NULL,
                location VARCHAR NOT NULL,
                event_type VARCHAR NOT NULL,
                event_time DOUBLE,
                event_hour INTEGER,
                day_of_week INTEGER,
                quantity_change INTEGER,
                quantity_before INTEGER,
                quantity_after INTEGER,
                reorder_point INTEGER,
                safety_stock INTEGER,
                on_order_qty INTEGER,
                stockout_occurred BOOLEAN DEFAULT FALSE,
                reference_id VARCHAR
            )
        """)

        # Supplier performance for lead time prediction
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS supplier_deliveries (
                delivery_id VARCHAR PRIMARY KEY,
                scenario_id VARCHAR NOT NULL,
                supplier_id VARCHAR NOT NULL,
                po_number VARCHAR NOT NULL,
                sku VARCHAR,
                order_quantity INTEGER,
                received_quantity INTEGER,
                order_time DOUBLE,
                expected_delivery_time DOUBLE,
                actual_delivery_time DOUBLE,
                expected_lead_time_days DOUBLE,
                actual_lead_time_days DOUBLE,
                on_time BOOLEAN,
                short_shipped BOOLEAN DEFAULT FALSE
            )
        """)

        # Daily inventory snapshots for forecasting
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory_snapshots (
                id VARCHAR PRIMARY KEY,
                scenario_id VARCHAR NOT NULL,
                sku VARCHAR NOT NULL,
                location VARCHAR NOT NULL,
                snapshot_day INTEGER,
                quantity_on_hand INTEGER,
                quantity_on_order INTEGER,
                daily_demand INTEGER,
                daily_receipts INTEGER,
                stockout_hours DOUBLE,
                reorder_triggered BOOLEAN DEFAULT FALSE
            )
        """)

        # ===== ENGAGEMENT WORKFLOW TABLES =====

        # Customer engagement events for ML training
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS engagement_events (
                event_id VARCHAR PRIMARY KEY,
                scenario_id VARCHAR NOT NULL,
                customer_id VARCHAR NOT NULL,
                event_type VARCHAR NOT NULL,
                event_time DOUBLE,
                event_hour INTEGER,
                day_of_week INTEGER,
                campaign_id VARCHAR,
                channel VARCHAR,
                response VARCHAR,
                value_tier VARCHAR,
                activity_state VARCHAR,
                days_since_last_purchase DOUBLE,
                total_spend DOUBLE,
                purchase_count INTEGER,
                loyalty_points INTEGER,
                churn_risk_score DOUBLE
            )
        """)

        # Customer segment snapshots for churn/CLV models
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_snapshots (
                id VARCHAR PRIMARY KEY,
                scenario_id VARCHAR NOT NULL,
                customer_id VARCHAR NOT NULL,
                snapshot_time DOUBLE,
                activity_state VARCHAR,
                value_tier VARCHAR,
                rfm_segment VARCHAR,
                total_spend DOUBLE,
                purchase_count INTEGER,
                avg_order_value DOUBLE,
                days_since_last_purchase DOUBLE,
                days_since_join DOUBLE,
                loyalty_points INTEGER,
                unresponsive_count INTEGER,
                churn_risk_score DOUBLE,
                churned BOOLEAN DEFAULT FALSE
            )
        """)

        # Campaign performance for campaign response model
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS campaign_interactions (
                interaction_id VARCHAR PRIMARY KEY,
                scenario_id VARCHAR NOT NULL,
                customer_id VARCHAR NOT NULL,
                campaign_id VARCHAR NOT NULL,
                campaign_type VARCHAR,
                send_time DOUBLE,
                value_tier VARCHAR,
                rfm_segment VARCHAR,
                unresponsive_count INTEGER,
                days_since_last_engagement DOUBLE,
                opened BOOLEAN DEFAULT FALSE,
                clicked BOOLEAN DEFAULT FALSE,
                converted BOOLEAN DEFAULT FALSE
            )
        """)

    def _execute(self, sql: str, params: tuple = None, fetch: bool = False):
        """Execute a SQL statement with optional params and optional fetch."""
        try:
            if params:
                result = self._conn.execute(sql, params)
            else:
                result = self._conn.execute(sql)
            if fetch:
                return result.fetchall()
            return None
        except Exception as e:
            logger.error(f"DuckDB exec error: {e}\nSQL: {sql[:300]}")
            raise

    # ------------------------------------------------------------------
    # Connection-pool API stubs (not needed for DuckDB)
    # ------------------------------------------------------------------
    def get_connection(self):
        return self._conn

    def return_connection(self, conn):
        pass

    # ------------------------------------------------------------------
    # Write operations – same signatures as PostgresWriter
    # ------------------------------------------------------------------
    def write_order(self, order_data: Dict) -> Optional[int]:
        try:
            order_id = self._conn.execute(
                "SELECT nextval('orders_order_id_seq')"
            ).fetchone()[0]

            self._conn.execute(
                """
                INSERT INTO orders
                    (order_id, customer_id, order_date, total_amount, status,
                     channel, fulfillment_status, workflow_source,
                     shipping_address, payment_method)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    order_data["customer_id"],
                    order_data["order_date"],
                    float(order_data["total_amount"]),
                    order_data["status"],
                    order_data["channel"],
                    order_data["fulfillment_status"],
                    order_data["workflow_source"],
                    order_data.get("shipping_address"),
                    order_data["payment_method"],
                ),
            )
            logger.debug(f"Created order {order_id}")
            return order_id
        except Exception as e:
            logger.error(f"Error writing order: {e}")
            return None

    def write_order_items(self, order_id: int, items: List[Dict]) -> bool:
        try:
            for item in items:
                item_id = self._conn.execute(
                    "SELECT nextval('order_items_order_item_id_seq')"
                ).fetchone()[0]
                self._conn.execute(
                    """
                    INSERT INTO order_items
                        (order_item_id, order_id, product_id, sku,
                         quantity, unit_price, subtotal)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        order_id,
                        item["product_id"],
                        item.get("sku"),
                        item["quantity"],
                        float(item["unit_price"]),
                        float(item["subtotal"]),
                    ),
                )
            logger.debug(f"Created {len(items)} order items for order {order_id}")
            return True
        except Exception as e:
            logger.error(f"Error writing order items: {e}")
            return False

    def write_payment(self, payment_data: Dict) -> Optional[int]:
        try:
            payment_id = self._conn.execute(
                "SELECT nextval('payments_payment_id_seq')"
            ).fetchone()[0]
            self._conn.execute(
                """
                INSERT INTO payments
                    (payment_id, order_id, amount, payment_method,
                     status, auth_code, payment_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payment_id,
                    payment_data["order_id"],
                    float(payment_data["amount"]),
                    payment_data["payment_method"],
                    payment_data["status"],
                    payment_data.get("auth_code"),
                    payment_data.get("payment_time", datetime.now()),
                ),
            )
            logger.debug(f"Created payment {payment_id}")
            return payment_id
        except Exception as e:
            logger.error(f"Error writing payment: {e}")
            return None

    def update_order_status(self, order_id: int, status: str,
                            fulfillment_status: Optional[str] = None) -> bool:
        try:
            if fulfillment_status:
                self._conn.execute(
                    "UPDATE orders SET status = ?, fulfillment_status = ? WHERE order_id = ?",
                    (status, fulfillment_status, order_id),
                )
            else:
                self._conn.execute(
                    "UPDATE orders SET status = ? WHERE order_id = ?",
                    (status, order_id),
                )
            logger.debug(f"Updated order {order_id} status to {status}")
            return True
        except Exception as e:
            logger.error(f"Error updating order status: {e}")
            return False

    def update_order_payment_status(self, order_id: int, payment_status: str) -> bool:
        try:
            self._conn.execute(
                "UPDATE orders SET payment_status = ? WHERE order_id = ?",
                (payment_status, order_id),
            )
            logger.debug(f"Updated order {order_id} payment_status to {payment_status}")
            return True
        except Exception as e:
            logger.error(f"Error updating order payment status: {e}")
            return False

    def update_order_fulfillment_status(self, order_id: int,
                                         fulfillment_status: str) -> bool:
        try:
            self._conn.execute(
                "UPDATE orders SET fulfillment_status = ? WHERE order_id = ?",
                (fulfillment_status, order_id),
            )
            logger.debug(
                f"Updated order {order_id} fulfillment_status to {fulfillment_status}"
            )
            return True
        except Exception as e:
            logger.error(f"Error updating order fulfillment status: {e}")
            return False

    def update_inventory(self, sku: str, location: str,
                         quantity_change: int, reserved_change: int = 0) -> bool:
        try:
            self._conn.execute(
                """
                UPDATE inventory
                SET quantity_on_hand  = quantity_on_hand  + ?,
                    quantity_reserved = quantity_reserved + ?,
                    last_updated      = CURRENT_TIMESTAMP
                WHERE sku = ? AND location_id = ?
                """,
                (quantity_change, reserved_change, sku, location),
            )
            logger.debug(f"Updated inventory for {sku} at {location}")
            return True
        except Exception as e:
            logger.error(f"Error updating inventory: {e}")
            return False

    def execute_query(self, query: str, params: tuple = None,
                      fetch: bool = False) -> Optional[List]:
        """
        Execute a generic SQL query.

        Translates Postgres-style placeholders (%s) to DuckDB-style (?).
        Also translates common Postgres-specific SQL constructs.
        """
        query = _pg_to_duckdb_sql(query)
        try:
            if params:
                result = self._conn.execute(query, params)
            else:
                result = self._conn.execute(query)
            if fetch:
                return result.fetchall()
            return None
        except Exception as e:
            logger.error(f"Query execution failed: {e}\nSQL: {query[:300]}")
            return None

    def close(self):
        if self._conn:
            self._conn.close()
            logger.info("DuckDBPostgresWriter closed")


# ===================================================================
#  DuckDB  ↔  CosmosDB adapter
# ===================================================================

class _DuckDBContainerClient:
    """Mimics the CosmosDB ContainerClient interface backed by DuckDB."""

    def __init__(self, conn: duckdb.DuckDBPyConnection, table_name: str):
        self._conn = conn
        self._table = table_name
        self._ensure_table()

    def _ensure_table(self):
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS "{self._table}" (
                id          VARCHAR PRIMARY KEY,
                partition_key VARCHAR,
                data        JSON
            )
        """)

    # ---------- Cosmos-compatible methods ----------
    def create_item(self, body: Dict, **kwargs) -> Dict:
        body = _decimal_to_float(body)
        doc_id = body.get("id", str(uuid4()))
        body["id"] = doc_id
        pk = self._resolve_partition_key(body)
        self._conn.execute(
            f'INSERT INTO "{self._table}" (id, partition_key, data) VALUES (?, ?, ?)',
            (doc_id, pk, json.dumps(body)),
        )
        return body

    def upsert_item(self, body: Dict, **kwargs) -> Dict:
        body = _decimal_to_float(body)
        doc_id = body.get("id", str(uuid4()))
        body["id"] = doc_id
        pk = self._resolve_partition_key(body)
        # DuckDB INSERT OR REPLACE
        self._conn.execute(
            f"""
            INSERT INTO "{self._table}" (id, partition_key, data)
            VALUES (?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                partition_key = excluded.partition_key,
                data = excluded.data
            """,
            (doc_id, pk, json.dumps(body)),
        )
        return body

    def query_items(self, query: str, *, enable_cross_partition_query: bool = True,
                    parameters: Optional[List] = None, **kwargs) -> List[Dict]:
        """
        Very lightweight Cosmos SQL → DuckDB SQL translator.
        Handles the common patterns used in this codebase:
          SELECT c.customerId FROM c
          SELECT * FROM c WHERE c.userId = '...' AND c.status = 'active'
        """
        rows = self._conn.execute(
            f'SELECT data FROM "{self._table}"'
        ).fetchall()
        documents = [json.loads(r[0]) for r in rows]

        # Apply simple WHERE filtering from the query string
        documents = _cosmos_filter(query, documents)

        # Apply SELECT projection
        documents = _cosmos_project(query, documents)

        return documents

    def read_all_items(self, **kwargs) -> List[Dict]:
        rows = self._conn.execute(
            f'SELECT data FROM "{self._table}"'
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def read(self):
        """Verify container (table) exists – no-op for DuckDB."""
        pass

    # ---------- helpers ----------
    @staticmethod
    def _resolve_partition_key(body: Dict) -> str:
        """Try common partition key fields."""
        for key in ("customerId", "cartId", "orderId", "order_id",
                     "sku", "customer_id", "id"):
            if key in body:
                return str(body[key])
        return str(body.get("id", ""))


class _DuckDBDatabaseClient:
    """Mimics CosmosDB DatabaseClient – returns container clients."""

    def __init__(self, conn: duckdb.DuckDBPyConnection):
        self._conn = conn
        self._containers: Dict[str, _DuckDBContainerClient] = {}

    def get_container_client(self, container_name: str) -> _DuckDBContainerClient:
        if container_name not in self._containers:
            self._containers[container_name] = _DuckDBContainerClient(
                self._conn, container_name
            )
        return self._containers[container_name]


class DuckDBCosmosWriter:
    """
    Drop-in replacement for CosmosWriter.
    Exposes the same public API; backed by a local DuckDB file.
    Also exposes ``self.database`` so that workflow code calling
    ``self.persistence.cosmos.database.get_container_client(...)``
    keeps working.
    """

    def __init__(self, config=None):
        self.db_path = COSMOS_DB_PATH
        self._conn = duckdb.connect(self.db_path)

        # Expose a Cosmos-like database client
        self.database = _DuckDBDatabaseClient(self._conn)

        # Pre-create container tables the simulation expects
        self.containers: Dict[str, _DuckDBContainerClient] = {}
        for name in [
            "Customers", "Carts", "WorkflowEvents",
            "FulfillmentState", "InventoryEvents", "EngagementEvents",
        ]:
            self.containers[name] = self.database.get_container_client(name)

        logger.info(f"DuckDBCosmosWriter initialised → {self.db_path}")

    # ------------------------------------------------------------------
    # Public API – same signatures as CosmosWriter
    # ------------------------------------------------------------------
    def write_cart_event(self, event_data: Dict) -> bool:
        try:
            document = {
                "id": str(uuid4()),
                "orderId": event_data.get("orderId", event_data.get("cartId")),
                "cartId": event_data.get("cartId"),
                "workflowType": "cart",
                "eventType": event_data["eventType"],
                "timestamp": event_data.get("timestamp", datetime.now().isoformat()),
                "details": event_data.get("details", {}),
                "metadata": {
                    "source": "simulation",
                    "workflow": event_data.get("workflow", "omnichannel_purchase"),
                },
            }
            self.containers["WorkflowEvents"].create_item(body=document)
            logger.debug(f"Created cart event: {event_data['eventType']}")
            return True
        except Exception as e:
            logger.error(f"Error writing cart event: {e}")
            return False

    def write_order_event(self, event_data: Dict) -> bool:
        try:
            event_data = _decimal_to_float(event_data)
            document = {
                "id": str(uuid4()),
                "orderId": event_data["orderId"],
                "workflowType": "order",
                "eventType": event_data["eventType"],
                "timestamp": event_data.get("timestamp", datetime.now().isoformat()),
                "details": event_data.get("details", {}),
                "metadata": {
                    "source": "simulation",
                    "workflow": event_data.get("workflow", "omnichannel_purchase"),
                },
            }
            self.containers["WorkflowEvents"].create_item(body=document)
            logger.debug(f"Created order event: {event_data['eventType']}")
            return True
        except Exception as e:
            logger.error(f"Error writing order event: {e}")
            return False

    def write_cart(self, cart_data: Dict) -> bool:
        try:
            cart_data = _decimal_to_float(cart_data)
            document = {
                "id": cart_data.get("id", str(uuid4())),
                "cartId": cart_data["cartId"],
                "userId": cart_data["userId"],
                "channel": cart_data["channel"],
                "items": cart_data.get("items", []),
                "lastUpdateTime": cart_data.get(
                    "lastUpdateTime", datetime.now().isoformat()
                ),
                "status": cart_data.get("status", "active"),
            }
            self.containers["Carts"].upsert_item(body=document)
            logger.debug(f"Upserted cart: {cart_data['cartId']}")
            return True
        except Exception as e:
            logger.error(f"Error writing cart: {e}")
            return False

    def write_document(self, container_name: str, document: Dict) -> bool:
        try:
            document = _decimal_to_float(document)
            if "id" not in document:
                document["id"] = str(uuid4())
            if container_name not in self.containers:
                # Lazily create unknown containers
                self.containers[container_name] = (
                    self.database.get_container_client(container_name)
                )
            self.containers[container_name].upsert_item(body=document)
            logger.debug(f"Upserted document to {container_name}: {document['id']}")
            return True
        except Exception as e:
            logger.error(f"Error writing document to {container_name}: {e}")
            return False

    def close(self):
        if self._conn:
            self._conn.close()
            logger.info("DuckDBCosmosWriter closed")


# ===================================================================
#  No-op Event Hub writer
# ===================================================================

class NoOpEventHubWriter:
    """Silently drops events (same interface as EventHubWriter)."""

    def __init__(self, config=None):
        logger.info("NoOpEventHubWriter initialised (events discarded)")

    def send_event(self, event_hub_name: str, event_data: Dict,
                   partition_key: Optional[str] = None) -> bool:
        return False

    def close(self):
        pass


# ===================================================================
#  Helpers – lightweight Postgres→DuckDB SQL translation
# ===================================================================

def _pg_to_duckdb_sql(sql: str) -> str:
    """
    Translate the most common Postgres-isms to DuckDB SQL:
      - %s  →  ?
      - ON CONFLICT … DO UPDATE SET col = EXCLUDED.col  (mostly works as-is)
      - CURRENT_TIMESTAMP works in DuckDB
      - DO $$ … END $$;  blocks → skip entirely (used for ALTER migrations)
    """
    import re

    # Skip PL/pgSQL DO blocks entirely
    if re.search(r'\bDO\s+\$', sql, re.IGNORECASE):
        return "SELECT 1"  # no-op

    # Replace %s with ?
    sql = sql.replace("%s", "?")

    # RETURNING clause: DuckDB doesn't support RETURNING in INSERT in the
    # same way; our adapter already handles IDs via sequences, so strip it.
    sql = re.sub(r'\bRETURNING\s+\w+', '', sql, flags=re.IGNORECASE)

    return sql


def _cosmos_filter(query: str, documents: List[Dict]) -> List[Dict]:
    """Apply very basic WHERE clause filtering from a Cosmos-style query."""
    import re

    where_match = re.search(r'WHERE\s+(.+?)(?:ORDER\s+BY|$)', query,
                            re.IGNORECASE | re.DOTALL)
    if not where_match:
        return documents

    where_clause = where_match.group(1).strip()

    # Parse simple  c.field = 'value'  AND chains
    conditions = re.split(r'\s+AND\s+', where_clause, flags=re.IGNORECASE)
    filtered = documents
    for cond in conditions:
        m = re.match(r"c\.(\w+)\s*=\s*'([^']*)'", cond.strip())
        if m:
            field, value = m.group(1), m.group(2)
            filtered = [d for d in filtered if str(d.get(field, "")) == value]
    return filtered


def _cosmos_project(query: str, documents: List[Dict]) -> List[Dict]:
    """Apply SELECT projection (handles SELECT * and SELECT c.field …)."""
    import re

    select_match = re.match(r'SELECT\s+(.+?)\s+FROM', query,
                            re.IGNORECASE | re.DOTALL)
    if not select_match:
        return documents

    projection = select_match.group(1).strip()
    if projection == "*":
        return documents

    # Parse field list: c.field1, c.field2
    fields = []
    for f in projection.split(","):
        f = f.strip()
        if f.startswith("c."):
            f = f[2:]  # remove "c." prefix
        fields.append(f)
    return [{f: d.get(f) for f in fields} for d in documents]
