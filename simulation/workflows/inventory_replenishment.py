"""
Inventory Replenishment & Supply Chain Workflow (Workflow 2).

Models the complete inventory management and replenishment cycle:
- Continuous inventory monitoring with reorder point logic
- Demand depletion from sales (consumption from Workflow 1)
- Automated purchase order generation when stock falls below ROP
- Supplier lead time simulation with variability
- Receiving and stock replenishment
- Inventory adjustments (shrinkage, audits)
- Multi-location stock transfers
- Supplier performance tracking

Includes:
- Stochastic demand consumption
- Reorder point (ROP) continuous review policy
- Variable lead times with supplier reliability
- Backorder handling and stockout tracking
- Safety stock calculations
- Inventory accuracy issues (shrinkage)

State persistence to Postgres, CosmosDB, and Event Hub.
"""

import simpy
import random
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from uuid import uuid4
import numpy as np

from ..shared.config import SimulationConfig
from ..shared.resources import ResourceRegistry
from ..shared.persistence import PersistenceManager
from ..shared.metrics import MetricsCollector


logger = logging.getLogger(__name__)


class InventoryReplenishmentWorkflow:
    """Inventory replenishment and supply chain simulation workflow"""
    
    def __init__(self, env: simpy.Environment, config: SimulationConfig,
                 resources: ResourceRegistry, persistence: PersistenceManager,
                 metrics: MetricsCollector):
        self.env = env
        self.config = config
        self.resources = resources
        self.persistence = persistence
        self.metrics = metrics
        
        # Simulation end time (in hours) for graceful termination
        self.simulation_end_time = config.simulation_duration_hours
        
        # Replenishment policies cache (SKU, location) -> policy
        self.replenishment_policies: Dict[Tuple[str, str], Dict] = {}
        
        # Supplier registry (supplier_id -> supplier_data)
        self.suppliers: Dict[str, Dict] = {}
        
        # Active purchase orders (PO_number -> PO_data)
        self.purchase_orders: Dict[str, Dict] = {}
        
        # PO counter
        self.po_counter = 0
        
        # Backorder queues (SKU, location) -> list of pending orders
        self.backorders: Dict[Tuple[str, str], List[Dict]] = {}
        
        # Real products from PostgreSQL (for data integrity)
        self.real_products: List[Dict] = []
        
        # Supplier mapping from PostgreSQL
        self.supplier_map: Dict[str, str] = {}  # supplier_id -> name

        # In-memory event buffers for ML table persistence
        # Accumulated alongside CosmosDB writes; flushed by persist_ml_data()
        self._inventory_event_buffer: List[Dict] = []
        self._daily_snapshot_tracker: Dict[Tuple[str, str], Dict] = {}

        logger.info("Inventory Replenishment Workflow initialized")
    
    def load_real_products(self):
        """
        Load real products and suppliers from PostgreSQL for data integrity.
        Must be called before starting workflow processes.
        Fails fast if no products are found.
        """
        if not self.persistence.postgres:
            raise RuntimeError("PostgreSQL not configured - cannot load real products")
        
        # Load products with replenishment policies
        query = """
            SELECT 
                p.sku,
                p.name,
                rp.supplier_id,
                rp.reorder_point,
                rp.order_quantity,
                rp.safety_stock,
                rp.lead_time_days
            FROM products p
            LEFT JOIN replenishment_policy rp ON p.sku = rp.sku
            WHERE p.sku IS NOT NULL
            ORDER BY p.name
        """
        
        result = self.persistence.postgres.execute_query(query, fetch=True)
        
        if not result or len(result) == 0:
            raise RuntimeError(
                "No products found in PostgreSQL. "
                "Run 'make seed-all-with-history' first to populate database."
            )
        
        self.real_products = []
        for row in result:
            product = {
                'sku': row[0],
                'name': row[1],
                'supplier_id': row[2],
                'reorder_point': row[3] or self.config.inventory.default_reorder_point,
                'order_quantity': row[4] or self.config.inventory.default_order_quantity,
                'safety_stock': row[5] or self.config.inventory.default_safety_stock,
                'lead_time_days': row[6] or self.config.inventory.default_lead_time_days
            }
            self.real_products.append(product)
        
        logger.info(f"Loaded {len(self.real_products)} real products from PostgreSQL")
        
        # Load supplier mapping
        supplier_query = "SELECT supplier_id, name FROM suppliers"
        supplier_result = self.persistence.postgres.execute_query(supplier_query, fetch=True)
        
        if not supplier_result or len(supplier_result) == 0:
            raise RuntimeError(
                "No suppliers found in PostgreSQL. "
                "Run 'make seed-all-with-history' first."
            )
        
        for row in supplier_result:
            self.supplier_map[row[0]] = row[1]
        
        logger.info(f"Loaded {len(self.supplier_map)} suppliers from PostgreSQL")
        
        if not self.real_products:
            raise RuntimeError("No products available - cannot run inventory workflow")
    
    def configure_replenishment_policy(self, sku: str, location: str, 
                                      reorder_point: int, order_quantity: int,
                                      safety_stock: int, supplier_id: str,
                                      lead_time_days: float):
        """Configure replenishment policy for a SKU at a location"""
        key = (sku, location)
        self.replenishment_policies[key] = {
            'sku': sku,
            'location': location,
            'reorder_point': reorder_point,
            'order_quantity': order_quantity,
            'safety_stock': safety_stock,
            'supplier_id': supplier_id,
            'lead_time_days': lead_time_days
        }
        
        # Persist policy to Postgres
        if self.persistence.postgres:
            self.persistence.postgres.execute_query(
                """
                INSERT INTO replenishment_policy 
                    (sku, location_id, supplier_id, reorder_point, order_quantity, 
                     safety_stock, lead_time_days)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (sku, location_id) DO UPDATE SET
                    supplier_id = EXCLUDED.supplier_id,
                    reorder_point = EXCLUDED.reorder_point,
                    order_quantity = EXCLUDED.order_quantity,
                    safety_stock = EXCLUDED.safety_stock,
                    lead_time_days = EXCLUDED.lead_time_days,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (sku, location, supplier_id, reorder_point, order_quantity, 
                 safety_stock, lead_time_days)
            )
        
        logger.debug(f"Configured replenishment policy for {sku} at {location}")
    
    def register_supplier(self, supplier_id: str, name: str, 
                         mean_lead_time: float, lead_time_std: float,
                         reliability: float = 0.95, min_order_qty: int = 100):
        """
        Register a supplier with their characteristics
        
        Args:
            supplier_id: Unique supplier identifier
            name: Supplier name
            mean_lead_time: Average lead time in days
            lead_time_std: Standard deviation of lead time
            reliability: Probability of on-time delivery (0-1)
            min_order_qty: Minimum order quantity
        """
        self.suppliers[supplier_id] = {
            'supplier_id': supplier_id,
            'name': name,
            'mean_lead_time': mean_lead_time,
            'lead_time_std': lead_time_std,
            'reliability': reliability,
            'min_order_qty': min_order_qty,
            'total_orders': 0,
            'on_time_deliveries': 0,
            'total_lead_time': 0.0
        }
        
        # Persist supplier to Postgres
        if self.persistence.postgres:
            self.persistence.postgres.execute_query(
                """
                INSERT INTO Suppliers (supplier_id, name, mean_lead_time_days, 
                                      reliability, min_order_qty)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (supplier_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    mean_lead_time_days = EXCLUDED.mean_lead_time_days,
                    reliability = EXCLUDED.reliability,
                    min_order_qty = EXCLUDED.min_order_qty
                """,
                (supplier_id, name, mean_lead_time, reliability, min_order_qty)
            )
        
        logger.info(f"Registered supplier: {supplier_id} ({name})")
    
    # ========== EVENT HUB EVENT EMISSION ==========
    
    def _emit_inventory_signal(self, sku: str, location: str, event_type: str, 
                               detail: Dict):
        """Emit inventory telemetry signal to Event Hub (high-volume leading indicators)"""
        event = {
            'sku': sku,
            'location': location,
            'eventType': event_type,  # stock_depleted, low_stock_alert, reorder_triggered
            'detail': detail,
            'timestamp': datetime.now().isoformat()
        }
        if self.persistence.eventhub:
            self.persistence.eventhub.send_event('inventory_signals', event)
        logger.debug(f"Emitted inventory signal: {event_type} for {sku} at {location}")
    
    def _emit_demand_event(self, sku: str, location: str, quantity: int, 
                          order_id: Optional[str] = None):
        """Emit demand/consumption event to Event Hub"""
        event = {
            'sku': sku,
            'location': location,
            'quantity': quantity,
            'order_id': order_id,
            'eventType': 'demand_consumed',
            'timestamp': datetime.now().isoformat()
        }
        if self.persistence.eventhub:
            self.persistence.eventhub.send_event('demand_events', event)
        logger.debug(f"Emitted demand event: {quantity} units of {sku} at {location}")
    
    def _emit_po_event(self, po_number: str, event_type: str, detail: Optional[Dict] = None):
        """Emit purchase order event to Event Hub"""
        event = {
            'po_number': po_number,
            'eventType': event_type,  # po_created, po_dispatched, po_received, po_exception
            'timestamp': datetime.now().isoformat()
        }
        if detail:
            event.update(detail)
        if self.persistence.eventhub:
            self.persistence.eventhub.send_event('purchase_order_events', event)
        logger.debug(f"Emitted PO event: {event_type} for {po_number}")
    
    def _emit_replenishment_event(self, sku: str, location: str, 
                                  quantity: int, po_number: str):
        """Emit stock replenishment event to Event Hub"""
        event = {
            'sku': sku,
            'location': location,
            'quantity': quantity,
            'po_number': po_number,
            'eventType': 'stock_replenished',
            'timestamp': datetime.now().isoformat()
        }
        if self.persistence.eventhub:
            self.persistence.eventhub.send_event('replenishment_events', event)
        logger.debug(f"Emitted replenishment event: {quantity} units of {sku}")
    
    # ========== COSMOS OPERATIONAL EVENT LOG ==========
    
    def _log_inventory_event(self, sku: str, location: str, event_type: str,
                            quantity_change: int, new_quantity: int,
                            reference_id: Optional[str] = None,
                            quantity_before: Optional[int] = None):
        """Log inventory event to CosmosDB (immutable event log) and buffer for ML tables"""
        event_id = str(uuid4())
        event_doc = {
            'id': event_id,
            'eventType': event_type,  # SALE, RECEIPT, ADJUSTMENT, TRANSFER, SHRINKAGE
            'sku': sku,
            'location': location,
            'quantityChange': quantity_change,
            'newOnHandQuantity': new_quantity,
            'referenceId': reference_id,  # PO number, order ID, etc.
            'eventTime': datetime.now().isoformat(),
            'partitionKey': sku  # Partition by SKU for efficient queries
        }

        if self.persistence.cosmos:
            self.persistence.cosmos.write_document('InventoryEvents', event_doc)

        logger.debug(f"Logged inventory event: {event_type} for {sku} at {location}")

        # Buffer for ML PostgreSQL table
        if quantity_before is None:
            quantity_before = new_quantity - quantity_change

        policy = self.replenishment_policies.get((sku, location), {})
        inv = self.resources.inventory.get_inventory(sku, location)
        on_order_qty = getattr(inv, 'on_order_qty', 0) if inv else 0

        self._inventory_event_buffer.append({
            'event_id': event_id,
            'sku': sku,
            'location': location,
            'event_type': event_type,
            'event_time': self.env.now,
            'event_hour': int(self.env.now) % 24,
            'day_of_week': int(self.env.now / 24) % 7,
            'quantity_change': quantity_change,
            'quantity_before': quantity_before,
            'quantity_after': new_quantity,
            'reorder_point': policy.get('reorder_point', 0),
            'safety_stock': policy.get('safety_stock', 0),
            'on_order_qty': on_order_qty,
            'stockout_occurred': new_quantity <= 0,
            'reference_id': reference_id,
        })

        # Update daily snapshot tracker
        key = (sku, location)
        day = int(self.env.now / 24)
        day_key = f'day_{day}'
        if key not in self._daily_snapshot_tracker:
            self._daily_snapshot_tracker[key] = {}
        if day_key not in self._daily_snapshot_tracker[key]:
            self._daily_snapshot_tracker[key][day_key] = {
                'demand': 0, 'receipts': 0, 'stockout_hours': 0.0,
                'reorder_triggered': False, 'last_on_hand': new_quantity,
                'last_on_order': on_order_qty, 'day': day,
            }

        day_data = self._daily_snapshot_tracker[key][day_key]
        if event_type == 'SALE':
            day_data['demand'] += abs(quantity_change)
        elif event_type == 'RECEIPT':
            day_data['receipts'] += quantity_change
        day_data['last_on_hand'] = new_quantity
        day_data['last_on_order'] = on_order_qty
        if new_quantity <= 0:
            day_data['stockout_hours'] += 1.0
    
    # ========== POSTGRES TRANSACTIONAL STATE UPDATES ==========
    
    def _update_inventory_state(self, sku: str, location: str, 
                               on_hand_delta: int, on_order_delta: int = 0):
        """Update inventory state in Postgres (transactional truth)"""
        if self.persistence.postgres:
            self.persistence.postgres.execute_query(
                """
                UPDATE inventory 
                SET quantity_on_hand = quantity_on_hand + %s,
                    on_order_qty = on_order_qty + %s,
                    last_updated = CURRENT_TIMESTAMP
                WHERE sku = %s AND location_id = %s
                """,
                (on_hand_delta, on_order_delta, sku, location)
            )
        
        # Also update in-memory resource registry
        inv = self.resources.inventory.get_inventory(sku, location)
        if inv:
            if on_hand_delta != 0:
                if on_hand_delta > 0:
                    inv.quantity_on_hand += on_hand_delta
                else:
                    inv.quantity_on_hand = max(0, inv.quantity_on_hand + on_hand_delta)
    
    def _create_purchase_order_record(self, po_number: str, supplier_id: str,
                                     sku: str, location: str, quantity: int,
                                     expected_delivery_date: datetime):
        """Create purchase order record in Postgres"""
        if self.persistence.postgres:
            # Create PO header
            self.persistence.postgres.execute_query(
                """
                INSERT INTO purchase_orders (po_number, supplier_id, status, 
                                           expected_delivery_date, created_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                """,
                (po_number, supplier_id, 'PENDING', expected_delivery_date)
            )
            
            # Create PO line
            self.persistence.postgres.execute_query(
                """
                INSERT INTO purchase_order_lines (po_number, sku, location_id,
                                               order_qty, received_qty)
                VALUES (%s, %s, %s, %s, 0)
                """,
                (po_number, sku, location, quantity)
            )
        
        logger.debug(f"Created PO record: {po_number} for {quantity} units of {sku}")
    
    def _update_purchase_order_status(self, po_number: str, status: str, 
                                     received_qty: Optional[int] = None):
        """Update purchase order status in Postgres"""
        if self.persistence.postgres:
            self.persistence.postgres.execute_query(
                """
                UPDATE purchase_orders 
                SET status = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE po_number = %s
                """,
                (status, po_number)
            )
            
            if received_qty is not None:
                self.persistence.postgres.execute_query(
                    """
                    UPDATE purchase_order_lines
                    SET received_qty = %s
                    WHERE po_number = %s
                    """,
                    (received_qty, po_number)
                )
        
        logger.debug(f"Updated PO {po_number} status to {status}")
    
    # ========== DEMAND DEPLETION PROCESS ==========
    
    def demand_depletion_process(self, sku: str, location: str, 
                                mean_daily_demand: float):
        """
        Simulate demand consuming inventory over time
        
        Args:
            sku: Product SKU
            location: Inventory location
            mean_daily_demand: Average daily demand (units/day)
        """
        while self.env.now < self.simulation_end_time:
            # Generate interarrival time for next demand event (Poisson process)
            # Convert daily demand to hourly rate
            hourly_rate = mean_daily_demand / 24.0
            
            if hourly_rate > 0:
                interarrival_hours = random.expovariate(hourly_rate)
            else:
                interarrival_hours = 24.0
            
            yield self.env.timeout(interarrival_hours)
            
            # Check if simulation should end
            if self.env.now >= self.simulation_end_time:
                break
            
            # Generate demand quantity (typically 1 for retail, could be higher)
            ic = self.config.inventory
            demand_qty = random.randint(ic.demand_qty_min, ic.demand_qty_max)
            
            # Get current inventory
            inv = self.resources.inventory.get_inventory(sku, location)
            
            if not inv:
                logger.warning(f"No inventory record for {sku} at {location}")
                continue
            
            # Check if we can fulfill demand
            if inv.quantity_on_hand >= demand_qty:
                # Fulfill demand - deplete inventory
                inv.quantity_on_hand -= demand_qty
                
                # Update Postgres state
                self._update_inventory_state(sku, location, -demand_qty)
                
                # Log event to Cosmos
                self._log_inventory_event(
                    sku, location, 'SALE', -demand_qty, inv.quantity_on_hand,
                    quantity_before=inv.quantity_on_hand + demand_qty
                )
                
                # Emit demand event to Event Hub
                self._emit_demand_event(sku, location, demand_qty)
                
                # Record metrics
                self.metrics.record_metric('inventory_depletion', demand_qty)
                
                logger.debug(f"[{self.env.now:.2f}] Demand fulfilled: {demand_qty} units of {sku} "
                           f"at {location} (remaining: {inv.quantity_on_hand})")
                
                # Check if we hit reorder point after depletion
                yield self.env.process(self._check_reorder_trigger(sku, location))
                
            else:
                # STOCKOUT - cannot fulfill demand
                logger.warning(f"[{self.env.now:.2f}] STOCKOUT: {sku} at {location} "
                             f"(demanded {demand_qty}, available {inv.quantity_on_hand})")
                
                # Record stockout
                self.metrics.record_metric('stockouts', 1)
                self.metrics.record_metric('lost_sales_units', demand_qty)
                
                # Emit low stock alert
                self._emit_inventory_signal(
                    sku, location, 'stockout_occurred',
                    {'demanded': demand_qty, 'available': inv.quantity_on_hand}
                )
                
                # Add to backorder queue if enabled
                key = (sku, location)
                if key not in self.backorders:
                    self.backorders[key] = []
                
                self.backorders[key].append({
                    'quantity': demand_qty,
                    'time': self.env.now,
                    'backorder_id': str(uuid4())
                })
    
    # ========== REORDER EVALUATION PROCESS ==========
    
    def _check_reorder_trigger(self, sku: str, location: str):
        """Check if reorder point is reached and trigger replenishment if needed"""
        
        key = (sku, location)
        policy = self.replenishment_policies.get(key)
        
        if not policy:
            logger.debug(f"No replenishment policy for {sku} at {location}")
            return
        
        inv = self.resources.inventory.get_inventory(sku, location)
        if not inv:
            return
        
        # Calculate inventory position (on_hand + on_order)
        inventory_position = inv.quantity_on_hand  # Simplified (could add on_order)
        reorder_point = policy['reorder_point']
        
        # Check if we're at or below ROP and not already on order
        if inventory_position <= reorder_point:
            
            # Emit low stock alert to Event Hub
            self._emit_inventory_signal(
                sku, location, 'low_stock_alert',
                {
                    'current_stock': inventory_position,
                    'reorder_point': reorder_point,
                    'safety_stock': policy['safety_stock']
                }
            )
            
            # Trigger reorder
            logger.info(f"[{self.env.now:.2f}] REORDER TRIGGERED: {sku} at {location} "
                       f"(stock: {inventory_position}, ROP: {reorder_point})")

            # Track reorder in daily snapshot
            day = int(self.env.now / 24)
            day_key = f'day_{day}'
            if key in self._daily_snapshot_tracker and day_key in self._daily_snapshot_tracker[key]:
                self._daily_snapshot_tracker[key][day_key]['reorder_triggered'] = True

            # Create purchase order
            yield self.env.process(
                self._create_purchase_order(
                    sku, location, policy['order_quantity'], policy['supplier_id']
                )
            )
    
    def _create_purchase_order(self, sku: str, location: str, 
                              quantity: int, supplier_id: str):
        """Create and process a purchase order"""
        
        # Generate PO number
        self.po_counter += 1
        po_number = f"PO-{datetime.now().strftime('%Y%m%d')}-{self.po_counter:05d}"
        
        supplier = self.suppliers.get(supplier_id)
        if not supplier:
            logger.error(f"Supplier {supplier_id} not found")
            return
        
        # Adjust quantity for minimum order quantity
        order_quantity = max(quantity, supplier['min_order_qty'])
        
        # Generate lead time with variability
        mean_lt = supplier['mean_lead_time']
        std_lt = supplier['lead_time_std']
        ic = self.config.inventory
        lead_time_days = max(ic.min_lead_time_enforced, random.normalvariate(mean_lt, std_lt))

        # Check supplier reliability (may have delays)
        if random.random() > supplier['reliability']:
            # Unreliable delivery - add extra delay
            delay_factor = random.uniform(ic.unreliable_delay_min, ic.unreliable_delay_max)
            lead_time_days *= delay_factor
            logger.warning(f"Supplier {supplier_id} delayed - lead time extended to {lead_time_days:.1f} days")
        
        # Calculate expected delivery date
        expected_delivery = datetime.now() + timedelta(days=lead_time_days)
        
        # Create PO record
        po_data = {
            'po_number': po_number,
            'sku': sku,
            'location': location,
            'supplier_id': supplier_id,
            'order_qty': order_quantity,
            'status': 'PENDING',
            'created_time': self.env.now,
            'expected_delivery_time': self.env.now + (lead_time_days * 24),  # hours
            'lead_time_days': lead_time_days
        }
        
        self.purchase_orders[po_number] = po_data
        
        # Persist to Postgres
        self._create_purchase_order_record(
            po_number, supplier_id, sku, location, order_quantity, expected_delivery
        )
        
        # Update on_order quantity in inventory
        self._update_inventory_state(sku, location, 0, order_quantity)
        
        # Emit PO created event
        self._emit_po_event(po_number, 'po_created', {
            'sku': sku,
            'location': location,
            'quantity': order_quantity,
            'supplier_id': supplier_id,
            'expected_delivery_days': lead_time_days
        })
        
        # Record metrics
        self.metrics.record_metric('purchase_orders_created', 1)
        self.metrics.record_metric('total_units_ordered', order_quantity)
        
        logger.info(f"[{self.env.now:.2f}] Created PO {po_number}: {order_quantity} units of {sku} "
                   f"from {supplier_id} (lead time: {lead_time_days:.1f} days)")
        
        # Schedule delivery process (yield to make this a generator for SimPy)
        yield self.env.process(self._delivery_process(po_number))
    
    # ========== SUPPLY CHAIN EXECUTION ==========
    
    def _delivery_process(self, po_number: str):
        """Simulate shipment in transit and delivery"""
        
        po_data = self.purchase_orders.get(po_number)
        if not po_data:
            return
        
        # Wait for lead time
        lead_time_hours = po_data['expected_delivery_time'] - self.env.now
        
        # Emit dispatched event
        self._emit_po_event(po_number, 'po_dispatched', {
            'expected_arrival_hours': lead_time_hours
        })
        
        # Update PO status
        po_data['status'] = 'IN_TRANSIT'
        self._update_purchase_order_status(po_number, 'IN_TRANSIT')
        
        logger.debug(f"[{self.env.now:.2f}] PO {po_number} dispatched - arriving in {lead_time_hours:.1f} hours")
        
        # Wait for delivery
        yield self.env.timeout(lead_time_hours)
        
        # Delivery arrived - process receiving
        yield self.env.process(self._receiving_process(po_number))
    
    def _receiving_process(self, po_number: str):
        """Process goods receiving and update inventory"""
        
        po_data = self.purchase_orders.get(po_number)
        if not po_data:
            return
        
        sku = po_data['sku']
        location = po_data['location']
        order_qty = po_data['order_qty']
        
        # Simulate receiving process time (inspection, unloading, put-away)
        ic = self.config.inventory
        receiving_time_minutes = random.uniform(ic.receiving_time_min, ic.receiving_time_max)
        yield self.env.timeout(receiving_time_minutes / 60.0)  # Convert to hours

        # Simulate possible short shipment (supplier sends less than ordered)
        if random.random() < ic.short_shipment_probability:
            received_qty = int(order_qty * random.uniform(ic.short_shipment_qty_min, ic.short_shipment_qty_max))
            logger.warning(f"Short shipment on PO {po_number}: received {received_qty}/{order_qty}")
        else:
            received_qty = order_qty
        
        # Update inventory: increase on_hand, decrease on_order
        self._update_inventory_state(sku, location, received_qty, -order_qty)
        
        # Log receipt event to Cosmos
        inv = self.resources.inventory.get_inventory(sku, location)
        new_quantity = inv.quantity_on_hand if inv else received_qty
        
        self._log_inventory_event(
            sku, location, 'RECEIPT', received_qty, new_quantity, po_number,
            quantity_before=new_quantity - received_qty
        )
        
        # Emit replenishment event to Event Hub
        self._emit_replenishment_event(sku, location, received_qty, po_number)
        
        # Emit PO received event
        self._emit_po_event(po_number, 'po_received', {
            'received_qty': received_qty,
            'ordered_qty': order_qty
        })
        
        # Update PO status
        po_data['status'] = 'RECEIVED'
        po_data['received_qty'] = received_qty
        po_data['received_time'] = self.env.now
        
        self._update_purchase_order_status(po_number, 'RECEIVED', received_qty)
        
        # Update supplier performance metrics
        supplier_id = po_data['supplier_id']
        supplier = self.suppliers.get(supplier_id)
        if supplier:
            supplier['total_orders'] += 1
            actual_lead_time = (po_data['received_time'] - po_data['created_time']) / 24.0
            supplier['total_lead_time'] += actual_lead_time
            
            # Check if on-time
            if actual_lead_time <= po_data['lead_time_days'] * self.config.inventory.on_time_delivery_tolerance:
                supplier['on_time_deliveries'] += 1
        
        # Record metrics
        self.metrics.record_metric('shipments_received', 1)
        self.metrics.record_metric('units_received', received_qty)
        
        logger.info(f"[{self.env.now:.2f}] Received PO {po_number}: {received_qty} units of {sku} "
                   f"at {location} (new stock: {new_quantity})")
        
        # Process any backorders
        yield self.env.process(self._fulfill_backorders(sku, location))
    
    def _fulfill_backorders(self, sku: str, location: str):
        """Attempt to fulfill backorders after receiving stock"""
        
        key = (sku, location)
        if key not in self.backorders or not self.backorders[key]:
            return
        
        inv = self.resources.inventory.get_inventory(sku, location)
        if not inv:
            return
        
        backorder_queue = self.backorders[key]
        fulfilled = []
        
        for backorder in backorder_queue[:]:  # Copy to allow removal
            if inv.quantity_on_hand >= backorder['quantity']:
                # Fulfill backorder
                inv.quantity_on_hand -= backorder['quantity']
                
                logger.info(f"[{self.env.now:.2f}] Fulfilled backorder: {backorder['quantity']} "
                          f"units of {sku} at {location}")
                
                self.metrics.record_metric('backorders_fulfilled', 1)
                fulfilled.append(backorder)
            else:
                break  # Stop if not enough stock
        
        # Remove fulfilled backorders
        for backorder in fulfilled:
            backorder_queue.remove(backorder)
        
        yield self.env.timeout(0)  # Yield control
    
    # ========== INVENTORY ADJUSTMENT PROCESSES ==========
    
    def shrinkage_process(self, sku: str, location: str):
        """
        Simulate inventory shrinkage (theft, damage, miscount)

        Args:
            sku: Product SKU
            location: Inventory location
        """
        daily_shrinkage_rate = self.config.inventory.daily_shrinkage_rate
        while self.env.now < self.simulation_end_time:
            # Daily shrinkage check
            yield self.env.timeout(24.0)  # Check daily
            
            # Check if simulation should end
            if self.env.now >= self.simulation_end_time:
                break
            
            inv = self.resources.inventory.get_inventory(sku, location)
            if not inv or inv.quantity_on_hand == 0:
                continue
            
            # Calculate shrinkage amount (Poisson distribution)
            expected_shrinkage = inv.quantity_on_hand * daily_shrinkage_rate
            shrinkage_qty = np.random.poisson(expected_shrinkage)
            
            if shrinkage_qty > 0:
                shrinkage_qty = min(shrinkage_qty, inv.quantity_on_hand)  # Can't shrink more than available
                
                # Apply shrinkage
                self._update_inventory_state(sku, location, -shrinkage_qty)
                
                # Log adjustment event
                self._log_inventory_event(
                    sku, location, 'SHRINKAGE', -shrinkage_qty,
                    inv.quantity_on_hand - shrinkage_qty, 'SHRINKAGE',
                    quantity_before=inv.quantity_on_hand
                )
                
                # Record metrics
                self.metrics.record_metric('inventory_shrinkage', shrinkage_qty)
                
                logger.debug(f"[{self.env.now:.2f}] Shrinkage: {shrinkage_qty} units of {sku} "
                           f"at {location}")
    
    def periodic_review_process(self, sku: str, location: str):
        """
        Periodic inventory review and adjustment

        Checks inventory accuracy and makes adjustments
        """
        review_interval_days = self.config.inventory.review_interval_days
        while self.env.now < self.simulation_end_time:
            # Wait for review interval
            yield self.env.timeout(review_interval_days * 24.0)
            
            # Check if simulation should end
            if self.env.now >= self.simulation_end_time:
                break
            
            inv = self.resources.inventory.get_inventory(sku, location)
            if not inv:
                continue
            
            # Simulate audit discrepancy (small random adjustment)
            ic = self.config.inventory
            if random.random() < ic.audit_discrepancy_probability:
                adjustment = random.randint(ic.audit_adjustment_min, ic.audit_adjustment_max)
                
                if adjustment != 0:
                    new_qty = max(0, inv.quantity_on_hand + adjustment)
                    actual_adjustment = new_qty - inv.quantity_on_hand
                    
                    self._update_inventory_state(sku, location, actual_adjustment)
                    
                    self._log_inventory_event(
                        sku, location, 'ADJUSTMENT', actual_adjustment, new_qty, 'AUDIT',
                        quantity_before=inv.quantity_on_hand
                    )
                    
                    logger.info(f"[{self.env.now:.2f}] Inventory audit adjustment: {actual_adjustment} "
                              f"units of {sku} at {location}")
    
    # ========== WORKFLOW ORCHESTRATION ==========
    
    def start_monitoring(self, sku: str, location: str, mean_daily_demand: float):
        """
        Start complete monitoring and replenishment for a SKU at a location
        
        This starts all necessary processes:
        - Demand depletion
        - Shrinkage
        - Periodic review
        """
        logger.info(f"Starting inventory monitoring for {sku} at {location} "
                   f"(demand: {mean_daily_demand:.1f} units/day)")
        
        # Start demand depletion process
        self.env.process(self.demand_depletion_process(sku, location, mean_daily_demand))
        
        # Start shrinkage process
        self.env.process(self.shrinkage_process(sku, location))
        
        # Start periodic review process
        self.env.process(self.periodic_review_process(sku, location))
    
    def get_supplier_performance(self, supplier_id: str) -> Optional[Dict]:
        """Get performance metrics for a supplier"""
        supplier = self.suppliers.get(supplier_id)
        if not supplier:
            return None
        
        total_orders = supplier['total_orders']
        if total_orders == 0:
            return {
                'supplier_id': supplier_id,
                'name': supplier['name'],
                'total_orders': 0,
                'on_time_rate': 0.0,
                'avg_lead_time': supplier['mean_lead_time']
            }
        
        on_time_rate = supplier['on_time_deliveries'] / total_orders
        avg_lead_time = supplier['total_lead_time'] / total_orders
        
        return {
            'supplier_id': supplier_id,
            'name': supplier['name'],
            'total_orders': total_orders,
            'on_time_rate': on_time_rate,
            'avg_lead_time': avg_lead_time
        }
    def print_inventory_summary(self):
        """Print inventory-specific metrics summary"""
        print("\n" + "="*80)
        print("INVENTORY REPLENISHMENT WORKFLOW SUMMARY")
        print("="*80)

        # Purchase Order metrics
        po_created = self.metrics.custom_metrics.get('purchase_orders_created', 0)
        units_ordered = self.metrics.custom_metrics.get('total_units_ordered', 0)
        shipments_received = self.metrics.custom_metrics.get('shipments_received', 0)
        units_received = self.metrics.custom_metrics.get('units_received', 0)

        print(f"\n📦 PURCHASE ORDER METRICS")
        print(f"  Purchase Orders Created: {int(po_created)}")
        print(f"  Total Units Ordered: {int(units_ordered):,}")
        print(f"  Shipments Received: {int(shipments_received)}")
        print(f"  Total Units Received: {int(units_received):,}")

        # Stockout metrics
        stockouts = self.metrics.custom_metrics.get('stockouts', 0)
        lost_sales = self.metrics.custom_metrics.get('lost_sales_units', 0)
        backorders_fulfilled = self.metrics.custom_metrics.get('backorders_fulfilled', 0)

        print(f"\n⚠️  STOCKOUT & BACKORDER METRICS")
        print(f"  Total Stockouts: {int(stockouts)}")
        print(f"  Lost Sales (units): {int(lost_sales):,}")
        print(f"  Backorders Fulfilled: {int(backorders_fulfilled)}")

        # Inventory metrics
        depletion = self.metrics.custom_metrics.get('inventory_depletion', 0)
        shrinkage = self.metrics.custom_metrics.get('inventory_shrinkage', 0)

        print(f"\n📊 INVENTORY ACTIVITY")
        print(f"  Total Units Depleted (sales): {int(depletion):,}")
        print(f"  Total Shrinkage (loss): {int(shrinkage):,}")

        # Active policies
        print(f"\n📋 REPLENISHMENT POLICIES")
        print(f"  Active SKU/Location Policies: {len(self.replenishment_policies)}")

        # Supplier Performance
        print(f"\n🏭 SUPPLIER PERFORMANCE")
        if self.suppliers:
            for supplier_id, supplier in self.suppliers.items():
                if supplier['total_orders'] > 0:
                    on_time_rate = supplier['on_time_deliveries'] / supplier['total_orders'] * 100
                    avg_lead_time = supplier['total_lead_time'] / supplier['total_orders']
                    print(f"  {supplier['name']}:")
                    print(f"    Orders: {supplier['total_orders']}")
                    print(f"    On-Time Rate: {on_time_rate:.1f}%")
                    print(f"    Avg Lead Time: {avg_lead_time:.1f} days")
        else:
            print("  No supplier activity recorded")

        print("=" * 80 + "\n")


# ========== ML DATA PERSISTENCE ==========

    def persist_ml_data(self, scenario_id: str) -> None:
        """
        Persist inventory data for ML training.
        Flushes in-memory event buffers to PostgreSQL ML tables.

        Writes to:
        - inventory_events: From buffered SALE/RECEIPT/SHRINKAGE/ADJUSTMENT events
        - supplier_deliveries: From all purchase orders (including in-transit)
        - inventory_snapshots: From daily snapshot tracker (actual daily data)

        Args:
            scenario_id: Unique scenario identifier
        """
        from uuid import uuid4

        conn = self.persistence.postgres._conn

        # 1. Flush inventory_events buffer (real per-event records)
        event_count = 0
        for evt in self._inventory_event_buffer:
            conn.execute(
                """
                INSERT INTO inventory_events
                    (event_id, scenario_id, sku, location, event_type, event_time,
                     event_hour, day_of_week, quantity_change,
                     quantity_before, quantity_after,
                     reorder_point, safety_stock, on_order_qty,
                     stockout_occurred, reference_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evt['event_id'],
                    scenario_id,
                    evt['sku'],
                    evt['location'],
                    evt['event_type'],
                    evt['event_time'],
                    evt['event_hour'],
                    evt['day_of_week'],
                    evt['quantity_change'],
                    evt['quantity_before'],
                    evt['quantity_after'],
                    evt['reorder_point'],
                    evt['safety_stock'],
                    evt['on_order_qty'],
                    evt['stockout_occurred'],
                    evt['reference_id'],
                ),
            )
            event_count += 1

        logger.info(f"Persisted {event_count} inventory events for scenario {scenario_id}")

        # 2. Flush supplier deliveries (ALL POs, not just RECEIVED)
        delivery_count = 0
        for po_number, po_data in self.purchase_orders.items():
            delivery_id = str(uuid4())
            expected_lt = po_data['lead_time_days']
            po_status = po_data.get('status', 'PENDING')

            if po_status == 'RECEIVED':
                actual_delivery_time = po_data.get('received_time', self.env.now)
                actual_lt = (actual_delivery_time - po_data['created_time']) / 24.0
                received_qty = po_data.get('received_qty', po_data['order_qty'])
                on_time = actual_lt <= expected_lt * 1.1
                short_shipped = received_qty < po_data['order_qty']
            else:
                actual_delivery_time = None
                actual_lt = None
                received_qty = 0
                on_time = None
                short_shipped = None

            conn.execute(
                """
                INSERT INTO supplier_deliveries
                    (delivery_id, scenario_id, supplier_id, po_number,
                     sku, location, order_quantity, received_quantity,
                     order_time, expected_delivery_time, actual_delivery_time,
                     expected_lead_time_days, actual_lead_time_days,
                     on_time, short_shipped, po_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    delivery_id,
                    scenario_id,
                    po_data['supplier_id'],
                    po_number,
                    po_data['sku'],
                    po_data.get('location', ''),
                    po_data['order_qty'],
                    received_qty,
                    po_data['created_time'],
                    po_data.get('expected_delivery_time'),
                    actual_delivery_time,
                    expected_lt,
                    actual_lt,
                    on_time,
                    short_shipped,
                    po_status,
                ),
            )
            delivery_count += 1

        logger.info(f"Persisted {delivery_count} supplier deliveries for scenario {scenario_id}")

        # 3. Flush inventory snapshots (one row per SKU-location per day)
        snapshot_count = 0
        for (sku, location), day_data_map in self._daily_snapshot_tracker.items():
            for day_key, day_data in day_data_map.items():
                snapshot_id = f"{scenario_id}_{sku}_{location}_{day_data['day']}"
                conn.execute(
                    """
                    INSERT INTO inventory_snapshots
                        (snapshot_id, scenario_id, sku, location, snapshot_day,
                         quantity_on_hand, quantity_on_order, daily_demand,
                         daily_receipts, stockout_hours, reorder_triggered)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (snapshot_id) DO UPDATE SET
                        quantity_on_hand = excluded.quantity_on_hand,
                        daily_demand = excluded.daily_demand
                    """,
                    (
                        snapshot_id,
                        scenario_id,
                        sku,
                        location,
                        day_data['day'],
                        day_data['last_on_hand'],
                        day_data['last_on_order'],
                        day_data['demand'],
                        day_data['receipts'],
                        day_data['stockout_hours'],
                        day_data['reorder_triggered'],
                    ),
                )
                snapshot_count += 1

        logger.info(f"Persisted {snapshot_count} inventory snapshots for scenario {scenario_id}")


# ========== WORKFLOW FACTORY ==========

def create_inventory_workflow(env: simpy.Environment, config: SimulationConfig,
                              resources: ResourceRegistry, persistence: PersistenceManager,
                              metrics: MetricsCollector) -> InventoryReplenishmentWorkflow:
    """Factory function to create and configure inventory workflow"""
    workflow = InventoryReplenishmentWorkflow(env, config, resources, persistence, metrics)
    return workflow
