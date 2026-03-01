"""
Customer Engagement & Personalization Workflow (Workflow 4).

Models the complete customer relationship management and engagement cycle:
- Customer lifecycle states (Active, Lapsed, Churned)
- RFM segmentation (Recency, Frequency, Monetary value)
- Personalized recommendations based on preferences
- Engagement campaigns (scheduled and triggered)
- Loyalty program with points accrual and redemption
- Customer service interactions and issue resolution
- Churn risk scoring and proactive retention

Includes:
- Customer state transitions with probabilistic behavior
- Dynamic segmentation and scoring
- Campaign effectiveness simulation
- Loyalty program mechanics
- Service recovery impact on retention
- Multi-channel engagement tracking

State persistence to Postgres, CosmosDB, and Event Hub.
"""

import simpy
import random
import logging
from typing import Dict, List, Optional, Tuple, Set
from datetime import datetime, timedelta
from uuid import uuid4
import numpy as np
from enum import Enum

from ..shared.config import SimulationConfig
from ..shared.resources import ResourceRegistry
from ..shared.persistence import PersistenceManager
from ..shared.metrics import MetricsCollector


logger = logging.getLogger(__name__)


class CustomerActivityState(Enum):
    """Customer activity states"""
    NEW = "new"
    ACTIVE = "active"
    LAPSED = "lapsed"
    CHURNED = "churned"


class CustomerValueTier(Enum):
    """Customer value tiers"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VIP = "vip"


class CustomerEngagementWorkflow:
    """Customer engagement and personalization simulation workflow"""
    
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
        
        # Customer registry: customer_id -> customer state
        self.customers: Dict[str, Dict] = {}
        
        # Campaign definitions
        self.campaigns: Dict[str, Dict] = {}
        
        # Product catalog for recommendations
        self.product_catalog: Dict[str, Tuple] = {}
        
        # Category preferences (from config)
        self.categories = config.engagement.product_categories
        
        # Real data from databases (loaded via load_real_data())
        self.real_customer_ids: List[str] = []
        self.real_products: List[Dict] = []
        self.product_names: List[str] = []  # For realistic search queries

        # In-memory event buffer for engagement_events ML table
        # Accumulated alongside CosmosDB writes; flushed by persist_ml_data()
        self._engagement_event_buffer: List[Dict] = []

        logger.info("Customer Engagement Workflow initialized")
    
    def load_real_data(self):
        """Load real customers and products from databases for data integrity"""
        logger.info("Loading real customers and products...")
        
        # Load customers from CosmosDB
        self.real_customer_ids = self._load_real_customers()
        
        # Load products from PostgreSQL
        self.real_products = self._load_real_products()
        self.product_names = [p['name'] for p in self.real_products]
        
        if not self.real_customer_ids:
            raise RuntimeError(
                "❌ No customers found in CosmosDB. Run 'make seed-all-with-history' first."
            )
        
        if not self.real_products:
            raise RuntimeError(
                "❌ No products found in PostgreSQL. Run 'make seed-all-with-history' first."
            )
        
        logger.info(f"✓ Loaded {len(self.real_customer_ids)} real customers from CosmosDB")
        logger.info(f"✓ Loaded {len(self.real_products)} real products from PostgreSQL")
    
    def _load_real_customers(self) -> List[str]:
        """Fetch real customer IDs from CosmosDB Customers container"""
        try:
            container = self.persistence.cosmos.database.get_container_client('Customers')
            query = "SELECT c.customerId FROM c"
            customers = list(container.query_items(
                query=query,
                enable_cross_partition_query=True
            ))
            return [c['customerId'] for c in customers]
        except Exception as e:
            logger.error(f"Failed to load customers from CosmosDB: {e}")
            return []
    
    def _load_real_products(self) -> List[Dict]:
        """Fetch real products (SKU, name, category, price) from PostgreSQL"""
        try:
            query = """
                SELECT sku, name, category, price
                FROM products
                ORDER BY sku
            """
            result = self.persistence.postgres.execute_query(query, fetch=True)
            
            if not result:
                logger.warning("No products found in PostgreSQL")
                return []
            
            return [
                {
                    'sku': row[0],
                    'name': row[1],
                    'category': row[2] or 'Chocolate',  # Default category
                    'price': float(row[3]) if row[3] else 0.0
                }
                for row in result
            ]
        except Exception as e:
            logger.error(f"Failed to load products from PostgreSQL: {e}")
            return []
    
    def register_customer(self, customer_id: str, email: str, name: str, 
                         join_date: Optional[datetime] = None):
        """Register a new customer in the system"""
        if join_date is None:
            join_date = datetime.now()
        
        # Generate random preferences
        ec = self.config.engagement
        preferred_categories = random.sample(self.categories, k=random.randint(ec.preferred_category_min, ec.preferred_category_max))
        marketing_opt_in = random.random() < ec.marketing_opt_in_probability
        
        customer_state = {
            'customer_id': customer_id,
            'email': email,
            'name': name,
            'join_date': join_date,
            'activity_state': CustomerActivityState.NEW,
            'value_tier': CustomerValueTier.LOW,
            'last_purchase_date': None,
            'total_spend': 0.0,
            'purchase_count': 0,
            'loyalty_points': 0,
            'churn_risk_score': 0.0,
            'preferred_categories': preferred_categories,
            'marketing_opt_in': marketing_opt_in,
            'unresponsive_count': 0,  # Track ignored campaigns
            'last_engagement_date': None
        }
        
        self.customers[customer_id] = customer_state

        # Write customer preferences (categories + opt-in) to Postgres
        if self.persistence.postgres:
            self.persistence.postgres.execute_query(
                """
                INSERT INTO customer_preferences
                    (customer_id, preferred_categories, marketing_opt_in,
                     created_at, updated_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (customer_id) DO UPDATE SET
                    preferred_categories = EXCLUDED.preferred_categories,
                    marketing_opt_in = EXCLUDED.marketing_opt_in,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (customer_id, ','.join(preferred_categories), marketing_opt_in)
            )

        logger.debug(f"Registered customer: {customer_id}")
    
    def load_purchase_history_from_db(self):
        """Load purchase history from PostgreSQL and calculate RFM aggregates
        
        Queries customer_purchase_history table (individual transactions with real SKUs)
        and aggregates per customer for RFM segmentation.
        """
        logger.info("📚 Loading purchase history from PostgreSQL...")
        
        try:
            # Aggregate purchase transactions per customer
            query = """
                SELECT 
                    customer_id,
                    MAX(purchase_date) as last_purchase_date,
                    COUNT(DISTINCT order_id) as purchase_count,
                    SUM(line_total) as total_spend,
                    AVG(line_total) as avg_line_value
                FROM customer_purchase_history
                GROUP BY customer_id
                ORDER BY customer_id
            """
            
            result = self.persistence.postgres.execute_query(query, fetch=True)
            
            if not result:
                logger.warning("No purchase history found in database")
                return
            
            loaded_count = 0
            now_days = self.env.now / 24.0  # Current simulation time in days
            
            for row in result:
                customer_id, last_purchase_date, purchase_count, total_spend, avg_line_value = row
                
                customer = self.customers.get(customer_id)
                if not customer:
                    continue  # Customer not registered in simulation
                
                # Convert DB datetime to simulation days
                if last_purchase_date:
                    days_ago = (datetime.now() - last_purchase_date).days
                    customer['last_purchase_date'] = now_days - days_ago
                else:
                    customer['last_purchase_date'] = None
                
                customer['purchase_count'] = purchase_count
                customer['total_spend'] = float(total_spend) if total_spend else 0.0
                
                # Calculate loyalty points
                ec = self.config.engagement
                customer['loyalty_points'] = int(customer['total_spend'] * ec.loyalty_points_ratio)

                # Determine value tier based on total spend
                if customer['total_spend'] >= ec.static_vip_threshold:
                    customer['value_tier'] = CustomerValueTier.VIP
                elif customer['total_spend'] >= ec.static_high_threshold:
                    customer['value_tier'] = CustomerValueTier.HIGH
                elif customer['total_spend'] >= ec.static_medium_threshold:
                    customer['value_tier'] = CustomerValueTier.MEDIUM
                else:
                    customer['value_tier'] = CustomerValueTier.LOW

                # Set activity state based on purchase recency
                if last_purchase_date:
                    if days_ago < ec.active_threshold_days:
                        customer['activity_state'] = CustomerActivityState.ACTIVE
                    elif days_ago < ec.lapsed_threshold_days:
                        customer['activity_state'] = CustomerActivityState.LAPSED
                    else:
                        customer['activity_state'] = CustomerActivityState.LAPSED
                
                loaded_count += 1
            
            # Count RFM segments
            segments = {}
            for cust in self.customers.values():
                seg = self._calculate_rfm_segment(cust)
                segments[seg] = segments.get(seg, 0) + 1
            
            logger.info(f"✓ Loaded purchase history for {loaded_count} customers. RFM segments: {dict(segments)}")
            
        except Exception as e:
            logger.error(f"Failed to load purchase history from PostgreSQL: {e}")
            logger.warning("Continuing without purchase history - all customers will be 'Needs Attention' segment")
    
    def persist_customer_stats(self):
        """Persist customer_stats for all customers with purchase history"""
        count = 0
        for customer_id, customer in self.customers.items():
            if customer.get('purchase_count', 0) > 0:
                self._update_customer_stats(customer_id)
                count += 1
        logger.info(f"Persisted customer_stats for {count} customers")

    def load_product_catalog(self, products: List[Tuple]):
        """Load product catalog for recommendations"""
        for product in products:
            product_id, sku, price, category = product
            self.product_catalog[sku] = (product_id, price, category)
        logger.info(f"Loaded {len(self.product_catalog)} products for recommendations")
    
    # ========== EVENT HUB EVENT EMISSION ==========
    
    def _emit_interaction_event(self, customer_id: str, event_type: str, 
                                campaign_id: Optional[str] = None, 
                                detail: Optional[Dict] = None):
        """Emit customer interaction event to Event Hub"""
        event = {
            'customer_id': customer_id,
            'eventType': event_type,  # email_sent, email_open, click, purchase, cart_abandon
            'campaign_id': campaign_id,
            'detail': detail or {},
            'timestamp': datetime.now().isoformat()
        }
        if self.persistence.eventhub:
            self.persistence.eventhub.send_event('interaction_events', event)
        logger.debug(f"Emitted interaction event: {event_type} for {customer_id}")
    
    # ========== COSMOS ENGAGEMENT EVENT LOG ==========
    
    def _log_engagement_event(self, customer_id: str, event_type: str,
                             campaign_id: Optional[str] = None,
                             channel: str = "email",
                             response: Optional[str] = None,
                             metadata: Optional[Dict] = None):
        """Log engagement event to CosmosDB (durable engagement history) and buffer for ML tables"""
        event_id = str(uuid4())
        event_doc = {
            'id': event_id,
            'customer_id': customer_id,
            'event_type': event_type,  # campaign_sent, email_open, click, purchase, service_ticket
            'campaign_id': campaign_id,
            'channel': channel,
            'response': response,  # opened, clicked, converted, ignored
            'metadata': metadata or {},
            'timestamp': datetime.now().isoformat(),
            'partitionKey': customer_id  # Partition by customer for efficient queries
        }

        if self.persistence.cosmos:
            self.persistence.cosmos.write_document('EngagementEvents', event_doc)

        logger.debug(f"Logged engagement event: {event_type} for {customer_id}")

        # Buffer for ML PostgreSQL table
        customer = self.customers.get(customer_id)
        if customer:
            now_days = self.env.now / 24.0
            if customer['last_purchase_date'] is not None:
                days_since_purchase = (self.env.now - customer['last_purchase_date']) / 24.0
            else:
                days_since_purchase = now_days

            self._engagement_event_buffer.append({
                'event_id': event_id,
                'customer_id': customer_id,
                'event_type': event_type,
                'event_time': self.env.now,
                'event_hour': int(self.env.now) % 24,
                'day_of_week': int(self.env.now / 24) % 7,
                'campaign_id': campaign_id,
                'channel': channel,
                'response': response,
                'value_tier': customer['value_tier'].value,
                'activity_state': customer['activity_state'].value,
                'days_since_last_purchase': days_since_purchase,
                'total_spend': customer['total_spend'],
                'purchase_count': customer['purchase_count'],
                'loyalty_points': customer['loyalty_points'],
                'churn_risk_score': customer['churn_risk_score'],
            })
    
    # ========== POSTGRES STATE UPDATES ==========
    
    def _update_customer_stats(self, customer_id: str):
        """Update customer statistics in Postgres"""
        customer = self.customers.get(customer_id)
        if not customer or not self.persistence.postgres:
            return
        
        self.persistence.postgres.execute_query(
            """
            INSERT INTO customer_stats 
                (customer_id, total_spend, last_purchase_date, purchase_count, 
                 avg_order_value, updated_at)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (customer_id) DO UPDATE SET
                total_spend = EXCLUDED.total_spend,
                last_purchase_date = EXCLUDED.last_purchase_date,
                purchase_count = EXCLUDED.purchase_count,
                avg_order_value = EXCLUDED.avg_order_value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (customer_id, customer['total_spend'], customer['last_purchase_date'],
             customer['purchase_count'], 
             customer['total_spend'] / customer['purchase_count'] if customer['purchase_count'] > 0 else 0)
        )
    
    def _update_customer_scores(self, customer_id: str):
        """Update customer segmentation and scores in Postgres"""
        customer = self.customers.get(customer_id)
        if not customer or not self.persistence.postgres:
            return
        
        self.persistence.postgres.execute_query(
            """
            INSERT INTO customer_scores
                (customer_id, segment, value_tier, churn_risk_score, 
                 activity_state, updated_at)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (customer_id) DO UPDATE SET
                segment = EXCLUDED.segment,
                value_tier = EXCLUDED.value_tier,
                churn_risk_score = EXCLUDED.churn_risk_score,
                activity_state = EXCLUDED.activity_state,
                updated_at = CURRENT_TIMESTAMP
            """,
            (customer_id, self._calculate_rfm_segment(customer),
             customer['value_tier'].value, customer['churn_risk_score'],
             customer['activity_state'].value)
        )
    
    def _update_loyalty_account(self, customer_id: str, points_change: int, reason: str):
        """Update loyalty points in Postgres"""
        customer = self.customers.get(customer_id)
        if not customer or not self.persistence.postgres:
            return
        
        # Update in-memory
        customer['loyalty_points'] += points_change
        
        # Update Postgres
        self.persistence.postgres.execute_query(
            """
            INSERT INTO loyalty_account 
                (customer_id, current_points, lifetime_points, tier)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (customer_id) DO UPDATE SET
                current_points = EXCLUDED.current_points + loyalty_account.current_points,
                lifetime_points = EXCLUDED.lifetime_points + loyalty_account.lifetime_points,
                tier = EXCLUDED.tier,
                updated_at = CURRENT_TIMESTAMP
            """,
            (customer_id, max(0, points_change), 
             max(0, points_change),
             customer['value_tier'].value)
        )
        
        # Log points transaction
        self.persistence.postgres.execute_query(
            """
            INSERT INTO points_transactions
                (transaction_id, customer_id, points_change, reason, transaction_date)
            VALUES (nextval('points_transactions_transaction_id_seq'), %s, %s, %s, CURRENT_TIMESTAMP)
            """,
            (customer_id, points_change, reason)
        )
        
        logger.debug(f"Updated loyalty points for {customer_id}: {points_change:+d} ({reason})")
    
    # ========== SEGMENTATION & SCORING ==========
    
    def _calculate_rfm_segment(self, customer: Dict) -> str:
        """Calculate RFM segment for customer"""
        now = datetime.now()
        
        # Recency (days since last purchase)
        if customer['last_purchase_date']:
            if isinstance(customer['last_purchase_date'], datetime):
                recency = (now - customer['last_purchase_date']).days
            else:
                recency = 999  # No purchase
        else:
            recency = 999
        
        # Frequency (purchase count)
        frequency = customer['purchase_count']
        
        # Monetary (total spend)
        monetary = customer['total_spend']
        
        ec = self.config.engagement
        # Champions: Recent, frequent, high spend
        if recency <= ec.rfm_champions_recency and frequency >= ec.rfm_champions_frequency and monetary >= ec.rfm_champions_monetary:
            return "Champions"
        # Loyal: Recent, some purchases, moderate spend
        elif recency <= ec.rfm_loyal_recency and frequency >= ec.rfm_loyal_frequency and monetary >= ec.rfm_loyal_monetary:
            return "Loyal"
        # Potential: Had any purchase in threshold OR any spend
        elif recency <= ec.rfm_potential_recency or monetary >= ec.rfm_potential_monetary:
            return "Potential"
        # At Risk: Very old or no purchases
        elif recency > 180:
            return "At Risk"
        else:
            return "Needs Attention"
    
    def _calculate_churn_risk(self, customer: Dict) -> float:
        """Calculate churn risk score (0-1)"""
        now = datetime.now()
        
        # Factors affecting churn risk
        risk_score = 0.0
        
        # Recency factor
        if customer['last_purchase_date']:
            if isinstance(customer['last_purchase_date'], datetime):
                days_since = (now - customer['last_purchase_date']).days
            else:
                days_since = 365
        else:
            days_since = 365
        
        ec = self.config.engagement
        if days_since > ec.churned_threshold_days:
            risk_score += ec.churn_risk_high_recency_increment
        elif days_since > ec.lapsed_threshold_days:
            risk_score += ec.churn_risk_medium_recency_increment

        # Engagement factor
        if customer['unresponsive_count'] > 3:
            risk_score += ec.churn_risk_unresponsive_increment

        # Value factor (high value customers less likely to churn)
        if customer['value_tier'] == CustomerValueTier.VIP:
            risk_score -= ec.churn_risk_vip_decrement
        elif customer['value_tier'] == CustomerValueTier.HIGH:
            risk_score -= ec.churn_risk_high_decrement
        
        return max(0.0, min(1.0, risk_score))
    
    # ========== CUSTOMER LIFECYCLE PROCESS ==========
    
    def customer_lifecycle_process(self, customer_id: str):
        """Simulate customer lifecycle with state transitions"""
        customer = self.customers.get(customer_id)
        if not customer:
            return
        
        while self.env.now < self.simulation_end_time:
            # Wait for next event (purchase or time-based check)
            ec = self.config.engagement
            wait_time = random.expovariate(1.0 / ec.lifecycle_wait_rate)
            yield self.env.timeout(wait_time)
            
            # Check if simulation should end
            if self.env.now >= self.simulation_end_time:
                break
            
            # Update activity state based on recency
            now_sim = self.env.now / 24.0  # Convert hours to days
            
            if customer['last_purchase_date']:
                days_since_purchase = now_sim - customer['last_purchase_date']
            else:
                days_since_purchase = now_sim
            
            # State transitions
            old_state = customer['activity_state']
            
            if days_since_purchase < ec.active_threshold_days:
                customer['activity_state'] = CustomerActivityState.ACTIVE
            elif days_since_purchase < ec.lapsed_threshold_days:
                customer['activity_state'] = CustomerActivityState.LAPSED
            elif days_since_purchase < ec.churned_threshold_days:
                # At risk - trigger retention campaign
                if random.random() < ec.retention_campaign_trigger_probability:
                    yield self.env.process(
                        self._trigger_retention_campaign(customer_id)
                    )
            else:
                # Churn if no response to campaigns
                customer['activity_state'] = CustomerActivityState.CHURNED
                self.metrics.record_metric('customers_churned', 1)
                self.metrics.record_metric('churn_events', 1)
                logger.info(f"[{self.env.now:.1f}h] 💔 Customer {customer_id[:8]}... churned (inactive for {days_since_purchase:.0f} days)")
                return  # Exit lifecycle
            
            # Update churn risk
            customer['churn_risk_score'] = self._calculate_churn_risk(customer)
            
            # Persist state changes
            if old_state != customer['activity_state']:
                self._update_customer_scores(customer_id)
                logger.info(f"[{self.env.now:.1f}h] 🔄 Customer {customer_id[:8]}... state: {old_state.value} → {customer['activity_state'].value}")
    
    # ========== PURCHASE INTEGRATION ==========
    
    def record_purchase(self, customer_id: str, amount: float, skus: List[str]):
        """Record a customer purchase (called from omnichannel workflow)"""
        customer = self.customers.get(customer_id)
        if not customer:
            return
        
        # Update customer state
        customer['last_purchase_date'] = self.env.now / 24.0  # Days
        customer['total_spend'] += amount
        customer['purchase_count'] += 1
        
        # Award loyalty points
        ec = self.config.engagement
        points_earned = int(amount * ec.points_per_dollar)
        self._update_loyalty_account(customer_id, points_earned, "purchase")
        self.metrics.record_metric('loyalty_points_earned', points_earned)

        # Update value tier based on total spend
        if customer['total_spend'] >= ec.dynamic_vip_threshold:
            customer['value_tier'] = CustomerValueTier.VIP
        elif customer['total_spend'] >= ec.dynamic_high_threshold:
            customer['value_tier'] = CustomerValueTier.HIGH
        elif customer['total_spend'] >= ec.dynamic_medium_threshold:
            customer['value_tier'] = CustomerValueTier.MEDIUM
        
        # Reset activity state to active
        customer['activity_state'] = CustomerActivityState.ACTIVE
        customer['unresponsive_count'] = 0  # Reset unresponsiveness
        
        # Update stats and scores
        self._update_customer_stats(customer_id)
        self._update_customer_scores(customer_id)
        
        # Log engagement event
        self._log_engagement_event(
            customer_id, 'purchase', None, 'transaction',
            'completed', {'amount': amount, 'items': len(skus)}
        )
        
        # Emit to Event Hub
        self._emit_interaction_event(
            customer_id, 'purchase', None,
            {'amount': amount, 'skus': skus}
        )
        
        # Record metrics
        self.metrics.record_metric('purchases_recorded', 1)
        self.metrics.record_metric('revenue_tracked', amount)
        
        logger.debug(f"Recorded purchase for {customer_id}: ${amount:.2f}, {points_earned} points")
    
    # ========== RECOMMENDATION ENGINE ==========
    
    def generate_recommendations(self, customer_id: str, count: int = 3) -> List[str]:
        """Generate personalized product recommendations"""
        customer = self.customers.get(customer_id)
        if not customer or not self.product_catalog:
            return []
        
        # Filter products by preferred categories
        preferred_prods = [
            sku for sku, (_, _, cat) in self.product_catalog.items()
            if cat in customer['preferred_categories']
        ]
        
        # If not enough, add random from other categories
        if len(preferred_prods) < count:
            other_prods = [
                sku for sku in self.product_catalog.keys()
                if sku not in preferred_prods
            ]
            preferred_prods.extend(random.sample(other_prods, 
                                                min(count - len(preferred_prods), len(other_prods))))
        
        # Select random subset
        recommendations = random.sample(preferred_prods, min(count, len(preferred_prods)))
        
        # Cache recommendations in Postgres
        if self.persistence.postgres and len(recommendations) >= 3:
            self.persistence.postgres.execute_query(
                """
                INSERT INTO recommendations_cache
                    (customer_id, sku_rank_1, sku_rank_2, sku_rank_3, updated_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (customer_id) DO UPDATE SET
                    sku_rank_1 = EXCLUDED.sku_rank_1,
                    sku_rank_2 = EXCLUDED.sku_rank_2,
                    sku_rank_3 = EXCLUDED.sku_rank_3,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (customer_id, recommendations[0], recommendations[1], recommendations[2])
            )
        
        self.metrics.record_metric('recommendations_generated', 1)
        
        return recommendations
    
    def populate_recommendations_cache(self):
        """Generate recommendations for all registered customers"""
        count = 0
        for customer_id in list(self.customers.keys()):
            recs = self.generate_recommendations(customer_id)
            if recs:
                count += 1
        logger.info(f"Generated recommendations for {count} customers")

    # ========== CAMPAIGN EXECUTION ==========
    
    def scheduled_campaign_process(self, campaign_id: str, segment: str, 
                                  interval_days: float = 7.0):
        """Run scheduled campaign (e.g., weekly newsletter)"""
        first_run = True  # Flag to execute immediately on first iteration
        
        while self.env.now < self.simulation_end_time:
            # Target customers in segment
            eligible_customers = [
                cid for cid, cust in self.customers.items()
                if cust['marketing_opt_in'] and 
                   self._calculate_rfm_segment(cust) == segment
            ]
            
            if not eligible_customers:
                # No customers in this segment - wait before checking again
                accelerated_interval = interval_days * 24 * self.config.engagement.acceleration_factor
                yield self.env.timeout(accelerated_interval)
                # Check if simulation should end
                if self.env.now >= self.simulation_end_time:
                    break
                continue
            
            logger.info(f"[{self.env.now:.1f}h] 📧 Campaign '{campaign_id}' sent to {len(eligible_customers)} {segment} customers")
            
            conversions = 0
            opens = 0
            clicks = 0
            for cust_id in eligible_customers:
                # Send campaign
                self._emit_interaction_event(cust_id, 'email_sent', campaign_id)
                self._log_engagement_event(cust_id, 'campaign_sent', campaign_id, 'email')
                self.metrics.record_metric('campaigns_sent', 1)
                
                # Simulate response
                customer = self.customers[cust_id]
                ec = self.config.engagement
                response_prob = ec.base_email_response_rate

                # Adjust by value tier
                if customer['value_tier'] == CustomerValueTier.VIP:
                    response_prob += ec.vip_response_boost
                elif customer['value_tier'] == CustomerValueTier.HIGH:
                    response_prob += ec.high_response_boost

                if random.random() < response_prob:
                    # Customer responds (clicks)
                    self._emit_interaction_event(cust_id, 'email_open', campaign_id)
                    self._emit_interaction_event(cust_id, 'click', campaign_id)
                    self._log_engagement_event(cust_id, 'email_open', campaign_id, 'email', 'clicked')
                    opens += 1
                    clicks += 1
                    self.metrics.record_metric('emails_opened', 1)
                    self.metrics.record_metric('clicks', 1)

                    # Some who click convert to purchase
                    if random.random() < ec.click_to_conversion_rate:
                        conversions += 1
                        customer['last_engagement_date'] = self.env.now
                        self.metrics.record_metric('campaign_conversions', 1)
                else:
                    # Ignored
                    customer['unresponsive_count'] += 1
                    self._log_engagement_event(cust_id, 'campaign_sent', campaign_id, 'email', 'ignored')
                    self.metrics.record_metric('emails_ignored', 1)
            
            self.metrics.record_metric(f'campaign_{campaign_id}_sent', len(eligible_customers))
            self.metrics.record_metric(f'campaign_{campaign_id}_conversions', conversions)
            
            logger.info(f"[{self.env.now:.1f}h] ✓ Campaign '{campaign_id}' complete: {opens} opens, {clicks} clicks, {conversions} conversions")
            
            # Wait for next campaign interval (accelerated for testing)
            accelerated_interval = interval_days * 24 * self.config.engagement.acceleration_factor
            yield self.env.timeout(accelerated_interval)
    
    def _trigger_retention_campaign(self, customer_id: str):
        """Trigger retention campaign for at-risk customer"""
        customer = self.customers.get(customer_id)
        if not customer or not customer['marketing_opt_in']:
            return
        
        campaign_id = f"retention_{int(self.env.now)}"
        
        logger.info(f"[{self.env.now:.1f}h] ⚠️  Triggering retention campaign for customer {customer_id[:8]}... (churn risk: {customer['churn_risk_score']:.2f})")
        
        # Send targeted offer
        self._emit_interaction_event(customer_id, 'email_sent', campaign_id, 
                                    {'type': 'retention', 'offer': '20% off'})
        self._log_engagement_event(customer_id, 'campaign_sent', campaign_id, 'email',
                                  metadata={'type': 'retention', 'churn_risk': customer['churn_risk_score']})
        self.metrics.record_metric('retention_campaigns_sent', 1)
        self.metrics.record_metric('churn_risk_alerts', 1)
        
        # Higher response rate for retention offers
        response_prob = self.config.engagement.retention_response_rate
        
        if random.random() < response_prob:
            # Customer responds
            self._emit_interaction_event(customer_id, 'click', campaign_id)
            self._log_engagement_event(customer_id, 'email_open', campaign_id, 'email', 'converted')
            
            # Reset engagement
            customer['last_engagement_date'] = self.env.now
            customer['unresponsive_count'] = 0
            
            self.metrics.record_metric('retention_campaigns_successful', 1)
            logger.info(f"[{self.env.now:.1f}h] ✓ Retention campaign successful for {customer_id[:8]}...")
        else:
            customer['unresponsive_count'] += 1
            self.metrics.record_metric('retention_campaigns_failed', 1)
        
        yield self.env.timeout(0)  # Yield control
    
    # ========== LOYALTY REDEMPTION ==========
    
    def loyalty_redemption_process(self, customer_id: str):
        """Simulate loyalty points redemption"""
        customer = self.customers.get(customer_id)
        if not customer:
            return
        
        while self.env.now < self.simulation_end_time:
            # Check periodically if eligible for redemption (accelerated for testing)
            # Check every 1-3 hours instead of 15-45 days
            yield self.env.timeout(random.uniform(1, 3))
            
            # Check if simulation should end
            if self.env.now >= self.simulation_end_time:
                break
            
            ec = self.config.engagement
            if customer['loyalty_points'] >= ec.redemption_threshold:
                # Redeem with some probability
                if random.random() < ec.redemption_probability:
                    points_to_redeem = min(ec.max_points_per_redemption, customer['loyalty_points'])
                    reward_value = int(points_to_redeem * ec.points_to_dollar_ratio)
                    
                    self._update_loyalty_account(customer_id, -points_to_redeem, "redemption")
                    
                    self._log_engagement_event(
                        customer_id, 'loyalty_redemption', None, 'loyalty',
                        'redeemed', {'points': points_to_redeem, 'value': reward_value}
                    )
                    
                    self.metrics.record_metric('loyalty_redemptions', 1)
                    self.metrics.record_metric('loyalty_points_redeemed', points_to_redeem)
                    
                    logger.info(f"[{self.env.now:.1f}h] 🎁 Customer {customer_id[:8]}... redeemed {points_to_redeem} points (${reward_value} reward)")
    
    # ========== SERVICE TICKET SIMULATION ==========
    
    def customer_service_process(self, customer_id: str):
        """Simulate customer service interactions"""
        customer = self.customers.get(customer_id)
        if not customer:
            return
        
        while self.env.now < self.simulation_end_time:
            # Random service issues
            ec = self.config.engagement
            yield self.env.timeout(random.expovariate(1.0 / ec.service_issue_interval_rate))

            # Check if simulation should end
            if self.env.now >= self.simulation_end_time:
                break

            if random.random() < ec.service_issue_probability:
                ticket_id = f"TICKET-{uuid4().hex[:8].upper()}"
                issue_type = random.choice(ec.service_issue_types)
                
                # Create support ticket in Postgres
                if self.persistence.postgres:
                    self.persistence.postgres.execute_query(
                        """
                        INSERT INTO support_tickets
                            (ticket_id, customer_id, issue_type, status, created_at)
                        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                        """,
                        (ticket_id, customer_id, issue_type, 'open')
                    )
                
                self._log_engagement_event(
                    customer_id, 'service_ticket', None, 'support',
                    'created', {'ticket_id': ticket_id, 'issue': issue_type}
                )
                self.metrics.record_metric('service_tickets_created', 1)
                logger.info(f"[{self.env.now:.1f}h] 🎫 Service ticket {ticket_id} created for {customer_id[:8]}... ({issue_type})")
                
                # Simulate resolution
                resolution_time = random.uniform(ec.resolution_time_min, ec.resolution_time_max)
                yield self.env.timeout(resolution_time)

                # Satisfaction rating
                satisfaction = random.randint(ec.satisfaction_min, ec.satisfaction_max)
                
                if self.persistence.postgres:
                    self.persistence.postgres.execute_query(
                        """
                        UPDATE support_tickets
                        SET status = %s, satisfaction_rating = %s, resolved_at = CURRENT_TIMESTAMP
                        WHERE ticket_id = %s
                        """,
                        ('resolved', satisfaction, ticket_id)
                    )
                
                # Impact on churn risk
                if satisfaction >= ec.good_service_threshold:
                    # Good service reduces churn risk
                    customer['churn_risk_score'] = max(0, customer['churn_risk_score'] - ec.churn_risk_reduction_good_service)
                    self.metrics.record_metric('service_tickets_satisfied', 1)
                else:
                    # Poor service increases churn risk
                    customer['churn_risk_score'] = min(1.0, customer['churn_risk_score'] + ec.churn_risk_increase_poor_service)
                    self.metrics.record_metric('service_tickets_unsatisfied', 1)
                
                self._update_customer_scores(customer_id)
                
                self.metrics.record_metric('service_tickets_resolved', 1)
                
                logger.info(f"[{self.env.now:.1f}h] ✓ Ticket {ticket_id} resolved (satisfaction: {satisfaction}/5)")
    
    # ========== SEGMENTATION UPDATE PROCESS ==========
    
    def segmentation_update_process(self, interval_days: float = 7.0):
        """Periodic segmentation and scoring update"""
        while self.env.now < self.simulation_end_time:
            yield self.env.timeout(interval_days * 24 * self.config.engagement.acceleration_factor)
            
            # Check if simulation should end
            if self.env.now >= self.simulation_end_time:
                break
            
            logger.info(f"[{self.env.now:.1f}h] 📊 Running segmentation update for {len(self.customers)} customers...")
            
            for customer_id, customer in self.customers.items():
                # Recalculate churn risk
                customer['churn_risk_score'] = self._calculate_churn_risk(customer)
                
                # Update scores in Postgres
                self._update_customer_scores(customer_id)
            
            self.metrics.record_metric('segmentation_updates', 1)
            
            logger.info(f"Segmentation update completed for {len(self.customers)} customers")
    
    # ========== WORKFLOW ORCHESTRATION ==========
    
    def start_customer_engagement(self, customer_id: str):
        """Start all engagement processes for a customer"""
        # Start lifecycle process
        self.env.process(self.customer_lifecycle_process(customer_id))
        
        # Start loyalty redemption process
        self.env.process(self.loyalty_redemption_process(customer_id))
        
        # Start service process
        self.env.process(self.customer_service_process(customer_id))
    
    def start_campaigns(self):
        """Start scheduled campaigns"""
        ec = self.config.engagement

        # Weekly newsletter to loyal customers
        self.env.process(self.scheduled_campaign_process("weekly_newsletter", "Loyal", ec.campaign_weekly_newsletter_interval))

        # Monthly promotion to potential customers
        self.env.process(self.scheduled_campaign_process("monthly_promo", "Potential", ec.campaign_monthly_promo_interval))

        # Bi-weekly to champions
        self.env.process(self.scheduled_campaign_process("vip_offers", "Champions", ec.campaign_vip_offers_interval))

        # Welcome/reactivation series for new/inactive customers
        self.env.process(self.scheduled_campaign_process("welcome_series", "Needs Attention", ec.campaign_welcome_series_interval))

        # All opted-in customers campaign (guaranteed to have targets)
        self.env.process(self.all_customers_campaign_process("all_customers_promo", ec.campaign_all_customers_interval))
    
    def all_customers_campaign_process(self, campaign_id: str, interval_days: float = 5.0):
        """Run campaign targeting ALL opted-in customers (guaranteed engagement)"""
        while self.env.now < self.simulation_end_time:
            # Target all customers who opted in to marketing
            eligible_customers = [
                cid for cid, cust in self.customers.items()
                if cust['marketing_opt_in']
            ]
            
            if not eligible_customers:
                yield self.env.timeout(interval_days * 24 * self.config.engagement.acceleration_factor)
                # Check if simulation should end
                if self.env.now >= self.simulation_end_time:
                    break
                continue
            
            logger.info(f"[{self.env.now:.1f}h] 📧 Campaign '{campaign_id}' sent to {len(eligible_customers)} opted-in customers")
            
            conversions = 0
            opens = 0
            clicks = 0
            for cust_id in eligible_customers:
                # Send campaign
                self._emit_interaction_event(cust_id, 'email_sent', campaign_id)
                self._log_engagement_event(cust_id, 'campaign_sent', campaign_id, 'email')
                self.metrics.record_metric('campaigns_sent', 1)
                
                # Simulate response
                customer = self.customers[cust_id]
                ec = self.config.engagement
                response_prob = ec.all_customers_base_response

                # Adjust by value tier
                if customer['value_tier'] == CustomerValueTier.VIP:
                    response_prob += ec.all_customers_vip_boost
                elif customer['value_tier'] == CustomerValueTier.HIGH:
                    response_prob += ec.all_customers_high_boost
                elif customer['value_tier'] == CustomerValueTier.MEDIUM:
                    response_prob += ec.all_customers_medium_boost

                if random.random() < response_prob:
                    # Customer responds (clicks)
                    self._emit_interaction_event(cust_id, 'email_open', campaign_id)
                    self._emit_interaction_event(cust_id, 'click', campaign_id)
                    self._log_engagement_event(cust_id, 'email_open', campaign_id, 'email', 'clicked')
                    opens += 1
                    clicks += 1
                    self.metrics.record_metric('emails_opened', 1)
                    self.metrics.record_metric('clicks', 1)

                    # Some who click convert to purchase
                    if random.random() < ec.all_customers_conversion_rate:
                        conversions += 1
                        customer['last_engagement_date'] = self.env.now
                        self.metrics.record_metric('campaign_conversions', 1)
                else:
                    # Ignored
                    customer['unresponsive_count'] += 1
                    self._log_engagement_event(cust_id, 'campaign_sent', campaign_id, 'email', 'ignored')
                    self.metrics.record_metric('emails_ignored', 1)
            
            self.metrics.record_metric(f'campaign_{campaign_id}_sent', len(eligible_customers))
            self.metrics.record_metric(f'campaign_{campaign_id}_conversions', conversions)
            
            logger.info(f"[{self.env.now:.1f}h] ✓ Campaign '{campaign_id}' complete: {opens} opens, {clicks} clicks, {conversions} conversions")
            
            # Wait for next campaign interval (accelerated)
            accelerated_interval = interval_days * 24 * self.config.engagement.acceleration_factor
            yield self.env.timeout(accelerated_interval)
    
    def start_segmentation_updates(self):
        """Start periodic segmentation updates"""
        self.env.process(self.segmentation_update_process(self.config.engagement.campaign_weekly_newsletter_interval))
    
    def print_engagement_summary(self):
        """Print engagement-specific metrics summary"""
        print("\n" + "="*80)
        print("ENGAGEMENT WORKFLOW SUMMARY")
        print("="*80)
        
        # Customer state distribution
        active_count = len([c for c in self.customers.values() if c['activity_state'] == CustomerActivityState.ACTIVE])
        lapsed_count = len([c for c in self.customers.values() if c['activity_state'] == CustomerActivityState.LAPSED])
        churned_count = len([c for c in self.customers.values() if c['activity_state'] == CustomerActivityState.CHURNED])
        new_count = len([c for c in self.customers.values() if c['activity_state'] == CustomerActivityState.NEW])
        
        print(f"\n👥 CUSTOMER STATES (Total: {len(self.customers)})")
        print(f"  Active: {active_count}")
        print(f"  Lapsed: {lapsed_count}")
        print(f"  New: {new_count}")
        print(f"  Churned: {churned_count}")
        
        # RFM Segment distribution (NEW)
        segments = {}
        for cust in self.customers.values():
            seg = self._calculate_rfm_segment(cust)
            segments[seg] = segments.get(seg, 0) + 1
        
        print(f"\n📊 RFM SEGMENTS")
        for seg_name in ["Champions", "Loyal", "Potential", "At Risk", "Needs Attention"]:
            count = segments.get(seg_name, 0)
            pct = (count / len(self.customers) * 100) if self.customers else 0
            print(f"  {seg_name}: {count} ({pct:.1f}%)")
        
        # Value tier distribution
        vip_count = len([c for c in self.customers.values() if c['value_tier'] == CustomerValueTier.VIP])
        high_count = len([c for c in self.customers.values() if c['value_tier'] == CustomerValueTier.HIGH])
        medium_count = len([c for c in self.customers.values() if c['value_tier'] == CustomerValueTier.MEDIUM])
        low_count = len([c for c in self.customers.values() if c['value_tier'] == CustomerValueTier.LOW])
        
        print(f"\n💎 VALUE TIERS")
        print(f"  VIP: {vip_count}")
        print(f"  High: {high_count}")
        print(f"  Medium: {medium_count}")
        print(f"  Low: {low_count}")
        
        # Campaign metrics
        campaigns_sent = self.metrics.custom_metrics.get('campaigns_sent', 0)
        emails_opened = self.metrics.custom_metrics.get('emails_opened', 0)
        clicks = self.metrics.custom_metrics.get('clicks', 0)
        emails_ignored = self.metrics.custom_metrics.get('emails_ignored', 0)
        open_rate = (emails_opened / campaigns_sent * 100) if campaigns_sent > 0 else 0
        click_rate = (clicks / campaigns_sent * 100) if campaigns_sent > 0 else 0
        
        print(f"\n📧 CAMPAIGN METRICS")
        print(f"  Campaigns Sent: {int(campaigns_sent)}")
        print(f"  Emails Opened: {int(emails_opened)}")
        print(f"  Clicks: {int(clicks)}")
        print(f"  Ignored: {int(emails_ignored)}")
        print(f"  Open Rate: {open_rate:.1f}%")
        print(f"  Click Rate: {click_rate:.1f}%")
        
        # Loyalty metrics
        points_earned = self.metrics.custom_metrics.get('loyalty_points_earned', 0)
        points_redeemed = self.metrics.custom_metrics.get('loyalty_points_redeemed', 0)
        redemptions = self.metrics.custom_metrics.get('loyalty_redemptions', 0)
        
        print(f"\n🎁 LOYALTY METRICS")
        print(f"  Points Earned: {int(points_earned):,}")
        print(f"  Points Redeemed: {int(points_redeemed):,}")
        print(f"  Redemptions: {int(redemptions)}")
        
        # Churn & retention
        churn_alerts = self.metrics.custom_metrics.get('churn_risk_alerts', 0)
        retention_sent = self.metrics.custom_metrics.get('retention_campaigns_sent', 0)
        retention_success = self.metrics.custom_metrics.get('retention_campaigns_successful', 0)
        churn_events = self.metrics.custom_metrics.get('churn_events', 0)
        retention_rate = (retention_success / retention_sent * 100) if retention_sent > 0 else 0
        
        print(f"\n⚠️  CHURN & RETENTION")
        print(f"  Churn Risk Alerts: {int(churn_alerts)}")
        print(f"  Retention Campaigns Sent: {int(retention_sent)}")
        print(f"  Retention Success: {int(retention_success)}")
        print(f"  Retention Success Rate: {retention_rate:.1f}%")
        print(f"  Customers Churned: {int(churn_events)}")
        
        # Service metrics
        tickets_created = self.metrics.custom_metrics.get('service_tickets_created', 0)
        tickets_resolved = self.metrics.custom_metrics.get('service_tickets_resolved', 0)
        satisfied = self.metrics.custom_metrics.get('service_tickets_satisfied', 0)
        unsatisfied = self.metrics.custom_metrics.get('service_tickets_unsatisfied', 0)
        satisfaction_rate = (satisfied / tickets_resolved * 100) if tickets_resolved > 0 else 0
        
        print(f"\n🎫 SERVICE METRICS")
        print(f"  Tickets Created: {int(tickets_created)}")
        print(f"  Tickets Resolved: {int(tickets_resolved)}")
        print(f"  Satisfied (4-5 stars): {int(satisfied)}")
        print(f"  Unsatisfied (1-3 stars): {int(unsatisfied)}")
        print(f"  Satisfaction Rate: {satisfaction_rate:.1f}%")
        
        # Top customers
        print(f"\n🏆 TOP 5 CUSTOMERS BY SPEND")
        top_customers = sorted(self.customers.values(), key=lambda c: c['total_spend'], reverse=True)[:5]
        for i, c in enumerate(top_customers, 1):
            print(f"  {i}. {c['name'][:25]:<25} ${c['total_spend']:>8,.2f} ({c['purchase_count']} purchases, {c['loyalty_points']} points)")
        
        print("=" * 80 + "\n")


# ========== ML DATA PERSISTENCE ==========

    def persist_ml_data(self, scenario_id: str) -> None:
        """
        Persist engagement data for ML training.

        Writes to:
        - customer_snapshots: For churn and CLV prediction models
        - campaign_interactions: For campaign response prediction model
        - engagement_events: For engagement pattern ML training

        Args:
            scenario_id: Unique scenario identifier
        """
        from uuid import uuid4

        conn = self.persistence.postgres._conn

        # 1. Persist customer snapshots
        snapshot_count = 0
        for customer_id, customer in self.customers.items():
            snapshot_id = f"{scenario_id}_{customer_id}"

            # Calculate days since metrics
            now_days = self.env.now / 24.0
            if customer['last_purchase_date']:
                days_since_purchase = now_days - customer['last_purchase_date']
            else:
                days_since_purchase = now_days

            # Days since join (from join_date)
            if isinstance(customer['join_date'], datetime):
                days_since_join = (datetime.now() - customer['join_date']).days
            else:
                days_since_join = now_days

            avg_order_value = (
                customer['total_spend'] / customer['purchase_count']
                if customer['purchase_count'] > 0 else 0.0
            )

            churned = customer['activity_state'] == CustomerActivityState.CHURNED

            conn.execute(
                """
                INSERT INTO customer_snapshots
                    (snapshot_id, scenario_id, customer_id, snapshot_time,
                     days_since_last_purchase, days_since_join, total_spend,
                     purchase_count, avg_order_value, loyalty_points,
                     unresponsive_count, value_tier, rfm_segment,
                     churn_risk_score, churned)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (snapshot_id) DO UPDATE SET
                    churn_risk_score = excluded.churn_risk_score,
                    churned = excluded.churned
                """,
                (
                    snapshot_id,
                    scenario_id,
                    customer_id,
                    self.env.now,
                    days_since_purchase,
                    days_since_join,
                    customer['total_spend'],
                    customer['purchase_count'],
                    avg_order_value,
                    customer['loyalty_points'],
                    customer['unresponsive_count'],
                    customer['value_tier'].value,
                    self._calculate_rfm_segment(customer),
                    customer['churn_risk_score'],
                    churned,
                ),
            )
            snapshot_count += 1

        logger.info(f"Persisted {snapshot_count} customer snapshots for scenario {scenario_id}")

        # 2. Persist campaign interactions (aggregated from metrics)
        # Generate synthetic campaign interaction records based on metrics
        interaction_count = 0

        campaigns_sent = int(self.metrics.custom_metrics.get('campaigns_sent', 0))
        emails_opened = int(self.metrics.custom_metrics.get('emails_opened', 0))
        clicks = int(self.metrics.custom_metrics.get('clicks', 0))
        conversions = int(self.metrics.custom_metrics.get('campaign_conversions', 0))

        # Create representative interactions for each customer
        for customer_id, customer in self.customers.items():
            if not customer['marketing_opt_in']:
                continue

            interaction_id = str(uuid4())

            # Determine response based on customer behavior
            was_unresponsive = customer['unresponsive_count'] > 0
            was_engaged = customer['last_engagement_date'] is not None

            if customer['last_engagement_date']:
                days_since_engagement = (self.env.now - customer['last_engagement_date']) / 24.0
            else:
                days_since_engagement = self.env.now / 24.0

            # Assign outcomes probabilistically based on tier
            base_open_rate = 0.2
            base_click_rate = 0.1
            base_convert_rate = 0.05

            if customer['value_tier'] == CustomerValueTier.VIP:
                base_open_rate, base_click_rate, base_convert_rate = 0.4, 0.25, 0.15
            elif customer['value_tier'] == CustomerValueTier.HIGH:
                base_open_rate, base_click_rate, base_convert_rate = 0.3, 0.15, 0.08

            opened = random.random() < base_open_rate
            clicked = opened and random.random() < base_click_rate
            converted = clicked and random.random() < base_convert_rate

            conn.execute(
                """
                INSERT INTO campaign_interactions
                    (interaction_id, scenario_id, customer_id, campaign_id,
                     campaign_type, send_time, value_tier, rfm_segment,
                     unresponsive_count, days_since_last_engagement,
                     opened, clicked, converted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    interaction_id,
                    scenario_id,
                    customer_id,
                    f"{scenario_id}_general",
                    'general',
                    self.env.now,
                    customer['value_tier'].value,
                    self._calculate_rfm_segment(customer),
                    customer['unresponsive_count'],
                    days_since_engagement,
                    opened,
                    clicked,
                    converted,
                ),
            )
            interaction_count += 1

        logger.info(f"Persisted {interaction_count} campaign interactions for scenario {scenario_id}")

        # 3. Flush engagement_events buffer (real per-event records)
        engagement_event_count = 0
        for evt in self._engagement_event_buffer:
            conn.execute(
                """
                INSERT INTO engagement_events
                    (event_id, scenario_id, customer_id, event_type,
                     event_time, event_hour, day_of_week,
                     campaign_id, channel, response,
                     value_tier, activity_state,
                     days_since_last_purchase, total_spend,
                     purchase_count, loyalty_points, churn_risk_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evt['event_id'],
                    scenario_id,
                    evt['customer_id'],
                    evt['event_type'],
                    evt['event_time'],
                    evt['event_hour'],
                    evt['day_of_week'],
                    evt['campaign_id'],
                    evt['channel'],
                    evt['response'],
                    evt['value_tier'],
                    evt['activity_state'],
                    evt['days_since_last_purchase'],
                    evt['total_spend'],
                    evt['purchase_count'],
                    evt['loyalty_points'],
                    evt['churn_risk_score'],
                ),
            )
            engagement_event_count += 1

        logger.info(f"Persisted {engagement_event_count} engagement events for scenario {scenario_id}")


# ========== WORKFLOW FACTORY ==========

def create_engagement_workflow(env: simpy.Environment, config: SimulationConfig,
                               resources: ResourceRegistry, persistence: PersistenceManager,
                               metrics: MetricsCollector) -> CustomerEngagementWorkflow:
    """Factory function to create and configure customer engagement workflow"""
    workflow = CustomerEngagementWorkflow(env, config, resources, persistence, metrics)
    return workflow
