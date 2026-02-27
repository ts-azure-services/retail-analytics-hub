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
        
        # Category preferences (for recommendation logic)
        self.categories = ["Electronics", "Clothing", "Home & Garden", "Sports", "Books", "Toys", "Food"]
        
        # Real data from databases (loaded via load_real_data())
        self.real_customer_ids: List[str] = []
        self.real_products: List[Dict] = []
        self.product_names: List[str] = []  # For realistic search queries
        
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
        preferred_categories = random.sample(self.categories, k=random.randint(1, 3))
        marketing_opt_in = random.random() < 0.7  # 70% opt in
        
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
        
        # Skip database writes - customers already seeded in PostgreSQL
        # This saves 3+ minutes during initialization (200 DB operations avoided)
        logger.debug(f"Registered customer: {customer_id} (in-memory only)")
    
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
                
                # Calculate loyalty points (10% of total spend)
                customer['loyalty_points'] = int(customer['total_spend'] * 0.1)
                
                # Determine value tier based on total spend
                if customer['total_spend'] >= 600:
                    customer['value_tier'] = CustomerValueTier.VIP
                elif customer['total_spend'] >= 300:
                    customer['value_tier'] = CustomerValueTier.HIGH
                elif customer['total_spend'] >= 100:
                    customer['value_tier'] = CustomerValueTier.MEDIUM
                else:
                    customer['value_tier'] = CustomerValueTier.LOW
                
                # Set activity state based on purchase recency
                if last_purchase_date:
                    if days_ago < 30:
                        customer['activity_state'] = CustomerActivityState.ACTIVE
                    elif days_ago < 90:
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
        """Log engagement event to CosmosDB (durable engagement history)"""
        event_doc = {
            'id': str(uuid4()),
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
                (customer_id, points_change, reason, transaction_date)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
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
        
        # Relaxed segmentation logic for realistic seeded data
        # Champions: Recent (90 days), frequent (2+), high spend ($200+)
        if recency <= 90 and frequency >= 2 and monetary >= 200:
            return "Champions"
        # Loyal: Recent (120 days), some purchases (1+), moderate spend ($100+)
        elif recency <= 120 and frequency >= 1 and monetary >= 100:
            return "Loyal"
        # Potential: Had any purchase in last 180 days OR any spend
        elif recency <= 180 or monetary >= 50:
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
        
        if days_since > 180:
            risk_score += 0.4
        elif days_since > 90:
            risk_score += 0.2
        
        # Engagement factor
        if customer['unresponsive_count'] > 3:
            risk_score += 0.3
        
        # Value factor (high value customers less likely to churn)
        if customer['value_tier'] == CustomerValueTier.VIP:
            risk_score -= 0.2
        elif customer['value_tier'] == CustomerValueTier.HIGH:
            risk_score -= 0.1
        
        return max(0.0, min(1.0, risk_score))
    
    # ========== CUSTOMER LIFECYCLE PROCESS ==========
    
    def customer_lifecycle_process(self, customer_id: str):
        """Simulate customer lifecycle with state transitions"""
        customer = self.customers.get(customer_id)
        if not customer:
            return
        
        while self.env.now < self.simulation_end_time:
            # Wait for next event (purchase or time-based check)
            # Accelerated for testing: check every ~12 hours instead of ~30 days
            wait_time = random.expovariate(1.0 / 0.5)  # ~30 minute wait in sim time
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
            
            if days_since_purchase < 30:
                customer['activity_state'] = CustomerActivityState.ACTIVE
            elif days_since_purchase < 90:
                customer['activity_state'] = CustomerActivityState.LAPSED
            elif days_since_purchase < 180:
                # At risk - trigger retention campaign
                if random.random() < 0.1:  # 10% chance to trigger
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
        
        # Award loyalty points (1 point per dollar)
        points_earned = int(amount)
        self._update_loyalty_account(customer_id, points_earned, "purchase")
        self.metrics.record_metric('loyalty_points_earned', points_earned)
        
        # Update value tier based on total spend
        if customer['total_spend'] >= 5000:
            customer['value_tier'] = CustomerValueTier.VIP
        elif customer['total_spend'] >= 2000:
            customer['value_tier'] = CustomerValueTier.HIGH
        elif customer['total_spend'] >= 500:
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
                accelerated_interval = interval_days * 24 * 0.1  # 10x faster for testing
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
                response_prob = 0.05  # Base 5% response rate
                
                # Adjust by value tier
                if customer['value_tier'] == CustomerValueTier.VIP:
                    response_prob += 0.10
                elif customer['value_tier'] == CustomerValueTier.HIGH:
                    response_prob += 0.05
                
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
                    if random.random() < 0.3:  # 30% of clickers purchase
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
            # Use 1/10th of interval_days for testing (7 days → 16.8 hours)
            accelerated_interval = interval_days * 24 * 0.1  # 10x faster for testing
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
        response_prob = 0.25  # 25% response rate
        
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
            
            if customer['loyalty_points'] >= 100:  # Lowered threshold for more activity
                # Redeem with some probability
                if random.random() < 0.4:  # 40% chance to redeem
                    points_to_redeem = min(100, customer['loyalty_points'])  # Redeem up to 100
                    reward_value = points_to_redeem // 10  # $1 per 10 points
                    
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
            # Random service issues (accelerated for testing)
            # Check every ~18 hours instead of ~6 months
            yield self.env.timeout(random.expovariate(1.0 / 18.0))
            
            # Check if simulation should end
            if self.env.now >= self.simulation_end_time:
                break
            
            if random.random() < 0.1:  # 10% of time periods have issues
                ticket_id = f"TICKET-{uuid4().hex[:8].upper()}"
                issue_type = random.choice(['shipping_delay', 'product_defect', 'billing_issue', 'return'])
                
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
                
                # Simulate resolution (accelerated for testing)
                resolution_time = random.uniform(0.1, 0.5)  # 6-30 minutes instead of 1-5 days
                yield self.env.timeout(resolution_time)
                
                # Satisfaction rating
                satisfaction = random.randint(1, 5)
                
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
                if satisfaction >= 4:
                    # Good service reduces churn risk
                    customer['churn_risk_score'] = max(0, customer['churn_risk_score'] - 0.1)
                    self.metrics.record_metric('service_tickets_satisfied', 1)
                else:
                    # Poor service increases churn risk
                    customer['churn_risk_score'] = min(1.0, customer['churn_risk_score'] + 0.2)
                    self.metrics.record_metric('service_tickets_unsatisfied', 1)
                
                self._update_customer_scores(customer_id)
                
                self.metrics.record_metric('service_tickets_resolved', 1)
                
                logger.info(f"[{self.env.now:.1f}h] ✓ Ticket {ticket_id} resolved (satisfaction: {satisfaction}/5)")
    
    # ========== SEGMENTATION UPDATE PROCESS ==========
    
    def segmentation_update_process(self, interval_days: float = 7.0):
        """Periodic segmentation and scoring update"""
        while self.env.now < self.simulation_end_time:
            # Accelerated for testing: run every 16.8 hours instead of 7 days
            yield self.env.timeout(interval_days * 24 * 0.1)  # 10x faster
            
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
        # Weekly newsletter to loyal customers
        self.env.process(self.scheduled_campaign_process("weekly_newsletter", "Loyal", 7.0))
        
        # Monthly promotion to potential customers
        self.env.process(self.scheduled_campaign_process("monthly_promo", "Potential", 30.0))
        
        # Bi-weekly to champions
        self.env.process(self.scheduled_campaign_process("vip_offers", "Champions", 14.0))
        
        # Welcome/reactivation series for new/inactive customers (every 3 days accelerated)
        self.env.process(self.scheduled_campaign_process("welcome_series", "Needs Attention", 3.0))
        
        # NEW: All opted-in customers campaign (guaranteed to have targets)
        self.env.process(self.all_customers_campaign_process("all_customers_promo", 5.0))
    
    def all_customers_campaign_process(self, campaign_id: str, interval_days: float = 5.0):
        """Run campaign targeting ALL opted-in customers (guaranteed engagement)"""
        while self.env.now < self.simulation_end_time:
            # Target all customers who opted in to marketing
            eligible_customers = [
                cid for cid, cust in self.customers.items()
                if cust['marketing_opt_in']
            ]
            
            if not eligible_customers:
                yield self.env.timeout(interval_days * 24 * 0.1)
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
                response_prob = 0.08  # Base 8% response rate for general campaigns
                
                # Adjust by value tier
                if customer['value_tier'] == CustomerValueTier.VIP:
                    response_prob += 0.12
                elif customer['value_tier'] == CustomerValueTier.HIGH:
                    response_prob += 0.07
                elif customer['value_tier'] == CustomerValueTier.MEDIUM:
                    response_prob += 0.03
                
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
                    if random.random() < 0.25:  # 25% of clickers convert
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
            accelerated_interval = interval_days * 24 * 0.1  # 10x faster
            yield self.env.timeout(accelerated_interval)
    
    def start_segmentation_updates(self):
        """Start periodic segmentation updates"""
        self.env.process(self.segmentation_update_process(7.0))  # Weekly
    
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
                    (interaction_id, scenario_id, customer_id, campaign_type,
                     send_time, value_tier, rfm_segment, unresponsive_count,
                     days_since_last_engagement, opened, clicked, converted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    interaction_id,
                    scenario_id,
                    customer_id,
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


# ========== WORKFLOW FACTORY ==========

def create_engagement_workflow(env: simpy.Environment, config: SimulationConfig,
                               resources: ResourceRegistry, persistence: PersistenceManager,
                               metrics: MetricsCollector) -> CustomerEngagementWorkflow:
    """Factory function to create and configure customer engagement workflow"""
    workflow = CustomerEngagementWorkflow(env, config, resources, persistence, metrics)
    return workflow
