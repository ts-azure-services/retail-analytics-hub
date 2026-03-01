"""
Sweep runner for executing multiple simulation scenarios.

Orchestrates the execution of parameter sweep experiments across
all workflow types: omnichannel, inventory, and engagement.
"""

import logging
import random
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import simpy

from ..shared.config import SimulationConfig
from ..shared.resources import ResourceRegistry
from ..shared.persistence import PersistenceManager
from ..shared.metrics import MetricsCollector
from ..workflows.omnichannel_purchase import OmnichannelPurchaseWorkflow
from ..workflows.inventory_replenishment import InventoryReplenishmentWorkflow
from ..workflows.customer_engagement import CustomerEngagementWorkflow
from .config_generator import ConfigGenerator, get_sweep_config, SweepConfig

logger = logging.getLogger(__name__)


# Map sweep names to workflow types
SWEEP_WORKFLOW_MAP = {
    # Omnichannel sweeps
    "conversion": "omnichannel",
    "demand": "omnichannel",
    "fulfillment": "omnichannel",
    # Inventory sweeps
    "inventory_supply": "inventory",
    "inventory_policy": "inventory",
    "inventory_demand": "inventory",
    # Engagement sweeps
    "engagement_campaign": "engagement",
    "engagement_retention": "engagement",
    "engagement_loyalty": "engagement",
}


class ScenarioTracker:
    """Tracks scenario execution and results."""

    def __init__(self, db_path: str = None):
        from ..shared.local_backend import POSTGRES_DB_PATH
        import duckdb

        self.db_path = db_path or POSTGRES_DB_PATH
        self._conn = duckdb.connect(self.db_path)
        self._ensure_table()

    def _ensure_table(self):
        """Create the simulation_scenarios table if it doesn't exist."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS simulation_scenarios (
                scenario_id VARCHAR PRIMARY KEY,
                scenario_name VARCHAR,
                workflow_type VARCHAR DEFAULT 'omnichannel',
                run_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                duration_hours DOUBLE,
                random_seed INTEGER,
                config_json JSON,
                status VARCHAR DEFAULT 'running',
                total_customers INTEGER,
                total_orders INTEGER,
                total_revenue DOUBLE,
                conversion_rate DOUBLE,
                stockout_count INTEGER,
                fill_rate DOUBLE,
                avg_lead_time DOUBLE,
                churn_rate DOUBLE,
                campaign_response_rate DOUBLE,
                avg_clv DOUBLE
            )
        """)

    def start_scenario(
        self,
        scenario_id: str,
        scenario_name: str,
        workflow_type: str,
        duration_hours: float,
        random_seed: int,
        config: Dict[str, Any],
    ) -> None:
        """Record the start of a scenario execution."""
        import json

        config_json = json.dumps(config)

        self._conn.execute(
            """
            INSERT INTO simulation_scenarios
                (scenario_id, scenario_name, workflow_type, run_timestamp,
                 duration_hours, random_seed, config_json, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'running')
            ON CONFLICT (scenario_id) DO UPDATE SET
                scenario_name = excluded.scenario_name,
                workflow_type = excluded.workflow_type,
                run_timestamp = excluded.run_timestamp,
                duration_hours = excluded.duration_hours,
                random_seed = excluded.random_seed,
                config_json = excluded.config_json,
                status = 'running'
            """,
            (
                scenario_id,
                scenario_name,
                workflow_type,
                datetime.now(),
                duration_hours,
                random_seed,
                config_json,
            ),
        )

        logger.info(f"Started tracking scenario: {scenario_id} ({workflow_type})")

    def complete_scenario(
        self,
        scenario_id: str,
        workflow_type: str,
        metrics: Dict[str, Any],
    ) -> None:
        """Record scenario completion with results."""
        # Build update based on workflow type
        if workflow_type == "omnichannel":
            self._conn.execute(
                """
                UPDATE simulation_scenarios
                SET status = 'completed',
                    total_customers = ?,
                    total_orders = ?,
                    total_revenue = ?,
                    conversion_rate = ?
                WHERE scenario_id = ?
                """,
                (
                    metrics.get("total_customers", 0),
                    metrics.get("total_orders", 0),
                    metrics.get("total_revenue", 0),
                    metrics.get("conversion_rate", 0),
                    scenario_id,
                ),
            )
        elif workflow_type == "inventory":
            self._conn.execute(
                """
                UPDATE simulation_scenarios
                SET status = 'completed',
                    stockout_count = ?,
                    fill_rate = ?,
                    avg_lead_time = ?
                WHERE scenario_id = ?
                """,
                (
                    metrics.get("stockout_count", 0),
                    metrics.get("fill_rate", 0),
                    metrics.get("avg_lead_time", 0),
                    scenario_id,
                ),
            )
        elif workflow_type == "engagement":
            self._conn.execute(
                """
                UPDATE simulation_scenarios
                SET status = 'completed',
                    total_customers = ?,
                    churn_rate = ?,
                    campaign_response_rate = ?,
                    avg_clv = ?
                WHERE scenario_id = ?
                """,
                (
                    metrics.get("total_customers", 0),
                    metrics.get("churn_rate", 0),
                    metrics.get("campaign_response_rate", 0),
                    metrics.get("avg_clv", 0),
                    scenario_id,
                ),
            )

        logger.info(f"Completed scenario {scenario_id}")

    def fail_scenario(self, scenario_id: str, error_message: str) -> None:
        """Record scenario failure."""
        self._conn.execute(
            "UPDATE simulation_scenarios SET status = 'failed' WHERE scenario_id = ?",
            (scenario_id,),
        )
        logger.error(f"Failed scenario {scenario_id}: {error_message}")

    def get_sweep_summary(self, sweep_name: str) -> Dict[str, Any]:
        """Get summary statistics for a sweep."""
        result = self._conn.execute(
            """
            SELECT
                COUNT(*) as total_scenarios,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) as running,
                AVG(total_customers) as avg_customers,
                AVG(total_orders) as avg_orders,
                AVG(total_revenue) as avg_revenue,
                AVG(conversion_rate) as avg_conversion,
                MIN(conversion_rate) as min_conversion,
                MAX(conversion_rate) as max_conversion,
                AVG(fill_rate) as avg_fill_rate,
                AVG(churn_rate) as avg_churn_rate
            FROM simulation_scenarios
            WHERE scenario_id LIKE ?
            """,
            (f"{sweep_name}_%",),
        ).fetchone()

        return {
            "sweep_name": sweep_name,
            "total_scenarios": result[0] or 0,
            "completed": result[1] or 0,
            "failed": result[2] or 0,
            "running": result[3] or 0,
            "avg_customers": result[4],
            "avg_orders": result[5],
            "avg_revenue": result[6],
            "avg_conversion": result[7],
            "min_conversion": result[8],
            "max_conversion": result[9],
            "avg_fill_rate": result[10],
            "avg_churn_rate": result[11],
        }

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


class SweepRunner:
    """Executes parameter sweep experiments for all workflow types."""

    def __init__(
        self,
        sweep_name: str,
        sweep_type: str = "grid",
        n_samples: int = 36,
        base_seed: int = 42,
    ):
        """
        Initialize the sweep runner.

        Args:
            sweep_name: Name of the sweep configuration to use
            sweep_type: "grid" for exhaustive, "random" for random sampling
            n_samples: Number of samples for random search
            base_seed: Base random seed
        """
        self.sweep_config = get_sweep_config(sweep_name)
        self.sweep_name = sweep_name
        self.sweep_type = sweep_type
        self.n_samples = n_samples
        self.base_seed = base_seed
        self.tracker = ScenarioTracker()
        self.completed_scenarios: List[str] = []

        # Determine workflow type from sweep name
        self.workflow_type = SWEEP_WORKFLOW_MAP.get(sweep_name, "omnichannel")

        logger.info(
            f"SweepRunner initialized: {sweep_name} sweep ({self.workflow_type}), "
            f"{sweep_type} search, seed={base_seed}"
        )

    def run(self) -> List[str]:
        """
        Execute all scenarios in the sweep.

        Returns:
            List of completed scenario IDs
        """
        generator = ConfigGenerator(self.sweep_config, self.base_seed)
        scenarios = generator.generate_scenarios(self.sweep_type, self.n_samples)

        logger.info(f"Starting sweep with {len(scenarios)} scenarios")
        print(f"\n{'='*60}")
        print(f"PARAMETER SWEEP: {self.sweep_config.name.upper()}")
        print(f"Workflow: {self.workflow_type}")
        print(f"{'='*60}")
        print(f"Total scenarios: {len(scenarios)}")
        print(f"Sweep type: {self.sweep_type}")
        print(f"Duration per scenario: {self.sweep_config.base_duration_hours}h")
        print(f"{'='*60}\n")

        for idx, scenario in enumerate(scenarios):
            scenario_id = scenario["scenario_id"]
            print(f"\n[{idx + 1}/{len(scenarios)}] Running {scenario_id}...")

            try:
                self._run_single_scenario(scenario)
                self.completed_scenarios.append(scenario_id)
                print(f"  Completed {scenario_id}")
            except Exception as e:
                logger.error(f"Scenario {scenario_id} failed: {e}", exc_info=True)
                self.tracker.fail_scenario(scenario_id, str(e))
                print(f"  FAILED: {e}")

        summary = self.tracker.get_sweep_summary(self.sweep_config.name)
        self._print_summary(summary)

        return self.completed_scenarios

    def _run_single_scenario(self, scenario: Dict[str, Any]) -> None:
        """Execute a single scenario based on workflow type."""
        scenario_id = scenario["scenario_id"]
        scenario_name = scenario["scenario_name"]
        duration_hours = scenario["duration_hours"]
        seed = scenario["random_seed"]
        params = scenario["parameters"]

        # Set random seeds
        random.seed(seed)
        np.random.seed(seed)

        # Track scenario start
        self.tracker.start_scenario(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            workflow_type=self.workflow_type,
            duration_hours=duration_hours,
            random_seed=seed,
            config=scenario,
        )

        # Create simulation config
        config = SimulationConfig()
        config.simulation_duration_hours = duration_hours
        config.random_seed = seed

        # Create SimPy environment
        env = simpy.Environment()

        # Create shared resources
        resources = ResourceRegistry(env, config.resources)

        # Create persistence manager
        persistence = PersistenceManager(
            config.database,
            enable_eventhub=False,
        )

        # Create metrics collector
        metrics = MetricsCollector(f"{self.workflow_type}_{scenario_id}")

        # Route to appropriate workflow runner
        if self.workflow_type == "omnichannel":
            result_metrics = self._run_omnichannel_scenario(
                env, config, resources, persistence, metrics, scenario_id, params, duration_hours
            )
        elif self.workflow_type == "inventory":
            result_metrics = self._run_inventory_scenario(
                env, config, resources, persistence, metrics, scenario_id, params, duration_hours
            )
        elif self.workflow_type == "engagement":
            result_metrics = self._run_engagement_scenario(
                env, config, resources, persistence, metrics, scenario_id, params, duration_hours
            )
        else:
            raise ValueError(f"Unknown workflow type: {self.workflow_type}")

        # Track scenario completion
        self.tracker.complete_scenario(
            scenario_id=scenario_id,
            workflow_type=self.workflow_type,
            metrics=result_metrics,
        )

        # Cleanup
        persistence.close()

    def _run_omnichannel_scenario(
        self,
        env: simpy.Environment,
        config: SimulationConfig,
        resources: ResourceRegistry,
        persistence: PersistenceManager,
        metrics: MetricsCollector,
        scenario_id: str,
        params: Dict[str, Any],
        duration_hours: float,
    ) -> Dict[str, Any]:
        """Run omnichannel purchase workflow scenario."""
        # Apply parameter overrides
        self._apply_overrides(config, params)

        workflow = OmnichannelPurchaseWorkflow(
            env, config, resources, persistence, metrics
        )
        workflow.scenario_id = scenario_id

        # Load data
        products = self._load_product_catalog(persistence)
        if products:
            workflow.load_product_catalog(products)
        workflow.load_real_customers()

        # Load inventory into resource registry so stock can be reserved
        try:
            conn = persistence.postgres._conn
            inv_rows = conn.execute(
                "SELECT sku, location_id, quantity_on_hand, reorder_point FROM inventory"
            ).fetchall()
            for sku, location, qty, rop in inv_rows:
                resources.inventory.register_sku(sku, location, qty, rop)
            logger.info(f"Registered {len(inv_rows)} inventory items for omnichannel scenario")
        except Exception as e:
            logger.warning(f"Could not load inventory for omnichannel scenario: {e}")

        # Start processes
        env.process(workflow.online_arrival_process())
        env.process(workflow.in_store_arrival_process())
        env.process(workflow.bopis_arrival_process())

        # Run (time unit: minutes)
        env.run(until=duration_hours * 60)

        # Persist metrics
        metrics.persist_to_db(scenario_id, persistence)

        final = metrics.calculate_metrics()
        return {
            "total_customers": final.total_customers,
            "total_orders": final.total_orders,
            "total_revenue": final.total_revenue,
            "conversion_rate": final.conversion_rate,
        }

    def _run_inventory_scenario(
        self,
        env: simpy.Environment,
        config: SimulationConfig,
        resources: ResourceRegistry,
        persistence: PersistenceManager,
        metrics: MetricsCollector,
        scenario_id: str,
        params: Dict[str, Any],
        duration_hours: float,
    ) -> Dict[str, Any]:
        """Run inventory replenishment workflow scenario."""
        # Apply parameter overrides to config (inventory section + distributions)
        self._apply_overrides(config, params)

        workflow = InventoryReplenishmentWorkflow(
            env, config, resources, persistence, metrics
        )
        workflow.scenario_id = scenario_id

        # Load real products
        workflow.load_real_products()

        # Load inventory into resource registry so demand can deplete stock
        try:
            inv_rows = persistence.postgres.execute_query(
                "SELECT sku, location_id, quantity_on_hand, reorder_point FROM inventory",
                fetch=True,
            )
            for sku, location, qty, rop in (inv_rows or []):
                resources.inventory.register_sku(sku, location, qty, rop)
            logger.info(f"Registered {len(inv_rows or [])} inventory items for scenario")
        except Exception as e:
            logger.warning(f"Could not load inventory for scenario: {e}")

        # Load suppliers and policies
        suppliers, policies = self._load_suppliers_and_policies(persistence)

        # Populate supplier registry using config values
        ic = config.inventory
        supplier_reliability = params.get("supplier_reliability", 0.95)
        mean_lead_time = params.get("mean_lead_time_days", ic.default_lead_time_days)
        lead_time_var = params.get("lead_time_variability", ic.lead_time_std_factor)

        for supplier_id, name, _, _, min_qty in suppliers:
            workflow.suppliers[supplier_id] = {
                "supplier_id": supplier_id,
                "name": name,
                "mean_lead_time": mean_lead_time,
                "lead_time_std": mean_lead_time * lead_time_var,
                "reliability": supplier_reliability,
                "min_order_qty": min_qty,
                "total_orders": 0,
                "on_time_deliveries": 0,
                "total_lead_time": 0.0,
            }

        # Apply policy parameter overrides
        rop_multiplier = params.get("reorder_point_multiplier", 1.0)
        ss_days = params.get("safety_stock_days", 7)
        oq_multiplier = params.get("order_quantity_multiplier", 1.0)

        for sku, location, supplier_id, rop, order_qty, safety_stock, lead_time in policies:
            workflow.configure_replenishment_policy(
                sku,
                location,
                int(rop * rop_multiplier),
                int(order_qty * oq_multiplier),
                ss_days,
                supplier_id,
                float(lead_time),
                persist=False,  # Don't overwrite seed data with multiplied values
            )

        # Start monitoring with demand from config
        demand_multiplier = params.get("mean_daily_demand_multiplier", 1.0)
        demand_variability = params.get("demand_variability", 0.3)
        # Higher demand_variability → wider demand quantity range per transaction
        config.inventory.demand_qty_max = max(
            config.inventory.demand_qty_min + 1,
            int(config.inventory.demand_qty_max * (0.5 + demand_variability * 2)),
        )
        for sku, location, *_ in policies:
            base_demand = random.uniform(ic.daily_demand_min, ic.daily_demand_max)
            workflow.start_monitoring(sku, location, base_demand * demand_multiplier)

        # Run (time unit: hours)
        env.run(until=duration_hours)

        # Persist ML training data
        workflow.persist_ml_data(scenario_id)

        # Calculate metrics
        stockouts = metrics.custom_metrics.get("stockouts", 0)
        units_received = metrics.custom_metrics.get("units_received", 0)
        lost_sales = metrics.custom_metrics.get("lost_sales_units", 0)

        fill_rate = 100.0
        if units_received + lost_sales > 0:
            fill_rate = (units_received / (units_received + lost_sales)) * 100

        avg_lead_time = 0.0
        for supplier in workflow.suppliers.values():
            if supplier["total_orders"] > 0:
                avg_lead_time = supplier["total_lead_time"] / supplier["total_orders"]
                break

        return {
            "stockout_count": int(stockouts),
            "fill_rate": fill_rate,
            "avg_lead_time": avg_lead_time,
        }

    def _run_engagement_scenario(
        self,
        env: simpy.Environment,
        config: SimulationConfig,
        resources: ResourceRegistry,
        persistence: PersistenceManager,
        metrics: MetricsCollector,
        scenario_id: str,
        params: Dict[str, Any],
        duration_hours: float,
    ) -> Dict[str, Any]:
        """Run customer engagement workflow scenario."""
        # Apply parameter overrides to config (engagement section)
        self._apply_overrides(config, params)

        workflow = CustomerEngagementWorkflow(
            env, config, resources, persistence, metrics
        )
        workflow.scenario_id = scenario_id

        # Load real data
        workflow.load_real_data()

        # Load customers
        customers = self._load_customers(persistence, config.customer_limit)

        for customer_id, name, email, join_date in customers:
            workflow.register_customer(customer_id, email, name, join_date)
            workflow.start_customer_engagement(customer_id)

        # Load purchase history
        workflow.load_purchase_history_from_db()
        workflow.persist_customer_stats()

        # Load products
        products = self._load_product_catalog(persistence)
        if products:
            workflow.load_product_catalog(products)
            workflow.populate_recommendations_cache()

        # Start campaigns (reads response rates etc. from config.engagement)
        workflow.start_campaigns()
        workflow.start_segmentation_updates()

        # Run (time unit: hours)
        env.run(until=duration_hours)

        # Persist ML training data
        workflow.persist_ml_data(scenario_id)

        # Calculate metrics
        total_customers = len(workflow.customers)
        churned = sum(1 for c in workflow.customers.values()
                     if c["activity_state"].value == "churned")
        churn_rate = (churned / total_customers * 100) if total_customers > 0 else 0

        campaigns_sent = metrics.custom_metrics.get("campaigns_sent", 0)
        clicks = metrics.custom_metrics.get("clicks", 0)
        response_rate = (clicks / campaigns_sent * 100) if campaigns_sent > 0 else 0

        total_spend = sum(c["total_spend"] for c in workflow.customers.values())
        avg_clv = total_spend / total_customers if total_customers > 0 else 0

        return {
            "total_customers": total_customers,
            "churn_rate": churn_rate,
            "campaign_response_rate": response_rate,
            "avg_clv": avg_clv,
        }

    # Parameters consumed directly by scenario methods (not via config fields)
    _SCENARIO_PARAMS = {
        "reorder_point_multiplier",
        "safety_stock_days",
        "order_quantity_multiplier",
        "mean_daily_demand_multiplier",
        "supplier_reliability",
        "mean_lead_time_days",
        "lead_time_variability",
        "demand_variability",
    }

    def _apply_overrides(
        self, config: SimulationConfig, params: Dict[str, Any]
    ) -> None:
        """Apply parameter overrides to the appropriate config section.

        Searches distributions, omnichannel, inventory, engagement, resources,
        and sla sections for matching field names.
        """
        for param_name, value in params.items():
            if param_name.startswith("_") or param_name in self._SCENARIO_PARAMS:
                continue
            applied = False
            for section_name in [
                "distributions", "omnichannel", "inventory",
                "engagement", "resources", "sla",
            ]:
                section = getattr(config, section_name, None)
                if section and hasattr(section, param_name):
                    setattr(section, param_name, value)
                    logger.debug(f"Set {section_name}.{param_name} = {value}")
                    applied = True
                    break
            if not applied:
                logger.warning(f"Unknown sweep parameter: {param_name}")

    def _load_product_catalog(self, persistence: PersistenceManager) -> List[tuple]:
        """Load product catalog from database."""
        try:
            conn = persistence.postgres._conn
            result = conn.execute(
                "SELECT product_id, sku, price, category FROM products"
            ).fetchall()
            return result
        except Exception as e:
            logger.warning(f"Could not load product catalog: {e}")
            return []

    def _load_suppliers_and_policies(
        self, persistence: PersistenceManager
    ) -> tuple:
        """Load suppliers and replenishment policies."""
        try:
            conn = persistence.postgres._conn

            suppliers = conn.execute(
                "SELECT supplier_id, name, mean_lead_time_days, reliability, min_order_qty FROM suppliers"
            ).fetchall()

            policies = conn.execute(
                """SELECT sku, location_id, supplier_id, reorder_point, order_quantity,
                         safety_stock, lead_time_days FROM replenishment_policy"""
            ).fetchall()

            return suppliers, policies
        except Exception as e:
            logger.warning(f"Could not load suppliers/policies: {e}")
            return [], []

    def _load_customers(
        self, persistence: PersistenceManager, limit: int = 100
    ) -> List[tuple]:
        """Load customers from database."""
        try:
            conn = persistence.postgres._conn
            result = conn.execute(
                "SELECT customer_id, name, email, created_at FROM customers LIMIT ?",
                (limit,),
            ).fetchall()
            return result
        except Exception as e:
            logger.warning(f"Could not load customers: {e}")
            return []

    def _print_summary(self, summary: Dict[str, Any]) -> None:
        """Print sweep summary statistics."""
        print(f"\n{'='*60}")
        print(f"SWEEP SUMMARY: {summary['sweep_name'].upper()}")
        print(f"Workflow: {self.workflow_type}")
        print(f"{'='*60}")
        print(f"Total scenarios:    {summary['total_scenarios']}")
        print(f"  Completed:        {summary['completed']}")
        print(f"  Failed:           {summary['failed']}")
        print(f"  Running:          {summary['running']}")

        if self.workflow_type == "omnichannel":
            if summary["avg_conversion"] is not None:
                print(f"\nConversion Rate:")
                print(f"  Average:          {summary['avg_conversion']:.1f}%")
                print(f"  Min:              {summary['min_conversion']:.1f}%")
                print(f"  Max:              {summary['max_conversion']:.1f}%")
            if summary["avg_revenue"] is not None:
                print(f"\nRevenue:")
                print(f"  Average:          ${summary['avg_revenue']:,.2f}")

        elif self.workflow_type == "inventory":
            if summary["avg_fill_rate"] is not None:
                print(f"\nFill Rate:")
                print(f"  Average:          {summary['avg_fill_rate']:.1f}%")

        elif self.workflow_type == "engagement":
            if summary["avg_churn_rate"] is not None:
                print(f"\nChurn Rate:")
                print(f"  Average:          {summary['avg_churn_rate']:.1f}%")

        print(f"{'='*60}\n")

    def close(self) -> None:
        """Clean up resources."""
        self.tracker.close()


def run_sweep(
    sweep_name: str,
    sweep_type: str = "grid",
    n_samples: int = 36,
    base_seed: int = 42,
) -> List[str]:
    """
    Convenience function to run a parameter sweep.

    Args:
        sweep_name: Name of sweep configuration
        sweep_type: "grid" or "random"
        n_samples: Number of samples for random search
        base_seed: Base random seed

    Returns:
        List of completed scenario IDs
    """
    runner = SweepRunner(sweep_name, sweep_type, n_samples, base_seed)
    try:
        return runner.run()
    finally:
        runner.close()
