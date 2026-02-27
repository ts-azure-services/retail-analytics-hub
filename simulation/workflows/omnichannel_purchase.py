"""
Omnichannel Purchase & Fulfillment Workflow (Workflow 1).

Models the complete customer purchase journey across multiple channels:
- In-store: Walk-in → Browse → Queue → Checkout → Payment → Exit
- Online: Browse → Cart → Checkout → Payment → Fulfillment → Delivery  
- BOPIS: Browse online → Payment → Store pickup

Includes:
- Random customer arrivals with time-of-day patterns
- Browsing and cart abandonment
- Queue management and checkout processing
- Payment processing with failure probability
- Multi-channel fulfillment
- Post-purchase returns

State persistence to Postgres, CosmosDB, and Event Hub.
"""

import simpy
import random
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from uuid import uuid4
import numpy as np

from ..shared.persistence import USE_LOCAL_DB
if not USE_LOCAL_DB:
    from azure.cosmos.exceptions import CosmosHttpResponseError
else:
    # Stub so except clauses still parse when running locally
    CosmosHttpResponseError = Exception

from ..shared.config import SimulationConfig
from ..shared.resources import ResourceRegistry
from ..shared.persistence import PersistenceManager
from ..shared.metrics import MetricsCollector


logger = logging.getLogger(__name__)


class OmnichannelPurchaseWorkflow:
    """Omnichannel purchase and fulfillment simulation workflow"""
    
    def __init__(self, env: simpy.Environment, config: SimulationConfig,
                 resources: ResourceRegistry, persistence: PersistenceManager,
                 metrics: MetricsCollector):
        self.env = env
        self.config = config
        self.resources = resources
        self.persistence = persistence
        self.metrics = metrics
        
        # Product catalog cache (SKU -> product_id, price, category)
        self.product_catalog: Dict[str, Tuple[int, float, str]] = {}
        
        # Real customer IDs from CosmosDB (loaded at initialization)
        self.real_customer_ids: List[str] = []
        
        # Customer ID counter (fallback only)
        self.customer_counter = 0
        
        logger.info("Omnichannel Purchase Workflow initialized")
    
    def load_product_catalog(self, products: List[Tuple]):
        """Load product catalog for SKU selection"""
        for product in products:
            product_id, sku, price, category = product
            self.product_catalog[sku] = (product_id, price, category)
        logger.info(f"Loaded {len(self.product_catalog)} products into catalog")
    
    def load_real_customers(self):
        """Load real customer IDs from CosmosDB Customers container"""
        try:
            customers_container = self.persistence.cosmos.database.get_container_client('Customers')
            
            # Query for customer IDs only (efficient - no need to fetch full documents)
            query = "SELECT c.customerId FROM c"
            customers = list(customers_container.query_items(
                query=query,
                enable_cross_partition_query=True
            ))
            
            self.real_customer_ids = [c['customerId'] for c in customers if 'customerId' in c]
            
            if self.real_customer_ids:
                logger.info(f"✓ Loaded {len(self.real_customer_ids)} real customer IDs from CosmosDB")
            else:
                error_msg = "✗ No customers found in CosmosDB. Data integrity requirement violated."
                logger.error(error_msg)
                logger.error("  Run 'make seed-all-with-history' to seed real customer data.")
                raise ValueError(error_msg)
            
        except CosmosHttpResponseError as e:
            error_msg = f"✗ Failed to fetch customers from CosmosDB: {getattr(e, 'message', str(e))}"
            logger.error(error_msg)
            logger.error("  Ensure CosmosDB is accessible and seeded with data.")
            raise
        except Exception as e:
            error_msg = f"✗ Could not load customers from CosmosDB: {e}"
            logger.error(error_msg)
            logger.error("  Run 'make seed-all-with-history' to seed real customer data.")
            raise
    
    # ========== EVENT HUB EVENT EMISSION ==========
    
    def _emit_interaction_event(self, customer_id: str, session_id: str, 
                                event_type: str, detail: Dict):
        """Emit customer interaction event to Event Hub"""
        event = {
            'customer_id': customer_id,
            'session_id': session_id,
            'eventType': event_type,
            'detail': detail,
            'timestamp': datetime.now().isoformat()
        }
        if self.persistence.eventhub:
            self.persistence.eventhub.send_event('interaction_events', event)
        logger.debug(f"Emitted interaction event: {event_type} for {customer_id}")
    
    def _emit_cart_event(self, cart_id: str, event_type: str, 
                        sku: Optional[str] = None, qty: Optional[int] = None):
        """Emit cart event to Event Hub (leading funnel signals)"""
        event = {
            'cartId': cart_id,
            'eventType': event_type,  # item_added, item_removed, cart_checked_out, cart_abandoned
            'sku': sku,
            'qty': qty,
            'timestamp': datetime.now().isoformat()
        }
        if self.persistence.eventhub:
            self.persistence.eventhub.send_event('cart_events', event)
        logger.debug(f"Emitted cart event: {event_type} for cart {cart_id}")
    
    def _emit_order_event(self, order_id: Optional[int], event_type: str, 
                         detail: Optional[Dict] = None):
        """Emit order event to Event Hub (business/system broadcasts)"""
        event = {
            'order_id': str(order_id) if order_id else None,
            'eventType': event_type,  # order_placed, payment_authorized, payment_failed
            'timestamp': datetime.now().isoformat()
        }
        if detail:
            event.update(detail)
        if self.persistence.eventhub:
            self.persistence.eventhub.send_event('order_events', event)
        logger.debug(f"Emitted order event: {event_type}")
    
    def _emit_fulfillment_event(self, order_id: int, event_type: str, 
                               location: str, detail: Optional[Dict] = None):
        """Emit fulfillment event to Event Hub (operational broadcasts)"""
        event = {
            'order_id': str(order_id),
            'eventType': event_type,  # picked, packed, shipped, delivered, exception
            'location': location,
            'timestamp': datetime.now().isoformat()
        }
        if detail:
            event.update(detail)
        if self.persistence.eventhub:
            self.persistence.eventhub.send_event('fulfillment_events', event)
        logger.debug(f"Emitted fulfillment event: {event_type} for order {order_id}")
    
    # ========== COSMOS OPERATIONAL STATE UPDATES ==========
    
    def _update_cart_state(self, cart_id: str, customer_id: str, 
                          channel: str, basket: List[Dict], status: str):
        """Update current cart state in Cosmos (operational state only)"""
        cart_doc = {
            'id': cart_id,
            'cartId': cart_id,
            'userId': customer_id,
            'channel': channel,
            'items': [
                {
                    'sku': item['sku'],
                    'qty': item['quantity'],
                    'price': item['price']
                }
                for item in basket
            ],
            'lastUpdateTime': datetime.now().isoformat(),
            'status': status  # active, abandoned, checked_out
        }
        self.persistence.cosmos.write_cart(cart_doc)
        logger.debug(f"Updated cart state: {cart_id} status={status}")
    
    def _update_fulfillment_state(self, order_id: int, fulfillment_status: str, 
                                 location: str, tracking: Optional[str] = None):
        """Update current fulfillment state in Cosmos (operational state only)"""
        fulfillment_doc = {
            'id': f"FUL-{order_id}",
            'order_id': str(order_id),
            'fulfillment_status': fulfillment_status,  # pending, picked, packed, shipped, delivered, exception
            'lastUpdateTime': datetime.now().isoformat(),
            'location': location,
            'tracking': tracking
        }
        self.persistence.cosmos.write_document('FulfillmentState', fulfillment_doc)
        logger.debug(f"Updated fulfillment state: order {order_id} status={fulfillment_status}")
    
    # ========== ARRIVAL PROCESSES ==========
    
    def online_arrival_process(self):
        """Generate online customer arrivals"""
        yield from self._customer_arrival_generator("online", 
                                                    self.config.distributions.arrival_rate_online)
    
    def in_store_arrival_process(self):
        """Generate in-store customer arrivals"""
        yield from self._customer_arrival_generator("in_store",
                                                    self.config.distributions.arrival_rate_in_store)
    
    def bopis_arrival_process(self):
        """Generate BOPIS customer arrivals"""
        yield from self._customer_arrival_generator("bopis",
                                                    self.config.distributions.arrival_rate_bopis)
    
    def _customer_arrival_generator(self, channel: str, base_rate: float):
        """
        Generic customer arrival generator with time-of-day patterns
        
        Args:
            channel: Customer channel (online, in_store, bopis)
            base_rate: Base arrival rate (customers per hour)
        """
        while True:
            # Get current hour for time-of-day multiplier
            current_hour = int(self.env.now % 24)
            multiplier = self.config.distributions.time_of_day_multipliers[current_hour]
            
            # Adjusted arrival rate
            adjusted_rate = base_rate * multiplier
            
            # Interarrival time (exponential distribution)
            if adjusted_rate > 0:
                interarrival_minutes = random.expovariate(adjusted_rate / 60.0)
            else:
                interarrival_minutes = 60.0  # Low activity period
            
            yield self.env.timeout(interarrival_minutes)
            
            # Select customer ID from real CosmosDB customers (no fallback)
            if not self.real_customer_ids:
                logger.error("Cannot generate customer arrival: No real customers loaded")
                return  # Stop generating arrivals
            
            customer_id = random.choice(self.real_customer_ids)
            
            # Start customer journey process
            self.env.process(self.customer_journey_process(customer_id, channel))
    
    # ========== CUSTOMER JOURNEY ==========
    
    def customer_journey_process(self, customer_id: str, channel: str):
        """
        Main customer journey process - routes to channel-specific flows
        
        Args:
            customer_id: Unique customer identifier
            channel: Customer channel (online, in_store, bopis)
        """
        arrival_time = self.env.now
        self.metrics.record_customer_arrival(customer_id, channel, arrival_time)
        
        logger.debug(f"[{self.env.now:.2f}] {customer_id} arrived via {channel}")
        
        # Route to channel-specific journey
        if channel == "in_store":
            yield from self._in_store_journey(customer_id, arrival_time)
        elif channel == "online":
            yield from self._online_journey(customer_id, arrival_time)
        elif channel == "bopis":
            yield from self._bopis_journey(customer_id, arrival_time)
    
    def _in_store_journey(self, customer_id: str, arrival_time: float):
        """In-store customer journey with sensor telemetry"""
        
        session_id = str(uuid4())
        store_location = self.config.resources.default_store
        
        # Entry event (sensor detection)
        self._emit_interaction_event(
            customer_id, session_id, 'enter_store',
            {'location': store_location, 'entry_time': datetime.now().isoformat()}
        )
        
        # 1. BROWSING with item pickups
        browsing_time = random.triangular(
            self.config.distributions.browsing_time_min,
            self.config.distributions.browsing_time_mode,
            self.config.distributions.browsing_time_max
        )
        
        # Simulate picking up items during browsing (sensor events)
        num_pickups = random.randint(3, 8)
        for _ in range(num_pickups):
            yield self.env.timeout(browsing_time / num_pickups)
            if self.product_catalog:
                picked_sku = random.choice(list(self.product_catalog.keys()))
                self._emit_interaction_event(
                    customer_id, session_id, 'pickup_item',
                    {'sku': picked_sku, 'timestamp': datetime.now().isoformat()}
                )
        
        # Select basket (try real cart first, fall back to synthetic)
        basket = self._generate_basket(customer_id)
        self.metrics.record_browsing_complete(customer_id, browsing_time, len(basket) if basket else 0)
        
        # Check abandonment or no cart available
        if not basket or random.random() < self.config.distributions.abandonment_rate_in_store:
            reason = "no_cart_data" if not basket else "in_store_browsing"
            self._emit_interaction_event(customer_id, session_id, 'exit_store', {'purchased': False})
            self.metrics.record_abandonment(customer_id, reason)
            logger.debug(f"[{self.env.now:.2f}] {customer_id} left without purchase ({reason})")
            return
        
        # 2. QUEUE FOR CHECKOUT
        checkout_resource = self.resources.get_checkout_resource(store_location)
        
        if not checkout_resource:
            logger.warning(f"No checkout resource for {store_location}")
            self.metrics.record_abandonment(customer_id, "no_checkout")
            return
        
        # Check queue length - may balk if too long
        queue_length = len(checkout_resource.queue)
        if queue_length > 10:  # Arbitrary threshold
            if random.random() < 0.3:  # 30% chance to balk
                self.metrics.record_abandonment(customer_id, "queue_too_long")
                logger.debug(f"[{self.env.now:.2f}] {customer_id} balked due to long queue")
                return
        
        queue_start = self.env.now
        with checkout_resource.request() as req:
            yield req
            queue_wait = self.env.now - queue_start
            self.metrics.record_queue_wait(customer_id, queue_wait)
            
            # 3. CHECKOUT SERVICE
            checkout_time = random.triangular(
                self.config.distributions.service_time_checkout_min,
                self.config.distributions.service_time_checkout_mode,
                self.config.distributions.service_time_checkout_max
            )
            yield self.env.timeout(checkout_time)
        
        total_amount = sum([item['price'] * item['quantity'] for item in basket])
        self.metrics.record_checkout(customer_id, checkout_time, total_amount)
        
        # 4. PAYMENT
        payment_success, order_id = self._process_payment(
            customer_id, basket, total_amount, "in_store", store_location
        )
        
        if not payment_success:
            return
        
        # 5. IN-STORE FULFILLMENT (immediate) - Mark as COMPLETED
        logger.debug(f"[{self.env.now:.2f}] {customer_id} completed in-store purchase: Order {order_id}")
        
        # Update order status to COMPLETED (critical for analytics)
        self.persistence.postgres.update_order_status(order_id, "COMPLETED", "COMPLETED")
        self._emit_order_event(order_id, 'order_completed', {
            'channel': 'in_store',
            'customer_id': customer_id,
            'completion_time': datetime.now().isoformat()
        })
        self.metrics.record_fulfillment_complete(order_id, self.env.now, self.env.now)
        
        logger.info(f"Order {order_id} COMPLETED for customer {customer_id} (in-store)")
        
        # Optionally model returns
        yield from self._handle_potential_return(order_id, basket)
    
    def _online_journey(self, customer_id: str, arrival_time: float):
        """Online customer journey with web telemetry"""
        
        session_id = str(uuid4())
        
        # Session start
        self._emit_interaction_event(
            customer_id, session_id, 'session_start',
            {'channel': 'web', 'referrer': random.choice(['google', 'direct', 'email', 'social'])}
        )
        
        # 1. BROWSING with page views and searches
        browsing_time = random.triangular(
            self.config.distributions.browsing_time_min,
            self.config.distributions.browsing_time_mode,
            self.config.distributions.browsing_time_max
        )
        
        # Simulate page views
        num_pages = random.randint(2, 8)
        for i in range(num_pages):
            yield self.env.timeout(browsing_time / num_pages)
            page_type = random.choice(['category', 'product_detail', 'search'])
            
            if page_type == 'search':
                self._emit_interaction_event(
                    customer_id, session_id, 'search',
                    {'query': f"search_term_{random.randint(1, 100)}", 
                     'results_count': random.randint(5, 50)}
                )
            else:
                viewed_sku = random.choice(list(self.product_catalog.keys())) if i > 0 and self.product_catalog else None
                self._emit_interaction_event(
                    customer_id, session_id, 'view',
                    {'page_type': page_type, 'sku': viewed_sku}
                )
        
        # Select basket (try real cart first, fall back to synthetic)
        basket = self._generate_basket(customer_id)
        self.metrics.record_browsing_complete(customer_id, browsing_time, len(basket) if basket else 0)
        
        # 2. CART CREATION - Update operational state in Cosmos
        cart_id = str(uuid4())
        if basket:
            self._update_cart_state(cart_id, customer_id, 'online', basket, 'active')
            
            # Emit cart events to Event Hub for each item
            for item in basket:
                self._emit_cart_event(cart_id, 'item_added', item['sku'], item['quantity'])
        
        # Check abandonment
        if random.random() < self.config.distributions.abandonment_rate_online or not basket:
            # Update cart state to abandoned
            if basket:
                self._update_cart_state(cart_id, customer_id, 'online', basket, 'abandoned')
            # Emit abandonment event
            self._emit_cart_event(cart_id, 'cart_abandoned')
            self.metrics.record_abandonment(customer_id, "online_cart_abandoned")
            logger.debug(f"[{self.env.now:.2f}] {customer_id} abandoned online cart")
            return
        
        # 3. CHECKOUT (no queue for online)
        checkout_time = random.uniform(1.0, 3.0)  # Quick online checkout
        yield self.env.timeout(checkout_time)
        
        total_amount = sum([item['price'] * item['quantity'] for item in basket])
        self.metrics.record_checkout(customer_id, checkout_time, total_amount)
        
        # 4. PAYMENT
        warehouse_location = "WAREHOUSE-001"
        payment_success, order_id = self._process_payment(
            customer_id, basket, total_amount, "online", warehouse_location, cart_id
        )
        
        if not payment_success:
            return
        
        # 5. FULFILLMENT PROCESS
        yield from self._online_fulfillment_process(order_id, basket, warehouse_location)
        
        # Optionally model returns
        yield from self._handle_potential_return(order_id, basket)
    
    def _bopis_journey(self, customer_id: str, arrival_time: float):
        """BOPIS (Buy Online, Pick up In Store) journey"""
        
        session_id = str(uuid4())
        
        # Session start
        self._emit_interaction_event(
            customer_id, session_id, 'session_start',
            {'channel': 'bopis', 'intent': 'store_pickup'}
        )
        
        # 1. ONLINE BROWSING
        browsing_time = random.triangular(
            self.config.distributions.browsing_time_min,
            self.config.distributions.browsing_time_mode,
            self.config.distributions.browsing_time_max
        )
        yield self.env.timeout(browsing_time)
        
        # Select basket (try real cart first, fall back to synthetic)
        basket = self._generate_basket(customer_id)
        self.metrics.record_browsing_complete(customer_id, browsing_time, len(basket) if basket else 0)
        
        # 2. CART CREATION - Update operational state in Cosmos
        cart_id = str(uuid4())
        if basket:
            self._update_cart_state(cart_id, customer_id, 'bopis', basket, 'active')
            # Emit cart events
            for item in basket:
                self._emit_cart_event(cart_id, 'item_added', item['sku'], item['quantity'])
        
        # Check abandonment
        if random.random() < self.config.distributions.abandonment_rate_bopis or not basket:
            if basket:
                self._update_cart_state(cart_id, customer_id, 'bopis', basket, 'abandoned')
            self._emit_cart_event(cart_id, 'cart_abandoned')
            self.metrics.record_abandonment(customer_id, "bopis_cart_abandoned")
            return
        
        # 3. CHECKOUT & SELECT PICKUP STORE
        checkout_time = random.uniform(1.0, 3.0)
        yield self.env.timeout(checkout_time)
        
        pickup_store = random.choice([loc for loc in self.config.resources.locations if loc.startswith("STORE-")])
        total_amount = sum([item['price'] * item['quantity'] for item in basket])
        self.metrics.record_checkout(customer_id, checkout_time, total_amount)
        
        # 4. PAYMENT
        payment_success, order_id = self._process_payment(
            customer_id, basket, total_amount, "bopis", pickup_store, cart_id
        )
        
        if not payment_success:
            return
        
        # 5. STORE FULFILLMENT (prepare for pickup)
        yield from self._bopis_fulfillment_process(order_id, basket, pickup_store, customer_id)
        
        # Optionally model returns
        yield from self._handle_potential_return(order_id, basket)
    
    # ========== HELPER FUNCTIONS ==========
    
    def _try_fetch_real_cart(self, customer_id: str) -> Optional[List[Dict]]:
        """Try to fetch real cart for customer from CosmosDB (optional enhancement)"""
        try:
            # Skip if customer_id is synthetic (starts with CUST-)
            if customer_id.startswith('CUST-'):
                return None
            
            carts_container = self.persistence.cosmos.database.get_container_client('Carts')
            
            # Query for active cart for this customer
            query = f"SELECT * FROM c WHERE c.userId = '{customer_id}' AND c.status = 'active'"
            carts = list(carts_container.query_items(
                query=query,
                enable_cross_partition_query=True
            ))
            
            if carts and carts[0].get('items'):
                cart_items = carts[0]['items']
                
                # Convert cart items to basket format
                basket = []
                for item in cart_items:
                    sku = item.get('sku')
                    if sku in self.product_catalog:
                        product_id, price, category = self.product_catalog[sku]
                        basket.append({
                            'sku': sku,
                            'product_id': product_id,
                            'quantity': item.get('qty', 1),
                            'price': item.get('price', price),
                            'category': category
                        })
                
                if basket:
                    logger.debug(f"Using real cart for customer {customer_id}: {len(basket)} items")
                    return basket
            
        except Exception as e:
            logger.debug(f"Could not fetch cart for {customer_id}: {e}")
        
        return None
    
    def _generate_basket(self, customer_id: Optional[str] = None) -> Optional[List[Dict]]:
        """Fetch real cart data from CosmosDB - NO FALLBACK to synthetic baskets
        
        Returns:
            List of basket items if real cart found, None otherwise
        """
        if not self.product_catalog:
            logger.warning("No product catalog loaded")
            return None
        
        # DATA INTEGRITY: Only use real cart data from CosmosDB
        if not customer_id or not self.real_customer_ids:
            logger.warning("Cannot generate basket: No customer_id or real customers not loaded")
            return None
        
        real_basket = self._try_fetch_real_cart(customer_id)
        
        if not real_basket:
            # No fallback - customer has no cart in CosmosDB
            logger.debug(f"No active cart found for customer {customer_id[:8]}... - skipping journey")
            return None
        
        return real_basket
    
    def _process_payment(self, customer_id: str, basket: List[Dict], 
                        total_amount: float, channel: str, location: str,
                        cart_id: Optional[str] = None):
        """
        Enhanced payment processing with proper write sequence
        
        Write Sequence:
        1. Validate pricing (read Products)
        2. Check/apply loyalty (read/write LoyaltyAccount)
        3. Reserve/decrement inventory (write Inventory)
        4. Create order header (write Orders with payment_status='pending')
        5. Create order lines (write OrderItems)
        6. Authorize/capture payment (write Payments)
        7. Update Orders.payment_status + fulfillment_status
        
        Returns:
            (success: bool, order_id: Optional[int])
        """
        # 1. Validate pricing from Products table (already in basket from catalog)
        
        # 2. Check loyalty and apply discount (placeholder - would read from LoyaltyAccount table)
        loyalty_discount = 0.0
        loyalty_points_earned = int(float(total_amount))  # 1 point per dollar
        
        final_amount = float(total_amount) - loyalty_discount
        
        # Simulate payment failure probability
        if random.random() < self.config.distributions.payment_failure_rate:
            self.metrics.record_payment_failure(customer_id)
            self._emit_order_event(None, 'payment_failed', {'reason': 'card_declined', 'customer_id': customer_id})
            logger.debug(f"[{self.env.now:.2f}] Payment failed for {customer_id}")
            return False, None
        
        # 3. Reserve/decrement inventory
        all_available = True
        for item in basket:
            available = self.resources.inventory.reserve_inventory(
                item['sku'], location, item['quantity']
            )
            if not available:
                all_available = False
                self.metrics.record_stockout(
                    item['sku'], location, item['quantity'],
                    self.resources.inventory.get_inventory(item['sku'], location).available
                    if self.resources.inventory.get_inventory(item['sku'], location) else 0
                )
        
        if not all_available:
            # Cancel reservations
            for item in basket:
                self.resources.inventory.cancel_reservation(item['sku'], location, item['quantity'])
            
            self.metrics.record_abandonment(customer_id, "stockout")
            logger.debug(f"[{self.env.now:.2f}] Stockout prevented purchase for {customer_id}")
            return False, None
        
        # 4. Create order header with payment_status='pending'
        payment_method = random.choice(['credit_card', 'debit_card', 'paypal'])
        order_data = {
            'customer_id': customer_id,
            'order_date': datetime.now(),
            'total_amount': final_amount,
            'status': 'pending',
            'channel': channel,
            'payment_status': 'pending',  # NEW: Track payment separately
            'fulfillment_status': 'pending',
            'workflow_source': 'omnichannel_purchase',
            'shipping_address': f"Address for {customer_id}" if channel != 'in_store' else None,
            'payment_method': payment_method
        }
        
        # 5. Create order items (with SKU for joins)
        order_items = [
            {
                'product_id': item['product_id'],
                'sku': item['sku'],  # NEW: Include SKU for joins
                'quantity': item['quantity'],
                'unit_price': item['price'],
                'subtotal': item['price'] * item['quantity']
            }
            for item in basket
        ]
        
        order_id = self.persistence.write_complete_order(order_data, order_items, cart_id)
        
        if not order_id:
            return False, None
        
        # 6. Authorize/capture payment
        auth_code = f"AUTH-{random.randint(100000, 999999)}"
        payment_data = {
            'order_id': order_id,
            'amount': final_amount,
            'payment_method': payment_method,
            'status': 'authorized',  # or 'captured' if immediate
            'auth_code': auth_code
        }
        self.persistence.postgres.write_payment(payment_data)
        
        # 7. Update Orders.payment_status
        self.persistence.postgres.update_order_payment_status(order_id, 'authorized')
        
        # Update loyalty points (placeholder - would write to LoyaltyAccount table)
        # self.persistence.postgres.update_loyalty_points(customer_id, loyalty_points_earned)
        
        # Fulfill inventory reservations
        for item in basket:
            self.resources.inventory.fulfill_inventory(item['sku'], location, item['quantity'])
        
        # Emit Event Hub events
        self._emit_order_event(order_id, 'order_placed', {
            'channel': channel, 
            'amount': final_amount,
            'customer_id': customer_id
        })
        self._emit_order_event(order_id, 'payment_authorized', {
            'method': payment_method,
            'auth_code': auth_code
        })
        
        # Update cart state to checked_out (if cart exists)
        if cart_id:
            self._update_cart_state(cart_id, customer_id, channel, basket, 'checked_out')
            self._emit_cart_event(cart_id, 'cart_checked_out')
        
        self.metrics.record_purchase_complete(customer_id, order_id, self.env.now)
        self.metrics.record_order_created(order_id, channel, self.env.now)
        
        logger.debug(f"[{self.env.now:.2f}] Order {order_id} created for {customer_id}")
        return True, order_id
    
    def _online_fulfillment_process(self, order_id: int, basket: List[Dict], location: str):
        """Enhanced online order fulfillment with proper event and state management"""
        self.metrics.record_fulfillment_start(order_id, self.env.now)
        
        # Update initial fulfillment state in Cosmos
        self._update_fulfillment_state(order_id, 'pending', location)
        
        # 1. PICKING
        with self.resources.warehouse_pickers.request() as req:
            yield req
            
            # Emit picking started event
            self._emit_fulfillment_event(order_id, 'picking_started', location)
            self._update_fulfillment_state(order_id, 'picking', location)
            
            picking_time = random.triangular(5, 10, 20)  # minutes
            yield self.env.timeout(picking_time)
            
            # Emit picked event
            self._emit_fulfillment_event(order_id, 'picked', location, 
                                         {'items_picked': len(basket)})
            self._update_fulfillment_state(order_id, 'picked', location)
        
        # 2. PACKING
        with self.resources.warehouse_packers.request() as req:
            yield req
            
            self._emit_fulfillment_event(order_id, 'packing_started', location)
            self._update_fulfillment_state(order_id, 'packing', location)
            
            packing_time = random.triangular(
                self.config.distributions.service_time_packing_min,
                self.config.distributions.service_time_packing_mode,
                self.config.distributions.service_time_packing_max
            )
            yield self.env.timeout(packing_time)
            
            tracking_number = f"TRACK-{random.randint(100000000, 999999999)}"
            self._emit_fulfillment_event(order_id, 'packed', location, 
                                         {'tracking': tracking_number})
            self._update_fulfillment_state(order_id, 'packed', location, tracking_number)
        
        # 3. SHIPPING
        carrier = random.choice(['UPS', 'FedEx', 'USPS', 'DHL'])
        self._emit_fulfillment_event(order_id, 'shipped', location, 
                                     {'carrier': carrier, 'tracking': tracking_number})
        self._update_fulfillment_state(order_id, 'shipped', location, tracking_number)
        
        # Update Postgres order status
        self.persistence.postgres.update_order_fulfillment_status(order_id, 'shipped')
        
        # 4. SHIPPING DELAY
        delivery_days = random.uniform(
            self.config.distributions.fulfillment_delay_min,
            self.config.distributions.fulfillment_delay_max
        )
        delivery_time_minutes = delivery_days * 24 * 60
        yield self.env.timeout(delivery_time_minutes)
        
        # 5. DELIVERY - Mark as COMPLETED
        self._emit_fulfillment_event(order_id, 'delivered', location, 
                                     {'delivery_time': datetime.now().isoformat(), 'carrier': carrier})
        self._update_fulfillment_state(order_id, 'delivered', location, tracking_number)
        
        # Final Postgres update - Set to COMPLETED (critical for analytics)
        self.persistence.postgres.update_order_status(order_id, 'COMPLETED', 'COMPLETED')
        self._emit_order_event(order_id, 'order_completed', {
            'channel': 'online',
            'completion_time': datetime.now().isoformat(),
            'carrier': carrier
        })
        
        # Check SLA
        sla_deadline = self.env.now  # Would be order_time + SLA in real scenario
        self.metrics.record_fulfillment_complete(order_id, self.env.now, sla_deadline)
        
        logger.info(f"Order {order_id} COMPLETED (online delivery)")
    
    def _bopis_fulfillment_process(self, order_id: int, basket: List[Dict], 
                                   store_location: str, customer_id: str):
        """Enhanced BOPIS fulfillment with proper event and state management"""
        self.metrics.record_fulfillment_start(order_id, self.env.now)
        
        # Update initial fulfillment state
        self._update_fulfillment_state(order_id, 'pending', store_location)
        
        # Store staff prepares order
        store_staff = self.resources.get_store_staff_resource(store_location)
        if not store_staff:
            logger.warning(f"No store staff at {store_location}")
            self._emit_fulfillment_event(order_id, 'exception', store_location,
                                        {'reason': 'no_staff_available'})
            self._update_fulfillment_state(order_id, 'exception', store_location)
            return
        
        with store_staff.request() as req:
            yield req
            
            # Emit preparation started
            self._emit_fulfillment_event(order_id, 'preparation_started', store_location)
            self._update_fulfillment_state(order_id, 'preparing', store_location)
            
            prep_time = random.triangular(
                self.config.distributions.bopis_prep_time_min,
                self.config.distributions.bopis_prep_time_mode,
                self.config.distributions.bopis_prep_time_max
            )
            yield self.env.timeout(prep_time)
        
        # Order ready for pickup
        self._emit_fulfillment_event(order_id, 'ready_for_pickup', store_location,
                                    {'prep_time_minutes': prep_time})
        self._update_fulfillment_state(order_id, 'ready_for_pickup', store_location)
        
        # Update Postgres
        self.persistence.postgres.update_order_status(order_id, "ready_for_pickup", "ready_for_pickup")
        
        # Check prep SLA (e.g., 1 hour)
        sla_deadline = self.env.now
        self.metrics.record_fulfillment_complete(order_id, self.env.now, sla_deadline)
        
        # Customer picks up (delay before pickup)
        pickup_delay = random.uniform(30, 240)  # 30 min to 4 hours
        yield self.env.timeout(pickup_delay)
        
        # Customer pickup event - Mark as COMPLETED
        self._emit_fulfillment_event(order_id, 'picked_up', store_location,
                                    {'customer_id': customer_id, 'pickup_time': datetime.now().isoformat()})
        self._update_fulfillment_state(order_id, 'picked_up', store_location)
        
        # Final Postgres update - Set to COMPLETED (critical for analytics)
        self.persistence.postgres.update_order_status(order_id, "COMPLETED", "COMPLETED")
        self._emit_order_event(order_id, 'order_completed', {
            'channel': 'bopis',
            'customer_id': customer_id,
            'completion_time': datetime.now().isoformat()
        })
        
        logger.info(f"Order {order_id} COMPLETED by {customer_id} (BOPIS pickup)")
    
    def _handle_potential_return(self, order_id: int, basket: List[Dict]):
        """Handle potential product returns with proper event emission"""
        # Determine return probability based on category
        will_return = False
        for item in basket:
            category = item['category']
            return_rate = self.config.distributions.return_rates.get(category, 0.10)
            if random.random() < return_rate:
                will_return = True
                break
        
        if not will_return:
            return
        
        # Delay until return
        return_delay_days = random.uniform(
            self.config.distributions.return_window_min,
            self.config.distributions.return_window_max
        )
        return_delay_minutes = return_delay_days * 24 * 60
        yield self.env.timeout(return_delay_minutes)
        
        # Process return
        location = self.config.resources.locations[0]  # Return to warehouse
        
        # Emit return event
        self._emit_order_event(order_id, 'return_initiated', {'location': location})
        
        self.metrics.record_return(order_id)
        self.persistence.postgres.update_order_status(order_id, "returned", "returned")
        
        self._emit_order_event(order_id, 'returned', {'return_completed': datetime.now().isoformat()})
        
        # Restock inventory
        for item in basket:
            self.resources.inventory.restock_inventory(item['sku'], location, item['quantity'])
        
        logger.debug(f"[{self.env.now:.2f}] Order {order_id} returned")
