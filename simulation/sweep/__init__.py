"""
Parameter sweep framework for systematic simulation exploration.

This module provides tools for:
- Generating parameter combinations for sweep experiments
- Running multiple simulation scenarios
- Tracking scenario metadata and results
"""

from .config_generator import (
    ConfigGenerator,
    CONVERSION_SWEEP,
    DEMAND_SWEEP,
    FULFILLMENT_SWEEP,
    INVENTORY_SUPPLY_SWEEP,
    INVENTORY_POLICY_SWEEP,
    INVENTORY_DEMAND_SWEEP,
    ENGAGEMENT_CAMPAIGN_SWEEP,
    ENGAGEMENT_RETENTION_SWEEP,
    ENGAGEMENT_LOYALTY_SWEEP,
)
from .scenario_tracker import ScenarioTracker
from .sweep_runner import SweepRunner

__all__ = [
    "ConfigGenerator",
    # Omnichannel sweeps
    "CONVERSION_SWEEP",
    "DEMAND_SWEEP",
    "FULFILLMENT_SWEEP",
    # Inventory sweeps
    "INVENTORY_SUPPLY_SWEEP",
    "INVENTORY_POLICY_SWEEP",
    "INVENTORY_DEMAND_SWEEP",
    # Engagement sweeps
    "ENGAGEMENT_CAMPAIGN_SWEEP",
    "ENGAGEMENT_RETENTION_SWEEP",
    "ENGAGEMENT_LOYALTY_SWEEP",
    # Core classes
    "ScenarioTracker",
    "SweepRunner",
]
