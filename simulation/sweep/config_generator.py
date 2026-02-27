"""
Configuration generator for parameter sweep experiments.

Generates parameter combinations for systematic exploration of the
simulation parameter space.
"""

import itertools
import random
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class SweepParameter:
    """Definition of a parameter to sweep."""
    name: str
    values: List[Any]
    description: str = ""


@dataclass
class SweepConfig:
    """Configuration for a parameter sweep experiment."""
    name: str
    description: str
    parameters: List[SweepParameter]
    base_duration_hours: float = 24.0

    @property
    def total_scenarios(self) -> int:
        """Total number of scenarios in this sweep (grid search)."""
        if not self.parameters:
            return 0
        count = 1
        for param in self.parameters:
            count *= len(param.values)
        return count


# Pre-built sweep configurations

CONVERSION_SWEEP = SweepConfig(
    name="conversion",
    description="Sweep parameters affecting customer conversion rates",
    parameters=[
        SweepParameter(
            name="abandonment_rate_online",
            values=[0.15, 0.25, 0.35, 0.45],
            description="Online cart abandonment rate"
        ),
        SweepParameter(
            name="abandonment_rate_in_store",
            values=[0.03, 0.05, 0.08],
            description="In-store abandonment rate"
        ),
        SweepParameter(
            name="payment_failure_rate",
            values=[0.01, 0.02, 0.05],
            description="Payment processing failure rate"
        ),
    ],
    base_duration_hours=24.0,
)


DEMAND_SWEEP = SweepConfig(
    name="demand",
    description="Sweep parameters affecting customer demand patterns",
    parameters=[
        SweepParameter(
            name="arrival_rate_online",
            values=[15.0, 20.0, 30.0, 50.0],
            description="Online customer arrival rate (per hour)"
        ),
        SweepParameter(
            name="arrival_rate_in_store",
            values=[10.0, 15.0, 25.0],
            description="In-store customer arrival rate (per hour)"
        ),
        SweepParameter(
            name="basket_size_mean",
            values=[2.0, 3.0, 5.0],
            description="Mean basket size (items)"
        ),
    ],
    base_duration_hours=24.0,
)


FULFILLMENT_SWEEP = SweepConfig(
    name="fulfillment",
    description="Sweep parameters affecting fulfillment performance",
    parameters=[
        SweepParameter(
            name="fulfillment_delay_max",
            values=[2.0, 3.0, 5.0],
            description="Maximum fulfillment delay (days)"
        ),
        SweepParameter(
            name="service_time_packing_mode",
            values=[5.0, 10.0, 15.0],
            description="Mode packing time (minutes)"
        ),
        SweepParameter(
            name="bopis_prep_time_mode",
            values=[10.0, 20.0, 30.0],
            description="Mode BOPIS preparation time (minutes)"
        ),
    ],
    base_duration_hours=24.0,
)


# ===== INVENTORY REPLENISHMENT SWEEPS =====

INVENTORY_SUPPLY_SWEEP = SweepConfig(
    name="inventory_supply",
    description="Sweep supplier and lead time parameters",
    parameters=[
        SweepParameter(
            name="supplier_reliability",
            values=[0.85, 0.95, 0.99],
            description="Supplier on-time delivery probability"
        ),
        SweepParameter(
            name="mean_lead_time_days",
            values=[3.0, 7.0, 14.0],
            description="Average supplier lead time (days)"
        ),
        SweepParameter(
            name="lead_time_variability",
            values=[0.1, 0.2, 0.3],
            description="Lead time standard deviation as fraction of mean"
        ),
    ],
    base_duration_hours=168.0,  # 1 week for inventory dynamics
)


INVENTORY_POLICY_SWEEP = SweepConfig(
    name="inventory_policy",
    description="Sweep reorder point and safety stock parameters",
    parameters=[
        SweepParameter(
            name="reorder_point_multiplier",
            values=[1.0, 1.5, 2.0],
            description="Multiplier for calculated reorder point"
        ),
        SweepParameter(
            name="safety_stock_days",
            values=[3, 7, 14],
            description="Safety stock in days of average demand"
        ),
        SweepParameter(
            name="order_quantity_multiplier",
            values=[1.0, 1.5, 2.0],
            description="Multiplier for economic order quantity"
        ),
    ],
    base_duration_hours=168.0,
)


INVENTORY_DEMAND_SWEEP = SweepConfig(
    name="inventory_demand",
    description="Sweep demand and shrinkage parameters",
    parameters=[
        SweepParameter(
            name="mean_daily_demand_multiplier",
            values=[0.5, 1.0, 2.0],
            description="Multiplier for base daily demand"
        ),
        SweepParameter(
            name="daily_shrinkage_rate",
            values=[0.001, 0.005, 0.01],
            description="Daily inventory shrinkage rate"
        ),
        SweepParameter(
            name="demand_variability",
            values=[0.2, 0.4, 0.6],
            description="Demand coefficient of variation"
        ),
    ],
    base_duration_hours=168.0,
)


# ===== CUSTOMER ENGAGEMENT SWEEPS =====

ENGAGEMENT_CAMPAIGN_SWEEP = SweepConfig(
    name="engagement_campaign",
    description="Sweep campaign effectiveness parameters",
    parameters=[
        SweepParameter(
            name="base_email_response_rate",
            values=[0.03, 0.08, 0.15],
            description="Base email open/click rate"
        ),
        SweepParameter(
            name="vip_response_bonus",
            values=[0.05, 0.10, 0.15],
            description="Additional response rate for VIP customers"
        ),
        SweepParameter(
            name="conversion_rate_from_click",
            values=[0.15, 0.25, 0.40],
            description="Probability of purchase after clicking"
        ),
    ],
    base_duration_hours=72.0,  # 3 days for campaign cycles
)


ENGAGEMENT_RETENTION_SWEEP = SweepConfig(
    name="engagement_retention",
    description="Sweep retention and churn parameters",
    parameters=[
        SweepParameter(
            name="retention_offer_response_rate",
            values=[0.15, 0.25, 0.40],
            description="Response rate for retention campaigns"
        ),
        SweepParameter(
            name="churn_threshold_days",
            values=[90, 180, 365],
            description="Days without purchase to trigger churn risk"
        ),
        SweepParameter(
            name="lapsed_threshold_days",
            values=[30, 60, 90],
            description="Days without purchase to mark as lapsed"
        ),
    ],
    base_duration_hours=72.0,
)


ENGAGEMENT_LOYALTY_SWEEP = SweepConfig(
    name="engagement_loyalty",
    description="Sweep loyalty program parameters",
    parameters=[
        SweepParameter(
            name="loyalty_points_per_dollar",
            values=[0.5, 1.0, 2.0],
            description="Points earned per dollar spent"
        ),
        SweepParameter(
            name="redemption_threshold_points",
            values=[50, 100, 200],
            description="Minimum points required for redemption"
        ),
        SweepParameter(
            name="points_value_ratio",
            values=[0.05, 0.10, 0.15],
            description="Dollar value per point when redeeming"
        ),
    ],
    base_duration_hours=72.0,
)


# Registry of available sweeps
SWEEP_REGISTRY: Dict[str, SweepConfig] = {
    # Omnichannel workflow
    "conversion": CONVERSION_SWEEP,
    "demand": DEMAND_SWEEP,
    "fulfillment": FULFILLMENT_SWEEP,
    # Inventory workflow
    "inventory_supply": INVENTORY_SUPPLY_SWEEP,
    "inventory_policy": INVENTORY_POLICY_SWEEP,
    "inventory_demand": INVENTORY_DEMAND_SWEEP,
    # Engagement workflow
    "engagement_campaign": ENGAGEMENT_CAMPAIGN_SWEEP,
    "engagement_retention": ENGAGEMENT_RETENTION_SWEEP,
    "engagement_loyalty": ENGAGEMENT_LOYALTY_SWEEP,
}


class ConfigGenerator:
    """Generates configuration variations for parameter sweeps."""

    def __init__(self, sweep_config: SweepConfig, base_seed: int = 42):
        """
        Initialize the config generator.

        Args:
            sweep_config: The sweep configuration to use
            base_seed: Base random seed for reproducibility
        """
        self.sweep_config = sweep_config
        self.base_seed = base_seed
        logger.info(
            f"ConfigGenerator initialized for '{sweep_config.name}' sweep "
            f"({sweep_config.total_scenarios} scenarios)"
        )

    def generate_grid(self) -> Iterator[Tuple[int, Dict[str, Any]]]:
        """
        Generate all parameter combinations (grid search).

        Yields:
            Tuples of (scenario_index, parameter_dict)
        """
        if not self.sweep_config.parameters:
            return

        # Get all parameter names and values
        param_names = [p.name for p in self.sweep_config.parameters]
        param_values = [p.values for p in self.sweep_config.parameters]

        # Generate Cartesian product
        for idx, combination in enumerate(itertools.product(*param_values)):
            params = dict(zip(param_names, combination))
            params["_scenario_index"] = idx
            params["_scenario_seed"] = self.base_seed + idx
            yield idx, params

    def generate_random(
        self, n_samples: int, seed: Optional[int] = None
    ) -> Iterator[Tuple[int, Dict[str, Any]]]:
        """
        Generate random parameter combinations (random search).

        Args:
            n_samples: Number of random samples to generate
            seed: Random seed (defaults to base_seed)

        Yields:
            Tuples of (scenario_index, parameter_dict)
        """
        rng = random.Random(seed or self.base_seed)

        for idx in range(n_samples):
            params = {}
            for param in self.sweep_config.parameters:
                params[param.name] = rng.choice(param.values)
            params["_scenario_index"] = idx
            params["_scenario_seed"] = self.base_seed + idx
            yield idx, params

    def generate_scenarios(
        self,
        sweep_type: str = "grid",
        n_samples: int = 36,
    ) -> List[Dict[str, Any]]:
        """
        Generate all scenarios for the sweep.

        Args:
            sweep_type: "grid" for exhaustive search, "random" for random sampling
            n_samples: Number of samples for random search

        Returns:
            List of scenario configurations
        """
        scenarios = []

        if sweep_type == "grid":
            for idx, params in self.generate_grid():
                scenario = self._build_scenario(idx, params)
                scenarios.append(scenario)
        elif sweep_type == "random":
            for idx, params in self.generate_random(n_samples):
                scenario = self._build_scenario(idx, params)
                scenarios.append(scenario)
        else:
            raise ValueError(f"Unknown sweep_type: {sweep_type}")

        logger.info(f"Generated {len(scenarios)} scenarios for {sweep_type} search")
        return scenarios

    def _build_scenario(self, idx: int, params: Dict[str, Any]) -> Dict[str, Any]:
        """Build a complete scenario configuration."""
        scenario_id = f"{self.sweep_config.name}_{idx:04d}"

        return {
            "scenario_id": scenario_id,
            "scenario_name": f"{self.sweep_config.name.title()} Scenario {idx + 1}",
            "sweep_name": self.sweep_config.name,
            "scenario_index": idx,
            "random_seed": params.pop("_scenario_seed", self.base_seed + idx),
            "duration_hours": self.sweep_config.base_duration_hours,
            "parameters": params,
        }


def get_sweep_config(name: str) -> SweepConfig:
    """Get a sweep configuration by name."""
    if name not in SWEEP_REGISTRY:
        available = ", ".join(SWEEP_REGISTRY.keys())
        raise ValueError(f"Unknown sweep '{name}'. Available: {available}")
    return SWEEP_REGISTRY[name]


def list_available_sweeps() -> List[str]:
    """List all available sweep configuration names."""
    return list(SWEEP_REGISTRY.keys())
