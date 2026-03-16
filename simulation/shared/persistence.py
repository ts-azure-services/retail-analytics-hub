"""
Shared persistence layer for database writes.

Handles writing simulation state to:
- PostgreSQL (orders, inventory, payments)
- CosmosDB (carts, workflow events)
- Event Hub (event streaming)

Set SIMULATION_TARGET=cloud in local.env (or environment) to route writes
to Azure services.  The default ("local") uses DuckDB files.
"""

# ──────────────────────────────────────────────────────────────────────
# LOCAL-DB TOGGLE  –  driven by SIMULATION_TARGET env var
#   "local" (default) → DuckDB files
#   "cloud"           → Azure PostgreSQL / CosmosDB / Event Hub
# ──────────────────────────────────────────────────────────────────────
import os
from dotenv import load_dotenv
load_dotenv("local.env")

USE_LOCAL_DB = os.getenv("SIMULATION_TARGET", "local").lower() != "cloud"
# ──────────────────────────────────────────────────────────────────────

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from uuid import uuid4
from decimal import Decimal

# Cloud SDK imports are deferred to class __init__ methods so that
# sweep mode can override USE_LOCAL_DB before they are triggered.

from .config import DatabaseConfig


logger = logging.getLogger(__name__)


def convert_decimals(obj: Any) -> Any:
    """
    Recursively convert Decimal objects to float for JSON serialization.
    Handles nested dictionaries and lists.
    """
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {key: convert_decimals(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals(item) for item in obj]
    else:
        return obj


class PostgresWriter:
    """Handles writes to PostgreSQL database"""
    
    def __init__(self, config: DatabaseConfig):
        global psycopg, ConnectionPool
        import psycopg
        from psycopg_pool import ConnectionPool

        self.config = config
        self.connection_pool = None
        self._initialize_pool()
    
    def _initialize_pool(self):
        """Initialize connection pool"""
        try:
            # psycopg3 connection pool with conninfo string
            conninfo = (
                f"host={self.config.postgres_host} "
                f"dbname={self.config.postgres_database} "
                f"user={self.config.postgres_user} "
                f"password={self.config.postgres_password} "
                f"port=5432 "
                f"sslmode=require "
                f"connect_timeout=10"
            )
            self.connection_pool = ConnectionPool(
                conninfo=conninfo,
                min_size=1,
                max_size=5,
                timeout=30,
            )
            logger.info("PostgreSQL connection pool initialized")
        except psycopg.Error as e:
            logger.error(f"Failed to initialize PostgreSQL pool: {e}")
            raise
    
    def get_connection(self):
        """Get a connection from the pool"""
        return self.connection_pool.getconn()
    
    def return_connection(self, conn):
        """Return a connection to the pool"""
        self.connection_pool.putconn(conn)
    
    def write_order(self, order_data: Dict) -> Optional[int]:
        """
        Write order to database
        
        Args:
            order_data: Dict with keys: customer_id, order_date, total_amount,
                       status, channel, fulfillment_status, workflow_source,
                       shipping_address, payment_method
        
        Returns:
            order_id if successful, None otherwise
        """
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            insert_query = """
            INSERT INTO orders (customer_id, order_date, total_amount, status, 
                              channel, fulfillment_status, workflow_source, 
                              shipping_address, payment_method)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING order_id
            """
            
            cursor.execute(insert_query, (
                order_data['customer_id'],
                order_data['order_date'],
                order_data['total_amount'],
                order_data['status'],
                order_data['channel'],
                order_data['fulfillment_status'],
                order_data['workflow_source'],
                order_data.get('shipping_address'),
                order_data['payment_method']
            ))
            
            order_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()
            
            logger.debug(f"Created order {order_id}")
            return order_id
            
        except psycopg.Error as e:
            logger.error(f"Error writing order: {e}")
            if conn:
                conn.rollback()
            return None
        finally:
            if conn:
                self.return_connection(conn)
    
    def write_order_items(self, order_id: int, items: List[Dict]) -> bool:
        """
        Write order items to database
        
        Args:
            order_id: Order ID
            items: List of dicts with keys: product_id, sku (optional), quantity, unit_price, subtotal
        
        Returns:
            True if successful
        """
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Include SKU if available (needed for analytics joins)
            insert_query = """
            INSERT INTO order_items (order_id, product_id, sku, quantity, unit_price, subtotal)
            VALUES (%s, %s, %s, %s, %s, %s)
            """
            
            values = [
                (order_id, item['product_id'], item.get('sku'), item['quantity'], 
                 item['unit_price'], item['subtotal'])
                for item in items
            ]
            
            cursor.executemany(insert_query, values)
            conn.commit()
            cursor.close()
            
            logger.debug(f"Created {len(items)} order items for order {order_id}")
            return True
            
        except psycopg.Error as e:
            logger.error(f"Error writing order items: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                self.return_connection(conn)
    
    def write_payment(self, payment_data: Dict) -> Optional[int]:
        """Write payment transaction to database"""
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            insert_query = """
            INSERT INTO payments (order_id, amount, payment_method, status, auth_code, payment_time)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING payment_id
            """
            
            cursor.execute(insert_query, (
                payment_data['order_id'],
                payment_data['amount'],
                payment_data['payment_method'],
                payment_data['status'],
                payment_data.get('auth_code'),
                payment_data.get('payment_time', datetime.now())
            ))
            
            payment_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()
            
            logger.debug(f"Created payment {payment_id}")
            return payment_id
            
        except psycopg.Error as e:
            logger.error(f"Error writing payment: {e}")
            if conn:
                conn.rollback()
            return None
        finally:
            if conn:
                self.return_connection(conn)
    
    def update_order_status(self, order_id: int, status: str, fulfillment_status: Optional[str] = None) -> bool:
        """Update order status"""
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if fulfillment_status:
                update_query = """
                UPDATE orders 
                SET status = %s, fulfillment_status = %s 
                WHERE order_id = %s
                """
                cursor.execute(update_query, (status, fulfillment_status, order_id))
            else:
                update_query = """
                UPDATE orders 
                SET status = %s 
                WHERE order_id = %s
                """
                cursor.execute(update_query, (status, order_id))
            
            conn.commit()
            cursor.close()
            
            logger.debug(f"Updated order {order_id} status to {status}")
            return True
            
        except psycopg.Error as e:
            logger.error(f"Error updating order status: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                self.return_connection(conn)
    
    def update_order_payment_status(self, order_id: int, payment_status: str) -> bool:
        """Update order payment_status field"""
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            update_query = """
            UPDATE orders 
            SET payment_status = %s 
            WHERE order_id = %s
            """
            cursor.execute(update_query, (payment_status, order_id))
            
            conn.commit()
            cursor.close()
            
            logger.debug(f"Updated order {order_id} payment_status to {payment_status}")
            return True
            
        except psycopg.Error as e:
            logger.error(f"Error updating order payment status: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                self.return_connection(conn)
    
    def update_order_fulfillment_status(self, order_id: int, fulfillment_status: str) -> bool:
        """Update order fulfillment_status field"""
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            update_query = """
            UPDATE orders 
            SET fulfillment_status = %s 
            WHERE order_id = %s
            """
            cursor.execute(update_query, (fulfillment_status, order_id))
            
            conn.commit()
            cursor.close()
            
            logger.debug(f"Updated order {order_id} fulfillment_status to {fulfillment_status}")
            return True
            
        except psycopg.Error as e:
            logger.error(f"Error updating order fulfillment status: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                self.return_connection(conn)
    
    def update_inventory(self, sku: str, location: str, quantity_change: int, reserved_change: int = 0) -> bool:
        """Update inventory levels"""
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            update_query = """
            UPDATE inventory 
            SET quantity_on_hand = quantity_on_hand + %s,
                quantity_reserved = quantity_reserved + %s,
                last_updated = CURRENT_TIMESTAMP
            WHERE sku = %s AND location_id = %s
            """
            
            cursor.execute(update_query, (quantity_change, reserved_change, sku, location))
            conn.commit()
            cursor.close()
            
            logger.debug(f"Updated inventory for {sku} at {location}")
            return True
            
        except psycopg.Error as e:
            logger.error(f"Error updating inventory: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                self.return_connection(conn)
    
    def execute_query(self, query: str, params: tuple = None, fetch: bool = False) -> Optional[List]:
        """
        Execute a generic SQL query
        
        Args:
            query: SQL query string
            params: Query parameters tuple
            fetch: Whether to fetch and return results
        
        Returns:
            List of results if fetch=True and successful, None otherwise
        """
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            result = None
            if fetch:
                result = cursor.fetchall()
            
            conn.commit()
            cursor.close()
            return result
            
        except psycopg.Error as e:
            logger.error(f"Query execution failed: {e}")
            if conn:
                conn.rollback()
            return None
        finally:
            if conn:
                self.return_connection(conn)
    
    def close(self):
        """Close all connections"""
        if self.connection_pool:
            self.connection_pool.close()
            logger.info("PostgreSQL connection pool closed")


class CosmosWriter:
    """Handles writes to CosmosDB"""
    
    def __init__(self, config: DatabaseConfig):
        global CosmosClient, PartitionKey, CosmosHttpResponseError
        from azure.cosmos import CosmosClient, PartitionKey
        from azure.cosmos.exceptions import CosmosHttpResponseError
        from azure.identity import DefaultAzureCredential

        self.config = config
        self.client = CosmosClient(config.cosmos_endpoint, credential=DefaultAzureCredential())
        self.database = self.client.get_database_client(config.cosmos_database)
        
        # Container references
        self.containers = {}
        self._setup_containers()
    
    def _setup_containers(self):
        """Setup container references"""
        container_names = ["Carts", "WorkflowEvents", "FulfillmentState", "InventoryEvents", "EngagementEvents"]
        for name in container_names:
            try:
                self.containers[name] = self.database.get_container_client(name)
                logger.debug(f"CosmosDB container ready: {name}")
            except Exception as e:
                logger.warning(f"Container {name} not accessible: {e}")
    
    def write_cart_event(self, event_data: Dict) -> bool:
        """
        Write cart event to WorkflowEvents container
        
        Args:
            event_data: Dict with keys: cartId, orderId, eventType, timestamp, details
        """
        try:
            document = {
                "id": str(uuid4()),
                "orderId": event_data.get('orderId', event_data.get('cartId')),
                "cartId": event_data.get('cartId'),
                "workflowType": "cart",
                "eventType": event_data['eventType'],
                "timestamp": event_data.get('timestamp', datetime.now().isoformat()),
                "details": event_data.get('details', {}),
                "metadata": {
                    "source": "simulation",
                    "workflow": event_data.get('workflow', 'omnichannel_purchase')
                }
            }
            
            self.containers["WorkflowEvents"].create_item(body=document)
            logger.debug(f"Created cart event: {event_data['eventType']}")
            return True
            
        except CosmosHttpResponseError as e:
            logger.error(f"Error writing cart event: {e.message}")
            return False
    
    def write_order_event(self, event_data: Dict) -> bool:
        """
        Write order event to WorkflowEvents container
        
        Args:
            event_data: Dict with keys: orderId, eventType, timestamp, details
        """
        try:
            # Convert any Decimal values to float
            event_data = convert_decimals(event_data)
            
            document = {
                "id": str(uuid4()),
                "orderId": event_data['orderId'],
                "workflowType": "order",
                "eventType": event_data['eventType'],
                "timestamp": event_data.get('timestamp', datetime.now().isoformat()),
                "details": event_data.get('details', {}),
                "metadata": {
                    "source": "simulation",
                    "workflow": event_data.get('workflow', 'omnichannel_purchase')
                }
            }
            
            self.containers["WorkflowEvents"].create_item(body=document)
            logger.debug(f"Created order event: {event_data['eventType']}")
            return True
            
        except CosmosHttpResponseError as e:
            logger.error(f"Error writing order event: {e.message}")
            return False
    
    def write_cart(self, cart_data: Dict) -> bool:
        """Write cart document to Carts container"""
        try:
            # Convert any Decimal values to float
            cart_data = convert_decimals(cart_data)
            
            document = {
                "id": cart_data.get('id', str(uuid4())),
                "cartId": cart_data['cartId'],
                "userId": cart_data['userId'],
                "channel": cart_data['channel'],
                "items": cart_data.get('items', []),
                "lastUpdateTime": cart_data.get('lastUpdateTime', datetime.now().isoformat()),
                "status": cart_data.get('status', 'active')
            }
            
            self.containers["Carts"].upsert_item(body=document)
            logger.debug(f"Upserted cart: {cart_data['cartId']}")
            return True
            
        except CosmosHttpResponseError as e:
            logger.error(f"Error writing cart: {e.message}")
            return False
    
    def write_document(self, container_name: str, document: Dict) -> bool:
        """Write/upsert a document to specified container"""
        try:
            # Convert any Decimal values to float
            document = convert_decimals(document)
            
            # Ensure id field exists
            if 'id' not in document:
                document['id'] = str(uuid4())
            
            if container_name not in self.containers:
                logger.warning(f"Container {container_name} not available")
                return False
            
            self.containers[container_name].upsert_item(body=document)
            logger.debug(f"Upserted document to {container_name}: {document['id']}")
            return True
            
        except CosmosHttpResponseError as e:
            logger.error(f"Error writing document to {container_name}: {e.message}")
            return False


class EventHubWriter:
    """Handles event streaming to Azure Event Hub"""
    
    def __init__(self, config: DatabaseConfig):
        global EventHubProducerClient, EventData, EventHubError
        from azure.eventhub import EventHubProducerClient, EventData
        from azure.eventhub.exceptions import EventHubError
        from azure.identity import DefaultAzureCredential

        self.config = config
        self.producer = None
        
        # Use identity-based authentication (same as working send.py script)
        if config.eventhub_name:
            try:
                credential = DefaultAzureCredential()
                # Extract namespace from connection string or use environment
                # Format: Endpoint=sb://namespace.servicebus.windows.net/
                if config.eventhub_connection_string:
                    namespace = config.eventhub_connection_string.split('//')[1].split('/')[0]
                else:
                    # Fallback: construct from environment
                    namespace = f"{config.eventhub_name.replace('eventhub', 'namespace')}.servicebus.windows.net"
                
                self.producer = EventHubProducerClient(
                    fully_qualified_namespace=namespace,
                    eventhub_name=config.eventhub_name,
                    credential=credential
                )
                logger.info(f"Event Hub producer initialized: {namespace}/{config.eventhub_name}")
            except Exception as e:
                logger.warning(f"Event Hub initialization failed (non-fatal): {e}")
                self.producer = None
    
    def send_event(self, event_hub_name: str, event_data: Dict, partition_key: Optional[str] = None) -> bool:
        """Send event to Event Hub
        
        Args:
            event_hub_name: Name of the event stream (e.g., 'interaction_events', 'cart_events')
            event_data: Event data dictionary
            partition_key: Optional partition key
        """
        if not self.producer:
            logger.debug("Event Hub producer not available, skipping event")
            return False
        
        try:
            # Convert any Decimal values to float
            event_data = convert_decimals(event_data)
            
            event_batch = self.producer.create_batch(partition_key=partition_key)
            event = EventData(json.dumps(event_data))
            event_batch.add(event)
            
            self.producer.send_batch(event_batch)
            logger.debug(f"Sent event to Event Hub ({event_hub_name}): {event_data.get('eventType')}")
            return True
            
        except EventHubError as e:
            logger.warning(f"Event Hub send failed (non-fatal): {e}")
            return False
        except Exception as e:
            logger.warning(f"Unexpected error sending to Event Hub (non-fatal): {e}")
            return False
    
    def close(self):
        """Close Event Hub producer"""
        if self.producer:
            self.producer.close()
            logger.info("Event Hub producer closed")


class PersistenceManager:
    """Unified manager for all persistence operations"""
    
    def __init__(self, config: DatabaseConfig, enable_eventhub: bool = True):
        if USE_LOCAL_DB:
            from .local_backend import (
                DuckDBPostgresWriter, DuckDBCosmosWriter, NoOpEventHubWriter,
            )
            self.postgres = DuckDBPostgresWriter(config)
            self.cosmos = DuckDBCosmosWriter(config)
            self.eventhub = NoOpEventHubWriter(config)
            logger.info("Persistence manager initialized (LOCAL DuckDB mode)")
        else:
            self.postgres = PostgresWriter(config)
            self.cosmos = CosmosWriter(config)
            self.eventhub = EventHubWriter(config) if enable_eventhub else None
            logger.info("Persistence manager initialized (Azure mode)")
    
    def write_complete_order(self, order_data: Dict, items: List[Dict], 
                            cart_id: Optional[str] = None) -> Optional[int]:
        """
        Write complete order with all related data
        
        Returns:
            order_id if successful
        """
        # Write order to Postgres
        order_id = self.postgres.write_order(order_data)
        if not order_id:
            return None
        
        # Write order items
        success = self.postgres.write_order_items(order_id, items)
        if not success:
            logger.warning(f"Failed to write items for order {order_id}")
        
        # Write order event to Cosmos
        self.cosmos.write_order_event({
            'orderId': str(order_id),
            'eventType': 'order_placed',
            'workflow': order_data.get('workflow_source', 'omnichannel_purchase'),
            'details': {
                'channel': order_data['channel'],
                'total_amount': float(order_data['total_amount']),
                'item_count': len(items)
            }
        })
        
        # Write cart checkout event if cart_id provided
        if cart_id:
            self.cosmos.write_cart_event({
                'cartId': cart_id,
                'orderId': str(order_id),
                'eventType': 'cart_checked_out',
                'workflow': order_data.get('workflow_source', 'omnichannel_purchase')
            })
        
        # Stream to Event Hub
        if self.eventhub:
            self.eventhub.send_event('order_events', {
                'eventType': 'order_placed',
                'orderId': order_id,
                'channel': order_data['channel'],
                'timestamp': datetime.now().isoformat()
            }, partition_key=str(order_id))
        
        return order_id
    
    def close(self):
        """Close all connections"""
        self.postgres.close()
        if self.eventhub:
            self.eventhub.close()
        logger.info("Persistence manager closed")
