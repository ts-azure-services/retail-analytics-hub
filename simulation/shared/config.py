"""
Configuration and distribution parameters for retail simulations.

This module defines all configurable parameters including:
- Random distributions for customer behavior
- Resource capacities
- Service level agreements (SLAs)
- Channel-specific settings
- Per-workflow assumptions (omnichannel, inventory, engagement)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


@dataclass
class DistributionConfig:
    """Configuration for random distributions used in simulation"""
    
    # Interarrival time parameters (arrivals per hour for Poisson process)
    arrival_rate_online: float = 20.0  # customers/hour
    arrival_rate_in_store: float = 15.0  # customers/hour
    arrival_rate_bopis: float = 5.0  # customers/hour
    
    # Time-of-day multipliers (24 hours) - peaks during business hours
    time_of_day_multipliers: List[float] = field(default_factory=lambda: [
        0.3, 0.2, 0.1, 0.1, 0.2, 0.3,  # 12am-6am: very low
        0.5, 0.7, 0.9, 1.2, 1.5, 1.8,  # 6am-12pm: morning ramp-up
        2.0, 1.9, 1.7, 1.5, 1.3, 1.4,  # 12pm-6pm: peak hours
        1.6, 1.5, 1.2, 0.9, 0.6, 0.4   # 6pm-12am: evening decline
    ])
    
    # Browsing time parameters (minutes) - triangular distribution
    browsing_time_min: float = 2.0
    browsing_time_mode: float = 8.0
    browsing_time_max: float = 30.0
    
    # Service time parameters (minutes) - triangular distribution
    service_time_checkout_min: float = 1.0
    service_time_checkout_mode: float = 3.0
    service_time_checkout_max: float = 8.0
    
    service_time_packing_min: float = 5.0
    service_time_packing_mode: float = 10.0
    service_time_packing_max: float = 20.0
    
    # Basket size parameters (Poisson distribution)
    basket_size_mean: float = 3.0
    
    # SKU selection parameters (Zipf distribution for popularity)
    sku_popularity_alpha: float = 1.2  # Higher = more concentrated on popular items
    
    # Abandonment probabilities (LOWERED for more completed orders)
    abandonment_rate_online: float = 0.25  # 25% abandon cart online (was 65%)
    abandonment_rate_in_store: float = 0.05  # 5% abandon in-store (was 10%)
    abandonment_rate_bopis: float = 0.15  # 15% abandon BOPIS (was 30%)
    
    # Payment failure rate (LOWERED for more completed orders)
    payment_failure_rate: float = 0.01  # 1% of payments fail (was 2%)
    
    # Order completion tuning (NEW)
    min_basket_size: int = 2  # Minimum items per basket
    max_basket_size: int = 8  # Maximum items per basket
    force_completion_rate: float = 0.90  # 90% of orders should complete successfully
    
    # Return probabilities by category
    return_rates: Dict[str, float] = field(default_factory=lambda: {
        "Electronics": 0.08,
        "Clothing": 0.20,
        "Home & Garden": 0.10,
        "Sports": 0.12,
        "Books": 0.05,
        "Toys": 0.15,
        "Food": 0.03
    })
    
    # Return time window (days) - uniform distribution
    return_window_min: float = 1.0
    return_window_max: float = 30.0
    
    # Fulfillment delay parameters (days) - uniform distribution
    fulfillment_delay_min: float = 1.0
    fulfillment_delay_max: float = 3.0
    
    # BOPIS preparation time (minutes) - triangular distribution
    bopis_prep_time_min: float = 15.0
    bopis_prep_time_mode: float = 45.0
    bopis_prep_time_max: float = 120.0


@dataclass
class ResourceConfig:
    """Configuration for resource capacities"""
    
    # Checkout resources (per location)
    checkout_counters_per_store: int = 5
    
    # Fulfillment resources
    warehouse_pickers: int = 10
    warehouse_packers: int = 8
    store_fulfillment_staff: int = 3
    
    # Inventory locations
    locations: List[str] = field(default_factory=lambda: [
        "WAREHOUSE-001",
        "STORE-NYC",
        "STORE-LA",
        "STORE-CHI",
        "STORE-MIA"
    ])
    
    # Default store for in-store purchases
    default_store: str = "STORE-NYC"


@dataclass
class SLAConfig:
    """Service Level Agreement configurations"""
    
    # Delivery time SLA (days)
    delivery_sla_days: float = 2.0
    
    # BOPIS ready time SLA (hours)
    bopis_ready_sla_hours: float = 1.0
    
    # Maximum queue wait time before customer balks (minutes)
    max_queue_wait_minutes: float = 15.0


@dataclass
class DatabaseConfig:
    """Database connection configurations"""
    
    # PostgreSQL
    postgres_host: str = field(default_factory=lambda: os.getenv("POSTGRESQL_SERVER_FQDN", ""))
    postgres_database: str = field(default_factory=lambda: os.getenv("POSTGRESQL_DATABASE_NAME", ""))
    postgres_user: str = field(default_factory=lambda: os.getenv("POSTGRESQL_ADMIN_LOGIN", ""))
    postgres_password: str = field(default_factory=lambda: os.getenv("POSTGRESQL_ADMIN_PASSWORD", ""))
    
    # CosmosDB
    cosmos_endpoint: str = field(default_factory=lambda: os.getenv("COSMOSDB_ENDPOINT", ""))
    cosmos_database: str = field(default_factory=lambda: os.getenv("COSMOSDB_DATABASE_NAME", ""))
    
    # Event Hub
    eventhub_connection_string: str = field(default_factory=lambda: os.getenv("EVENTHUB_CONNECTION_STRING", ""))
    eventhub_name: str = field(default_factory=lambda: os.getenv("EVENTHUB_NAME", "retail-events"))


@dataclass
class OmnichannelAssumptions:
    """All assumptions for the omnichannel purchase workflow.

    Centralizes every parameter that was previously hardcoded in
    omnichannel_purchase.py so sweeps can override them.
    """

    # In-store browsing: number of item pickups (uniform)
    item_pickups_min: int = 3
    item_pickups_max: int = 8

    # Queue balking behavior
    queue_balk_threshold: int = 10        # customers in queue before balking
    queue_balk_probability: float = 0.3   # probability of leaving if queue is long

    # Online browsing behavior
    online_pages_min: int = 2
    online_pages_max: int = 8
    search_results_min: int = 5
    search_results_max: int = 50

    # Online/BOPIS checkout time (minutes, uniform)
    online_checkout_time_min: float = 1.0
    online_checkout_time_max: float = 3.0
    bopis_checkout_time_min: float = 1.0
    bopis_checkout_time_max: float = 3.0

    # Picking time (minutes, triangular)
    picking_time_min: float = 5.0
    picking_time_mode: float = 10.0
    picking_time_max: float = 20.0

    # BOPIS customer pickup delay (minutes, uniform)
    bopis_pickup_delay_min: float = 30.0
    bopis_pickup_delay_max: float = 240.0

    # Catalog lists
    payment_methods: List[str] = field(default_factory=lambda: [
        'credit_card', 'debit_card', 'paypal'
    ])
    web_referrers: List[str] = field(default_factory=lambda: [
        'google', 'direct', 'email', 'social'
    ])
    page_types: List[str] = field(default_factory=lambda: [
        'category', 'product_detail', 'search'
    ])
    carriers: List[str] = field(default_factory=lambda: [
        'UPS', 'FedEx', 'USPS', 'DHL'
    ])


@dataclass
class InventoryAssumptions:
    """All assumptions for the inventory replenishment workflow.

    Centralizes every parameter that was previously hardcoded in
    inventory_replenishment.py so sweeps can override them.
    """

    # Default policy values (fallback when DB row is NULL)
    default_reorder_point: int = 50
    default_order_quantity: int = 100
    default_safety_stock: int = 20
    default_lead_time_days: float = 7.0

    # Lead time variability (std dev as fraction of mean)
    lead_time_std_factor: float = 0.2

    # Demand generation
    daily_demand_min: float = 5.0         # units/day lower bound
    daily_demand_max: float = 20.0        # units/day upper bound
    demand_qty_min: int = 1               # units per transaction
    demand_qty_max: int = 3

    # Supplier behavior
    min_lead_time_enforced: float = 1.0   # floor on lead time (days)
    unreliable_delay_min: float = 1.2     # delay multiplier for unreliable suppliers
    unreliable_delay_max: float = 2.0

    # Receiving process
    receiving_time_min: float = 10.0      # minutes
    receiving_time_max: float = 30.0

    # Short shipments
    short_shipment_probability: float = 0.05
    short_shipment_qty_min: float = 0.7   # fraction of ordered qty received
    short_shipment_qty_max: float = 0.95

    # Delivery performance
    on_time_delivery_tolerance: float = 1.1  # 10% grace period

    # Shrinkage
    daily_shrinkage_rate: float = 0.001   # 0.1% per day

    # Periodic review
    review_interval_days: float = 7.0
    audit_discrepancy_probability: float = 0.1
    audit_adjustment_min: int = -5
    audit_adjustment_max: int = 5


@dataclass
class EngagementAssumptions:
    """All assumptions for the customer engagement workflow.

    Centralizes every parameter that was previously hardcoded in
    customer_engagement.py so sweeps can override them.
    """

    # Product categories
    product_categories: List[str] = field(default_factory=lambda: [
        "Electronics", "Clothing", "Home & Garden", "Sports", "Books", "Toys", "Food"
    ])
    preferred_category_min: int = 1
    preferred_category_max: int = 3
    marketing_opt_in_probability: float = 0.7

    # Value tier thresholds (static — initial load from purchase history)
    static_vip_threshold: float = 600.0
    static_high_threshold: float = 300.0
    static_medium_threshold: float = 100.0

    # Value tier thresholds (dynamic — during simulation purchases)
    dynamic_vip_threshold: float = 5000.0
    dynamic_high_threshold: float = 2000.0
    dynamic_medium_threshold: float = 500.0

    # Activity state thresholds (days since last purchase)
    active_threshold_days: int = 30
    lapsed_threshold_days: int = 90
    churned_threshold_days: int = 180

    # RFM segment criteria
    rfm_champions_recency: int = 90
    rfm_champions_frequency: int = 2
    rfm_champions_monetary: float = 200.0
    rfm_loyal_recency: int = 120
    rfm_loyal_frequency: int = 1
    rfm_loyal_monetary: float = 100.0
    rfm_potential_recency: int = 180
    rfm_potential_monetary: float = 50.0

    # Churn risk scoring weights
    churn_risk_high_recency_increment: float = 0.4    # >180 days inactive
    churn_risk_medium_recency_increment: float = 0.2  # >90 days inactive
    churn_risk_unresponsive_increment: float = 0.3    # >3 ignored campaigns
    churn_risk_vip_decrement: float = 0.2
    churn_risk_high_decrement: float = 0.1

    # Lifecycle process timing
    lifecycle_wait_rate: float = 0.5      # expovariate(1/X) hours between checks
    retention_campaign_trigger_probability: float = 0.1

    # Scheduled campaign response rates
    base_email_response_rate: float = 0.05
    vip_response_boost: float = 0.10
    high_response_boost: float = 0.05
    click_to_conversion_rate: float = 0.3

    # Retention campaign
    retention_response_rate: float = 0.25

    # All-customers campaign
    all_customers_base_response: float = 0.08
    all_customers_vip_boost: float = 0.12
    all_customers_high_boost: float = 0.07
    all_customers_medium_boost: float = 0.03
    all_customers_conversion_rate: float = 0.25

    # Loyalty program
    loyalty_points_ratio: float = 0.1     # initial load: 10% of lifetime spend
    points_per_dollar: float = 1.0        # earned per purchase dollar
    redemption_threshold: int = 100       # min points to redeem
    redemption_probability: float = 0.4
    max_points_per_redemption: int = 100
    points_to_dollar_ratio: float = 0.1   # $1 per 10 points

    # Service issues
    service_issue_interval_rate: float = 18.0  # expovariate(1/X) hours between checks
    service_issue_probability: float = 0.1
    service_issue_types: List[str] = field(default_factory=lambda: [
        'shipping_delay', 'product_defect', 'billing_issue', 'return'
    ])
    resolution_time_min: float = 0.1      # hours
    resolution_time_max: float = 0.5
    satisfaction_min: int = 1
    satisfaction_max: int = 5
    good_service_threshold: int = 4
    churn_risk_reduction_good_service: float = 0.1
    churn_risk_increase_poor_service: float = 0.2

    # Campaign scheduling (interval in days)
    campaign_weekly_newsletter_interval: float = 7.0
    campaign_monthly_promo_interval: float = 30.0
    campaign_vip_offers_interval: float = 14.0
    campaign_welcome_series_interval: float = 3.0
    campaign_all_customers_interval: float = 5.0

    # Time acceleration factor for campaign/segmentation processes
    acceleration_factor: float = 0.1      # 10x faster than real time


@dataclass
class SimulationConfig:
    """Master configuration for simulation"""

    distributions: DistributionConfig = field(default_factory=DistributionConfig)
    resources: ResourceConfig = field(default_factory=ResourceConfig)
    sla: SLAConfig = field(default_factory=SLAConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)

    # Per-workflow assumptions
    omnichannel: OmnichannelAssumptions = field(default_factory=OmnichannelAssumptions)
    inventory: InventoryAssumptions = field(default_factory=InventoryAssumptions)
    engagement: EngagementAssumptions = field(default_factory=EngagementAssumptions)

    # Simulation runtime parameters
    simulation_duration_hours: float = 24.0  # Simulate 24 hours
    random_seed: int = 42  # For reproducibility
    customer_limit: int = 500  # Max customers to load for engagement simulation

    # Logging and output
    log_level: str = "INFO"
    enable_console_output: bool = True
    enable_event_streaming: bool = True

    def __post_init__(self):
        """Load config overrides from overlay file if present."""
        overlay_path = Path(__file__).parent.parent.parent / "config_overrides.json"
        if overlay_path.exists():
            try:
                with open(overlay_path) as f:
                    overrides = json.load(f)
                self._apply_overrides(overrides)
                logger.info(f"Loaded config overrides from {overlay_path}")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load config overrides: {e}")

    def _apply_overrides(self, overrides: Dict[str, Any]):
        """Apply override dict to config fields.

        Expected format:
        {
            "distributions": {"arrival_rate_online": 30.0},
            "omnichannel": {"queue_balk_threshold": 15},
            "inventory": {"daily_shrinkage_rate": 0.005},
            "engagement": {"base_email_response_rate": 0.08}
        }
        """
        for section_name, section_overrides in overrides.items():
            section = getattr(self, section_name, None)
            if section is None:
                logger.warning(f"Unknown config section in overrides: {section_name}")
                continue
            if not isinstance(section_overrides, dict):
                continue
            for field_name, value in section_overrides.items():
                if hasattr(section, field_name):
                    setattr(section, field_name, value)
                else:
                    logger.warning(
                        f"Unknown field in overrides: {section_name}.{field_name}"
                    )

    def validate(self) -> bool:
        """Validate configuration completeness"""
        # When using local DuckDB backend, Azure credentials are not needed
        from .persistence import USE_LOCAL_DB
        if USE_LOCAL_DB:
            return True

        required_fields = [
            self.database.postgres_host,
            self.database.postgres_database,
            self.database.postgres_user,
            self.database.postgres_password,
            self.database.cosmos_endpoint,
            self.database.cosmos_database
        ]

        if not all(required_fields):
            print("Warning: Some database configuration values are missing")
            return False

        return True


# Global configuration instance
DEFAULT_CONFIG = SimulationConfig()
