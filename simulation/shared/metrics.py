"""
Metrics collection for simulation workflows.

Tracks KPIs and performance metrics including:
- Conversion rates
- Queue wait times
- Stockouts
- On-time delivery
- Resource utilization
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import statistics


logger = logging.getLogger(__name__)


@dataclass
class CustomerJourneyMetrics:
    """Metrics for individual customer journey"""
    customer_id: str
    channel: str
    arrival_time: float
    browsing_duration: float = 0.0
    queue_wait_time: float = 0.0
    checkout_time: float = 0.0
    total_time: float = 0.0
    basket_size: int = 0
    total_amount: float = 0.0
    abandoned: bool = False
    abandonment_reason: Optional[str] = None
    payment_failed: bool = False
    completed: bool = False
    order_id: Optional[int] = None


@dataclass
class OrderMetrics:
    """Metrics for individual order"""
    order_id: int
    channel: str
    order_time: float
    fulfillment_start_time: Optional[float] = None
    fulfillment_complete_time: Optional[float] = None
    delivery_time: Optional[float] = None
    fulfillment_duration: float = 0.0
    delivery_duration: float = 0.0
    on_time: Optional[bool] = None
    returned: bool = False


@dataclass
class WorkflowMetrics:
    """Aggregated metrics for a workflow"""
    workflow_name: str
    simulation_start: datetime = field(default_factory=datetime.now)
    simulation_end: Optional[datetime] = None
    
    # Customer journey metrics
    total_customers: int = 0
    customers_by_channel: Dict[str, int] = field(default_factory=dict)
    completed_purchases: int = 0
    abandoned_carts: int = 0
    payment_failures: int = 0
    
    # Journey timings
    avg_browsing_time: float = 0.0
    avg_queue_wait_time: float = 0.0
    avg_checkout_time: float = 0.0
    max_queue_wait_time: float = 0.0
    
    # Order metrics
    total_orders: int = 0
    orders_by_channel: Dict[str, int] = field(default_factory=dict)
    total_revenue: float = 0.0
    avg_basket_size: float = 0.0
    avg_order_value: float = 0.0
    
    # Fulfillment metrics
    avg_fulfillment_time: float = 0.0
    on_time_orders: int = 0
    late_orders: int = 0
    on_time_percentage: float = 0.0
    
    # Inventory metrics
    total_stockouts: int = 0
    lost_sales: int = 0
    
    # Return metrics
    total_returns: int = 0
    return_rate: float = 0.0
    
    # Conversion metrics
    conversion_rate: float = 0.0  # completed / total_customers


class MetricsCollector:
    """Collects and aggregates simulation metrics"""
    
    def __init__(self, workflow_name: str = "default"):
        self.workflow_name = workflow_name
        self.customer_journeys: List[CustomerJourneyMetrics] = []
        self.orders: List[OrderMetrics] = []
        self.stockout_events: List[Dict] = []
        self.custom_metrics: Dict[str, float] = {}  # Generic metrics storage
        self.simulation_start_time = datetime.now()
        
        logger.info(f"Metrics collector initialized for workflow: {workflow_name}")
    
    def record_metric(self, metric_name: str, value: float = 1.0):
        """
        Record a generic metric (increments by value if exists, otherwise sets it)
        
        Args:
            metric_name: Name of the metric
            value: Value to add (default 1.0 for counting)
        """
        if metric_name in self.custom_metrics:
            self.custom_metrics[metric_name] += value
        else:
            self.custom_metrics[metric_name] = value
        logger.debug(f"Metric {metric_name}: {self.custom_metrics[metric_name]}")
    
    def record_customer_arrival(self, customer_id: str, channel: str, arrival_time: float):
        """Record customer arrival"""
        journey = CustomerJourneyMetrics(
            customer_id=customer_id,
            channel=channel,
            arrival_time=arrival_time
        )
        self.customer_journeys.append(journey)
        logger.debug(f"Customer {customer_id} arrived via {channel}")
    
    def record_browsing_complete(self, customer_id: str, duration: float, basket_size: int):
        """Record browsing completion"""
        journey = self._get_journey(customer_id)
        if journey:
            journey.browsing_duration = duration
            journey.basket_size = basket_size
    
    def record_queue_wait(self, customer_id: str, wait_time: float):
        """Record queue wait time"""
        journey = self._get_journey(customer_id)
        if journey:
            journey.queue_wait_time = wait_time
    
    def record_checkout(self, customer_id: str, checkout_time: float, total_amount: float):
        """Record checkout completion"""
        journey = self._get_journey(customer_id)
        if journey:
            journey.checkout_time = checkout_time
            journey.total_amount = total_amount
    
    def record_abandonment(self, customer_id: str, reason: str = "unknown"):
        """Record cart abandonment"""
        journey = self._get_journey(customer_id)
        if journey:
            journey.abandoned = True
            journey.abandonment_reason = reason
            logger.debug(f"Customer {customer_id} abandoned cart: {reason}")
    
    def record_payment_failure(self, customer_id: str):
        """Record payment failure"""
        journey = self._get_journey(customer_id)
        if journey:
            journey.payment_failed = True
            logger.debug(f"Payment failed for customer {customer_id}")
    
    def record_purchase_complete(self, customer_id: str, order_id: int, sim_time: float):
        """Record completed purchase"""
        journey = self._get_journey(customer_id)
        if journey:
            journey.completed = True
            journey.order_id = order_id
            journey.total_time = sim_time - journey.arrival_time
            logger.debug(f"Customer {customer_id} completed purchase: order {order_id}")
    
    def record_order_created(self, order_id: int, channel: str, order_time: float):
        """Record new order"""
        order = OrderMetrics(
            order_id=order_id,
            channel=channel,
            order_time=order_time
        )
        self.orders.append(order)
        logger.debug(f"Order {order_id} created via {channel}")
    
    def record_fulfillment_start(self, order_id: int, start_time: float):
        """Record fulfillment start"""
        order = self._get_order(order_id)
        if order:
            order.fulfillment_start_time = start_time
    
    def record_fulfillment_complete(self, order_id: int, complete_time: float, sla_deadline: float):
        """Record fulfillment completion"""
        order = self._get_order(order_id)
        if order:
            order.fulfillment_complete_time = complete_time
            if order.fulfillment_start_time:
                order.fulfillment_duration = complete_time - order.fulfillment_start_time
            order.on_time = complete_time <= sla_deadline
            logger.debug(f"Order {order_id} fulfilled ({'on-time' if order.on_time else 'late'})")
    
    def record_delivery_complete(self, order_id: int, delivery_time: float):
        """Record delivery completion"""
        order = self._get_order(order_id)
        if order:
            order.delivery_time = delivery_time
            if order.fulfillment_complete_time:
                order.delivery_duration = delivery_time - order.fulfillment_complete_time
    
    def record_return(self, order_id: int):
        """Record order return"""
        order = self._get_order(order_id)
        if order:
            order.returned = True
            logger.debug(f"Order {order_id} returned")
    
    def record_stockout(self, sku: str, location: str, requested: int, available: int):
        """Record stockout event"""
        event = {
            'sku': sku,
            'location': location,
            'requested': requested,
            'available': available,
            'timestamp': datetime.now().isoformat()
        }
        self.stockout_events.append(event)
        logger.debug(f"Stockout: {sku} at {location}")
    
    def _get_journey(self, customer_id: str) -> Optional[CustomerJourneyMetrics]:
        """Get customer journey by ID"""
        for journey in self.customer_journeys:
            if journey.customer_id == customer_id:
                return journey
        return None
    
    def _get_order(self, order_id: int) -> Optional[OrderMetrics]:
        """Get order by ID"""
        for order in self.orders:
            if order.order_id == order_id:
                return order
        return None
    
    def calculate_metrics(self) -> WorkflowMetrics:
        """Calculate aggregated metrics"""
        metrics = WorkflowMetrics(
            workflow_name=self.workflow_name,
            simulation_start=self.simulation_start_time,
            simulation_end=datetime.now()
        )
        
        # Customer journey aggregations
        metrics.total_customers = len(self.customer_journeys)
        
        if metrics.total_customers > 0:
            # Channel breakdown
            for journey in self.customer_journeys:
                metrics.customers_by_channel[journey.channel] = \
                    metrics.customers_by_channel.get(journey.channel, 0) + 1
            
            # Outcomes
            completed = [j for j in self.customer_journeys if j.completed]
            abandoned = [j for j in self.customer_journeys if j.abandoned]
            failed = [j for j in self.customer_journeys if j.payment_failed]
            
            metrics.completed_purchases = len(completed)
            metrics.abandoned_carts = len(abandoned)
            metrics.payment_failures = len(failed)
            
            # Timings
            if completed:
                browsing_times = [j.browsing_duration for j in completed]
                metrics.avg_browsing_time = statistics.mean(browsing_times) if browsing_times else 0.0
                
                queue_waits = [j.queue_wait_time for j in completed if j.queue_wait_time > 0]
                metrics.avg_queue_wait_time = statistics.mean(queue_waits) if queue_waits else 0.0
                
                checkout_times = [j.checkout_time for j in completed]
                metrics.avg_checkout_time = statistics.mean(checkout_times) if checkout_times else 0.0
                
                all_waits = [j.queue_wait_time for j in self.customer_journeys if j.queue_wait_time > 0]
                if all_waits:
                    metrics.max_queue_wait_time = max(all_waits)
            
            # Order metrics
            if completed:
                basket_sizes = [j.basket_size for j in completed if j.basket_size > 0]
                metrics.avg_basket_size = statistics.mean(basket_sizes) if basket_sizes else 0.0
                metrics.total_revenue = sum([j.total_amount for j in completed])
                metrics.avg_order_value = metrics.total_revenue / len(completed) if completed else 0.0
            
            # Conversion rate
            metrics.conversion_rate = (metrics.completed_purchases / metrics.total_customers) * 100
        
        # Order aggregations
        metrics.total_orders = len(self.orders)
        
        if metrics.total_orders > 0:
            # Orders by channel
            for order in self.orders:
                metrics.orders_by_channel[order.channel] = \
                    metrics.orders_by_channel.get(order.channel, 0) + 1
            
            # Fulfillment metrics
            fulfilled = [o for o in self.orders if o.fulfillment_complete_time is not None]
            if fulfilled:
                metrics.avg_fulfillment_time = statistics.mean([o.fulfillment_duration for o in fulfilled])
                
                on_time = [o for o in fulfilled if o.on_time is True]
                late = [o for o in fulfilled if o.on_time is False]
                
                metrics.on_time_orders = len(on_time)
                metrics.late_orders = len(late)
                metrics.on_time_percentage = (len(on_time) / len(fulfilled)) * 100 if fulfilled else 0.0
            
            # Returns
            returns = [o for o in self.orders if o.returned]
            metrics.total_returns = len(returns)
            metrics.return_rate = (len(returns) / metrics.total_orders) * 100
        
        # Inventory metrics
        metrics.total_stockouts = len(self.stockout_events)
        metrics.lost_sales = sum([e['requested'] - e['available'] for e in self.stockout_events])
        
        return metrics
    
    def print_summary(self):
        """Print metrics summary to console"""
        metrics = self.calculate_metrics()
        
        print("\n" + "=" * 80)
        print(f"SIMULATION METRICS SUMMARY: {metrics.workflow_name}")
        print("=" * 80)
        
        print(f"\n📊 CUSTOMER JOURNEY METRICS")
        print(f"  Total Customers: {metrics.total_customers}")
        print(f"  Completed Purchases: {metrics.completed_purchases}")
        print(f"  Abandoned Carts: {metrics.abandoned_carts}")
        print(f"  Payment Failures: {metrics.payment_failures}")
        print(f"  Conversion Rate: {metrics.conversion_rate:.2f}%")
        
        if metrics.customers_by_channel:
            print(f"\n  Customers by Channel:")
            for channel, count in metrics.customers_by_channel.items():
                print(f"    {channel}: {count}")
        
        print(f"\n⏱️  TIMING METRICS")
        print(f"  Avg Browsing Time: {metrics.avg_browsing_time:.2f} min")
        print(f"  Avg Queue Wait: {metrics.avg_queue_wait_time:.2f} min")
        print(f"  Max Queue Wait: {metrics.max_queue_wait_time:.2f} min")
        print(f"  Avg Checkout Time: {metrics.avg_checkout_time:.2f} min")
        
        print(f"\n💰 ORDER METRICS")
        print(f"  Total Orders: {metrics.total_orders}")
        print(f"  Total Revenue: ${metrics.total_revenue:,.2f}")
        print(f"  Avg Basket Size: {metrics.avg_basket_size:.2f} items")
        print(f"  Avg Order Value: ${metrics.avg_order_value:.2f}")
        
        if metrics.orders_by_channel:
            print(f"\n  Orders by Channel:")
            for channel, count in metrics.orders_by_channel.items():
                print(f"    {channel}: {count}")
        
        print(f"\n📦 FULFILLMENT METRICS")
        print(f"  Avg Fulfillment Time: {metrics.avg_fulfillment_time:.2f} hours")
        print(f"  On-Time Orders: {metrics.on_time_orders}")
        print(f"  Late Orders: {metrics.late_orders}")
        print(f"  On-Time %: {metrics.on_time_percentage:.2f}%")
        
        print(f"\n📉 INVENTORY METRICS")
        print(f"  Total Stockouts: {metrics.total_stockouts}")
        print(f"  Lost Sales (units): {metrics.lost_sales}")
        
        print(f"\n↩️  RETURN METRICS")
        print(f"  Total Returns: {metrics.total_returns}")
        print(f"  Return Rate: {metrics.return_rate:.2f}%")
        
        print("\n" + "=" * 80 + "\n")
    
    def export_to_dict(self) -> Dict:
        """Export metrics as dictionary"""
        metrics = self.calculate_metrics()
        return {
            'workflow_name': metrics.workflow_name,
            'simulation_start': metrics.simulation_start.isoformat(),
            'simulation_end': metrics.simulation_end.isoformat() if metrics.simulation_end else None,
            'customer_metrics': {
                'total': metrics.total_customers,
                'completed': metrics.completed_purchases,
                'abandoned': metrics.abandoned_carts,
                'payment_failures': metrics.payment_failures,
                'conversion_rate': metrics.conversion_rate,
                'by_channel': metrics.customers_by_channel
            },
            'timing_metrics': {
                'avg_browsing': metrics.avg_browsing_time,
                'avg_queue_wait': metrics.avg_queue_wait_time,
                'max_queue_wait': metrics.max_queue_wait_time,
                'avg_checkout': metrics.avg_checkout_time
            },
            'order_metrics': {
                'total_orders': metrics.total_orders,
                'total_revenue': metrics.total_revenue,
                'avg_basket_size': metrics.avg_basket_size,
                'avg_order_value': metrics.avg_order_value,
                'by_channel': metrics.orders_by_channel
            },
            'fulfillment_metrics': {
                'avg_time': metrics.avg_fulfillment_time,
                'on_time': metrics.on_time_orders,
                'late': metrics.late_orders,
                'on_time_percentage': metrics.on_time_percentage
            },
            'inventory_metrics': {
                'stockouts': metrics.total_stockouts,
                'lost_sales': metrics.lost_sales
            },
            'return_metrics': {
                'total': metrics.total_returns,
                'rate': metrics.return_rate
            }
        }

    def persist_to_db(self, scenario_id: str, persistence) -> None:
        """
        Persist journey and order data for ML training.

        Writes to:
        - customer_journeys: Individual journey records
        - order_metrics: Order-level metrics
        - hourly_demand: Aggregated hourly demand data

        Args:
            scenario_id: Unique scenario identifier
            persistence: PersistenceManager with database connection
        """
        from uuid import uuid4

        conn = persistence.postgres._conn

        # 1. Persist customer_journeys
        for journey in self.customer_journeys:
            journey_id = str(uuid4())

            # Derive temporal features
            arrival_hour = int(journey.arrival_time / 60) % 24  # Convert minutes to hour of day
            day_of_week = int(journey.arrival_time / (60 * 24)) % 7  # Day of week

            conn.execute(
                """
                INSERT INTO customer_journeys
                    (journey_id, scenario_id, customer_id, channel, arrival_time,
                     arrival_hour, day_of_week, browsing_duration, basket_size,
                     queue_wait_time, checkout_time, total_amount, abandoned,
                     abandonment_reason, payment_failed, completed, order_id,
                     total_journey_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    journey_id,
                    scenario_id,
                    journey.customer_id,
                    journey.channel,
                    journey.arrival_time,
                    arrival_hour,
                    day_of_week,
                    journey.browsing_duration,
                    journey.basket_size,
                    journey.queue_wait_time,
                    journey.checkout_time,
                    journey.total_amount,
                    journey.abandoned,
                    journey.abandonment_reason,
                    journey.payment_failed,
                    journey.completed,
                    journey.order_id,
                    journey.total_time,
                ),
            )

        logger.info(f"Persisted {len(self.customer_journeys)} customer journeys for scenario {scenario_id}")

        # 2. Persist order_metrics
        for order in self.orders:
            order_hour = int(order.order_time / 60) % 24
            day_of_week = int(order.order_time / (60 * 24)) % 7

            conn.execute(
                """
                INSERT INTO order_metrics
                    (order_id, scenario_id, channel, order_time, order_hour,
                     day_of_week, fulfillment_start_time, fulfillment_complete_time,
                     fulfillment_duration, on_time, returned)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (order_id) DO UPDATE SET
                    scenario_id = excluded.scenario_id,
                    fulfillment_complete_time = excluded.fulfillment_complete_time,
                    fulfillment_duration = excluded.fulfillment_duration,
                    on_time = excluded.on_time,
                    returned = excluded.returned
                """,
                (
                    order.order_id,
                    scenario_id,
                    order.channel,
                    order.order_time,
                    order_hour,
                    day_of_week,
                    order.fulfillment_start_time,
                    order.fulfillment_complete_time,
                    order.fulfillment_duration,
                    order.on_time,
                    order.returned,
                ),
            )

        logger.info(f"Persisted {len(self.orders)} order metrics for scenario {scenario_id}")

        # 3. Aggregate and persist hourly_demand
        hourly_data = self._aggregate_hourly_demand(scenario_id)

        for hour_data in hourly_data:
            conn.execute(
                """
                INSERT INTO hourly_demand
                    (id, scenario_id, hour_of_simulation, hour_of_day, day_of_week,
                     channel, arrival_count, order_count, revenue, abandonment_count,
                     avg_basket_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                    scenario_id = excluded.scenario_id,
                    hour_of_simulation = excluded.hour_of_simulation,
                    hour_of_day = excluded.hour_of_day,
                    day_of_week = excluded.day_of_week,
                    channel = excluded.channel,
                    arrival_count = excluded.arrival_count,
                    order_count = excluded.order_count,
                    revenue = excluded.revenue,
                    abandonment_count = excluded.abandonment_count,
                    avg_basket_size = excluded.avg_basket_size
                """,
                (
                    hour_data['id'],
                    scenario_id,
                    hour_data['hour_of_simulation'],
                    hour_data['hour_of_day'],
                    hour_data['day_of_week'],
                    hour_data['channel'],
                    hour_data['arrival_count'],
                    hour_data['order_count'],
                    hour_data['revenue'],
                    hour_data['abandonment_count'],
                    hour_data['avg_basket_size'],
                ),
            )

        logger.info(f"Persisted {len(hourly_data)} hourly demand records for scenario {scenario_id}")

    def _aggregate_hourly_demand(self, scenario_id: str) -> List[Dict]:
        """
        Aggregate customer journeys into hourly demand metrics.

        Args:
            scenario_id: Scenario identifier for unique IDs

        Returns:
            List of hourly demand dictionaries
        """
        from uuid import uuid4
        from collections import defaultdict

        # Group by hour and channel
        hourly_buckets = defaultdict(lambda: {
            'arrivals': 0,
            'orders': 0,
            'revenue': 0.0,
            'abandonments': 0,
            'basket_sizes': [],
        })

        for journey in self.customer_journeys:
            # Calculate hour of simulation (in hours, not minutes)
            hour_of_simulation = int(journey.arrival_time / 60)
            hour_of_day = hour_of_simulation % 24
            day_of_week = int(journey.arrival_time / (60 * 24)) % 7

            key = (hour_of_simulation, hour_of_day, day_of_week, journey.channel)

            hourly_buckets[key]['arrivals'] += 1

            if journey.completed:
                hourly_buckets[key]['orders'] += 1
                hourly_buckets[key]['revenue'] += journey.total_amount
                if journey.basket_size > 0:
                    hourly_buckets[key]['basket_sizes'].append(journey.basket_size)

            if journey.abandoned:
                hourly_buckets[key]['abandonments'] += 1

        # Convert to list format
        result = []
        for (hour_sim, hour_day, dow, channel), data in hourly_buckets.items():
            avg_basket = (
                sum(data['basket_sizes']) / len(data['basket_sizes'])
                if data['basket_sizes'] else 0.0
            )

            result.append({
                'id': f"{scenario_id}_{hour_sim}_{channel}",
                'hour_of_simulation': float(hour_sim),
                'hour_of_day': hour_day,
                'day_of_week': dow,
                'channel': channel,
                'arrival_count': data['arrivals'],
                'order_count': data['orders'],
                'revenue': data['revenue'],
                'abandonment_count': data['abandonments'],
                'avg_basket_size': avg_basket,
            })

        return result
