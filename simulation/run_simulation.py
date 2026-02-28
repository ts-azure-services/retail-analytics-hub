"""
Simulation orchestrator and runner.

Main entry point for running retail simulation workflows.
Supports:
- Single workflow execution
- Multi-workflow coordination
- Configurable parameters
- Metrics collection and reporting
"""

import simpy
import logging
import sys
import argparse
import json
from datetime import datetime
from typing import Optional, List
from decimal import Decimal

from simulation.shared.config import SimulationConfig
from simulation.shared.resources import ResourceRegistry
from simulation.shared.persistence import PersistenceManager, USE_LOCAL_DB
from simulation.shared.metrics import MetricsCollector
from simulation.workflows.omnichannel_purchase import OmnichannelPurchaseWorkflow
from simulation.workflows.inventory_replenishment import InventoryReplenishmentWorkflow
from simulation.workflows.customer_engagement import CustomerEngagementWorkflow


class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder for Decimal types"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


class ErrorColorFormatter(logging.Formatter):
    """Custom formatter that colors only ERROR and CRITICAL messages red"""
    
    RED = '\033[0;31m'
    BOLD_RED = '\033[1;31m'
    RESET = '\033[0m'
    
    def format(self, record):
        formatted = super().format(record)
        if record.levelno >= logging.ERROR:
            color = self.BOLD_RED if record.levelno >= logging.CRITICAL else self.RED
            return f"{color}{formatted}{self.RESET}"
        return formatted


# Configure logging
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(ErrorColorFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

file_handler = logging.FileHandler(f'simulation_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        console_handler,
        file_handler
    ]
)

logger = logging.getLogger(__name__)


def run_sweep_mode(args) -> int:
    """
    Run parameter sweep mode.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    from simulation.sweep import SweepRunner

    print("=" * 80)
    print("PARAMETER SWEEP MODE")
    print("=" * 80)
    print(f"Sweep: {args.sweep}")
    print(f"Type: {args.sweep_type}")
    if args.sweep_type == 'random':
        print(f"Samples: {args.sweep_samples}")
    print(f"Random Seed: {args.seed}")
    print("=" * 80)

    try:
        runner = SweepRunner(
            sweep_name=args.sweep,
            sweep_type=args.sweep_type,
            n_samples=args.sweep_samples,
            base_seed=args.seed,
        )

        completed_scenarios = runner.run()

        print(f"\nCompleted {len(completed_scenarios)} scenarios")
        print("=" * 80)
        print("SWEEP COMPLETE")
        print("=" * 80)

        runner.close()
        return 0

    except KeyboardInterrupt:
        logger.info("Sweep interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"Sweep failed: {e}", exc_info=True)
        return 1


class SimulationOrchestrator:
    """Orchestrates simulation workflows"""
    
    def __init__(self, config: SimulationConfig):
        self.config = config
        self.env = None
        self.resources = None
        self.persistence = None
        self.metrics_collectors = {}
        self.workflows = {}
        
        logger.info("Simulation orchestrator initialized")
    
    def setup(self):
        """Setup simulation environment and shared components"""
        logger.info("Setting up simulation environment...")
        
        # Validate configuration
        if not self.config.validate():
            logger.error("Configuration validation failed")
            raise ValueError("Invalid configuration")
        
        # Create SimPy environment
        self.env = simpy.Environment()
        
        # Create shared resources
        self.resources = ResourceRegistry(self.env, self.config.resources)
        
        # Create persistence manager
        self.persistence = PersistenceManager(
            self.config.database,
            enable_eventhub=self.config.enable_event_streaming
        )
        
        logger.info("Simulation environment ready")
    
    def _get_db_connection(self):
        """Return a database connection – DuckDB when local, psycopg otherwise."""
        if USE_LOCAL_DB:
            import duckdb
            from simulation.shared.local_backend import POSTGRES_DB_PATH
            return duckdb.connect(POSTGRES_DB_PATH)
        else:
            import psycopg
            return psycopg.connect(
                host=self.config.database.postgres_host,
                dbname=self.config.database.postgres_database,
                user=self.config.database.postgres_user,
                password=self.config.database.postgres_password,
                port=5432,
                sslmode='require',
                connect_timeout=10,
            )

    def load_inventory_from_db(self):
        """Load initial inventory from database"""
        logger.info("Loading inventory from database...")
        
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            # Load inventory
            cursor.execute("SELECT sku, location_id, quantity_on_hand, reorder_point FROM inventory")
            inventory_rows = cursor.fetchall()
            
            for sku, location, quantity, reorder_point in inventory_rows:
                self.resources.inventory.register_sku(sku, location, quantity, reorder_point)
            
            logger.info(f"Loaded {len(inventory_rows)} inventory records")
            
            cursor.close()
            conn.close()
            
        except Exception as e:
            logger.warning(f"Could not load inventory from database: {e}")
            logger.info("Simulation will proceed with empty inventory")
    
    def load_product_catalog(self):
        """Load product catalog from database"""
        logger.info("Loading product catalog...")
        
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            # Load products
            cursor.execute("SELECT product_id, sku, price, category FROM products")
            products = cursor.fetchall()
            
            logger.info(f"Loaded {len(products)} products")
            
            cursor.close()
            conn.close()
            
            return products
            
        except Exception as e:
            logger.error(f"Failed to load product catalog: {e}")
            return []
    
    def load_suppliers_and_policies(self):
        """Load suppliers and replenishment policies from database"""
        logger.info("Loading suppliers and replenishment policies...")
        
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            # Load suppliers
            cursor.execute(
                "SELECT supplier_id, name, mean_lead_time_days, reliability, min_order_qty FROM suppliers"
            )
            suppliers = cursor.fetchall()
            
            # Load replenishment policies
            cursor.execute(
                """SELECT sku, location_id, supplier_id, reorder_point, order_quantity, 
                         safety_stock, lead_time_days FROM replenishment_policy"""
            )
            policies = cursor.fetchall()
            
            logger.info(f"Loaded {len(suppliers)} suppliers and {len(policies)} replenishment policies")
            
            cursor.close()
            conn.close()
            
            return suppliers, policies
            
        except Exception as e:
            logger.error(f"Failed to load suppliers and policies: {e}")
            return [], []
    
    def load_customers(self):
        """Load customers from database"""
        logger.info("Loading customers...")
        
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            # Load customers (use configurable limit)
            # DuckDB uses ? placeholders; psycopg uses %s — handled by helper
            if USE_LOCAL_DB:
                cursor.execute(
                    "SELECT customer_id, name, email, created_at FROM customers LIMIT ?",
                    (self.config.customer_limit,)
                )
            else:
                cursor.execute(
                    "SELECT customer_id, name, email, created_at FROM customers LIMIT %s",
                    (self.config.customer_limit,)
                )
            customers = cursor.fetchall()
            
            logger.info(f"Loaded {len(customers)} customers (limit: {self.config.customer_limit})")
            
            cursor.close()
            conn.close()
            
            return customers
            
        except Exception as e:
            logger.error(f"Failed to load customers: {e}")
            return []
    
    def register_workflow(self, workflow_name: str, workflow_class):
        """Register a workflow for execution"""
        metrics = MetricsCollector(workflow_name)
        self.metrics_collectors[workflow_name] = metrics
        
        # Instantiate workflow
        workflow = workflow_class(
            self.env,
            self.config,
            self.resources,
            self.persistence,
            metrics
        )
        
        self.workflows[workflow_name] = workflow
        logger.info(f"Registered workflow: {workflow_name}")
        
        return workflow
    
    def run_omnichannel_workflow(self):
        """Run omnichannel purchase workflow"""
        logger.info("Starting Omnichannel Purchase Workflow...")
        
        # Register workflow
        workflow = self.register_workflow("omnichannel_purchase", OmnichannelPurchaseWorkflow)
        
        # Load product catalog
        products = self.load_product_catalog()
        if products:
            workflow.load_product_catalog(products)
        else:
            logger.warning("No products loaded - simulation may not generate orders")
        
        # Load real customer IDs from CosmosDB
        logger.info("Loading real customer IDs from CosmosDB...")
        workflow.load_real_customers()
        
        # Start arrival processes
        self.env.process(workflow.online_arrival_process())
        self.env.process(workflow.in_store_arrival_process())
        self.env.process(workflow.bopis_arrival_process())

        # Run simulation (time unit: minutes for omnichannel workflow)
        simulation_duration_hours = self.config.simulation_duration_hours
        simulation_duration_minutes = simulation_duration_hours * 60
        logger.info(f"Running simulation for {simulation_duration_hours} hours...")

        self.env.run(until=simulation_duration_minutes)
        
        logger.info("Simulation completed")
    
    def run_inventory_replenishment_workflow(self):
        """Run inventory replenishment workflow"""
        logger.info("Starting Inventory Replenishment Workflow...")
        
        # Register workflow
        workflow = self.register_workflow("inventory_replenishment", InventoryReplenishmentWorkflow)
        
        # Load real products and suppliers from PostgreSQL for data integrity
        logger.info("Loading real products and suppliers from PostgreSQL...")
        workflow.load_real_products()
        
        # Load suppliers and policies (suppliers already loaded, just need policies)
        suppliers, policies = self.load_suppliers_and_policies()
        
        if not suppliers:
            logger.warning("No suppliers loaded - workflow may not function properly")
            return
        
        # Populate supplier registry in memory (skip database writes since already seeded)
        logger.info(f"Populating supplier registry for {len(suppliers)} suppliers...")
        for supplier_id, name, lead_time, reliability, min_qty in suppliers:
            # Use a reasonable std deviation (20% of mean)
            lead_time_std = float(lead_time) * self.config.inventory.lead_time_std_factor
            # Directly populate in-memory registry without database write
            workflow.suppliers[supplier_id] = {
                'supplier_id': supplier_id,
                'name': name,
                'mean_lead_time': float(lead_time),
                'lead_time_std': lead_time_std,
                'reliability': float(reliability),
                'min_order_qty': min_qty,
                'total_orders': 0,
                'on_time_deliveries': 0,
                'total_lead_time': 0.0
            }
        
        # Configure replenishment policies
        for sku, location, supplier_id, rop, order_qty, safety_stock, lead_time in policies:
            workflow.configure_replenishment_policy(
                sku, location, rop, order_qty, safety_stock, 
                supplier_id, float(lead_time)
            )
        
        # Load products for demand simulation
        products = self.load_product_catalog()
        product_skus = [p[1] for p in products] if products else []
        
        # Start monitoring processes for each SKU/location
        # Use historical data or defaults for mean daily demand
        for sku, location, *_ in policies:
            # Default: 5-20 units per day demand (can be refined with historical data)
            import random
            mean_daily_demand = random.uniform(self.config.inventory.daily_demand_min, self.config.inventory.daily_demand_max)
            workflow.start_monitoring(sku, location, mean_daily_demand)
        
        # Run simulation (time unit: hours)
        simulation_duration_hours = self.config.simulation_duration_hours
        logger.info(f"Running simulation for {simulation_duration_hours} hours...")
        
        self.env.run(until=simulation_duration_hours)
        
        logger.info("Simulation completed")

        # Print inventory-specific summary
        workflow.print_inventory_summary()
    
    def run_customer_engagement_workflow(self):
        """Run customer engagement workflow"""
        logger.info("Starting Customer Engagement Workflow...")
        
        # Register workflow
        workflow = self.register_workflow("customer_engagement", CustomerEngagementWorkflow)
        
        # Load real data from databases (customers from CosmosDB, products from PostgreSQL)
        logger.info("Loading real customers and products for engagement workflow...")
        workflow.load_real_data()
        
        # Load customers
        customers = self.load_customers()
        
        if not customers:
            logger.warning("No customers loaded - workflow may not function properly")
            return
        
        # Register customers in workflow
        for customer_id, name, email, join_date in customers:
            workflow.register_customer(customer_id, email, name, join_date)
            workflow.start_customer_engagement(customer_id)
        
        logger.info(f"Registered {len(customers)} customers for engagement")
        
        # Load purchase history from PostgreSQL (seeded in 'make seed-all-with-history')
        workflow.load_purchase_history_from_db()
        
        # Load products for recommendations
        products = self.load_product_catalog()
        if products:
            workflow.load_product_catalog(products)
        
        # Start campaigns and segmentation
        workflow.start_campaigns()
        workflow.start_segmentation_updates()
        
        # Run simulation (time unit: hours)
        simulation_duration_hours = self.config.simulation_duration_hours
        logger.info(f"Running simulation for {simulation_duration_hours} hours...")
        
        self.env.run(until=simulation_duration_hours)
        
        logger.info("Simulation completed")
        
        # Print engagement-specific summary
        workflow.print_engagement_summary()
    
    def run_all_workflows(self):
        """Run all available workflows (for multi-workflow simulation)"""
        logger.info("Starting multi-workflow simulation...")
        
        # Register all three workflows
        omni_workflow = self.register_workflow("omnichannel_purchase", OmnichannelPurchaseWorkflow)
        inv_workflow = self.register_workflow("inventory_replenishment", InventoryReplenishmentWorkflow)
        engage_workflow = self.register_workflow("customer_engagement", CustomerEngagementWorkflow)
        
        # Load real data for engagement workflow
        logger.info("Loading real customers and products for engagement workflow...")
        engage_workflow.load_real_data()
        
        # Load product catalog
        products = self.load_product_catalog()
        if products:
            omni_workflow.load_product_catalog(products)
            engage_workflow.load_product_catalog(products)
        else:
            logger.warning("No products loaded - simulation may not generate orders")
        
        # Load customers for engagement
        customers = self.load_customers()
        if customers:
            for customer_id, name, email, join_date in customers:
                engage_workflow.register_customer(customer_id, email, name, join_date)
                engage_workflow.start_customer_engagement(customer_id)
            logger.info(f"Registered {len(customers)} customers for engagement")
            
            # Load purchase history from PostgreSQL (seeded in 'make seed-all-with-history')
            engage_workflow.load_purchase_history_from_db()
            
            # Start engagement campaigns
            engage_workflow.start_campaigns()
            engage_workflow.start_segmentation_updates()
        
        # Load suppliers and policies for inventory workflow
        logger.info("Loading suppliers and replenishment policies for inventory workflow...")
        inv_workflow.load_real_products()
        
        suppliers, policies = self.load_suppliers_and_policies()
        
        if suppliers:
            # Populate supplier registry directly (skip database writes)
            for supplier_id, name, lead_time, reliability, min_qty in suppliers:
                lead_time_std = float(lead_time) * self.config.inventory.lead_time_std_factor
                inv_workflow.suppliers[supplier_id] = {
                    'supplier_id': supplier_id,
                    'name': name,
                    'mean_lead_time': float(lead_time),
                    'lead_time_std': lead_time_std,
                    'reliability': float(reliability),
                    'min_order_qty': min_qty,
                    'total_orders': 0,
                    'on_time_deliveries': 0,
                    'total_lead_time': 0.0
                }
            logger.info(f"✓ Populated supplier registry with {len(suppliers)} suppliers")
            
            # Configure replenishment policies
            for sku, location, supplier_id, rop, order_qty, safety_stock, lead_time in policies:
                inv_workflow.configure_replenishment_policy(
                    sku, location, rop, order_qty, safety_stock, 
                    supplier_id, float(lead_time)
                )
            
            # Start monitoring processes
            for sku, location, *_ in policies:
                import random
                mean_daily_demand = random.uniform(self.config.inventory.daily_demand_min, self.config.inventory.daily_demand_max)
                inv_workflow.start_monitoring(sku, location, mean_daily_demand)
        
        # Start omnichannel arrival processes
        self.env.process(omni_workflow.online_arrival_process())
        self.env.process(omni_workflow.in_store_arrival_process())
        self.env.process(omni_workflow.bopis_arrival_process())
        
        # Run simulation (time unit: hours)
        simulation_duration_hours = self.config.simulation_duration_hours
        logger.info(f"Running simulation for {simulation_duration_hours} hours...")
        
        self.env.run(until=simulation_duration_hours)
        
        # Print supplier performance
        if suppliers:
            logger.info("\nSupplier Performance Summary:")
            for supplier_id, *_ in suppliers:
                perf = inv_workflow.get_supplier_performance(supplier_id)
                if perf:
                    logger.info(f"  {perf['name']}: {perf['total_orders']} orders, "
                              f"{perf['on_time_rate']:.1%} on-time, "
                              f"avg lead time {perf['avg_lead_time']:.1f} days")
        
        logger.info("Simulation completed")
    
    def print_results(self):
        """Print simulation results"""
        logger.info("Generating simulation results...")
        
        for workflow_name, metrics in self.metrics_collectors.items():
            print(f"\n{'='*80}")
            print(f"WORKFLOW: {workflow_name}")
            print(f"{'='*80}")
            metrics.print_summary()
    
    def export_results(self, output_file: str):
        """Export results to JSON file"""
        results = {
            'simulation_config': {
                'duration_hours': self.config.simulation_duration_hours,
                'random_seed': self.config.random_seed,
                'timestamp': datetime.now().isoformat()
            },
            'workflows': {}
        }
        
        for workflow_name, metrics in self.metrics_collectors.items():
            results['workflows'][workflow_name] = metrics.export_to_dict()
        
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, cls=DecimalEncoder)
        
        logger.info(f"Results exported to {output_file}")
    
    def cleanup(self):
        """Cleanup resources"""
        logger.info("Cleaning up resources...")
        if self.persistence:
            self.persistence.close()
        logger.info("Cleanup complete")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Retail Simulation Runner')
    parser.add_argument(
        '--workflow',
        choices=['omnichannel', 'inventory', 'engagement', 'all'],
        default='omnichannel',
        help='Workflow to run: omnichannel, inventory, engagement, or all (default: omnichannel)'
    )
    parser.add_argument(
        '--duration',
        type=float,
        default=24.0,
        help='Simulation duration in hours (default: 24)'
    )
    parser.add_argument(
        '--seed',
        type=int,
        default=42,
        help='Random seed for reproducibility (default: 42)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Output file for results (JSON format)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    parser.add_argument(
        '--sweep',
        type=str,
        choices=[
            # Omnichannel sweeps
            'conversion', 'demand', 'fulfillment',
            # Inventory sweeps
            'inventory_supply', 'inventory_policy', 'inventory_demand',
            # Engagement sweeps
            'engagement_campaign', 'engagement_retention', 'engagement_loyalty',
        ],
        default=None,
        help='Run parameter sweep (omnichannel: conversion/demand/fulfillment, '
             'inventory: inventory_supply/inventory_policy/inventory_demand, '
             'engagement: engagement_campaign/engagement_retention/engagement_loyalty)'
    )
    parser.add_argument(
        '--sweep-type',
        type=str,
        choices=['grid', 'random'],
        default='grid',
        help='Sweep type: grid (exhaustive) or random (default: grid)'
    )
    parser.add_argument(
        '--sweep-samples',
        type=int,
        default=36,
        help='Number of samples for random sweep (default: 36)'
    )

    args = parser.parse_args()

    # Configure logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Handle sweep mode
    if args.sweep:
        return run_sweep_mode(args)

    # Load configuration
    config = SimulationConfig()
    config.simulation_duration_hours = args.duration
    config.random_seed = args.seed

    # Set random seed
    import random
    import numpy as np
    random.seed(args.seed)
    np.random.seed(args.seed)

    print("=" * 80)
    print("RETAIL SIMULATION - OMNICHANNEL PURCHASE & FULFILLMENT")
    print("=" * 80)
    print(f"Workflow: {args.workflow}")
    print(f"Duration: {args.duration} hours")
    print(f"Random Seed: {args.seed}")
    print("=" * 80)
    
    # Create and run orchestrator
    orchestrator = SimulationOrchestrator(config)
    
    try:
        # Setup
        orchestrator.setup()
        orchestrator.load_inventory_from_db()
        
        # Run workflow
        if args.workflow == 'omnichannel':
            orchestrator.run_omnichannel_workflow()
        elif args.workflow == 'inventory':
            orchestrator.run_inventory_replenishment_workflow()
        elif args.workflow == 'engagement':
            orchestrator.run_customer_engagement_workflow()
        elif args.workflow == 'all':
            orchestrator.run_all_workflows()
        
        # Print results
        orchestrator.print_results()
        
        # Export if requested
        if args.output:
            orchestrator.export_results(args.output)
        
    except KeyboardInterrupt:
        logger.info("Simulation interrupted by user")
    except Exception as e:
        logger.error(f"Simulation failed: {e}", exc_info=True)
        return 1
    finally:
        orchestrator.cleanup()
    
    print("\n" + "=" * 80)
    print("SIMULATION COMPLETE")
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
