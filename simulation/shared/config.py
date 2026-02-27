"""
Configuration and distribution parameters for retail simulations.

This module defines all configurable parameters including:
- Random distributions for customer behavior
- Resource capacities
- Service level agreements (SLAs)
- Channel-specific settings
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List
from dotenv import load_dotenv

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
class SimulationConfig:
    """Master configuration for simulation"""
    
    distributions: DistributionConfig = field(default_factory=DistributionConfig)
    resources: ResourceConfig = field(default_factory=ResourceConfig)
    sla: SLAConfig = field(default_factory=SLAConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    
    # Simulation runtime parameters
    simulation_duration_hours: float = 24.0  # Simulate 24 hours
    random_seed: int = 42  # For reproducibility
    customer_limit: int = 500  # Max customers to load for engagement simulation
    
    # Logging and output
    log_level: str = "INFO"
    enable_console_output: bool = True
    enable_event_streaming: bool = True
    
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
            print("⚠ Warning: Some database configuration values are missing")
            return False
        
        return True


# Global configuration instance
DEFAULT_CONFIG = SimulationConfig()
