"""
Scenario tracker for parameter sweep experiments.

Tracks scenario metadata and results in the simulation_scenarios table.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import duckdb

from ..shared.local_backend import POSTGRES_DB_PATH

logger = logging.getLogger(__name__)


class ScenarioTracker:
    """Tracks scenario execution and results."""

    def __init__(self, db_path: str = POSTGRES_DB_PATH):
        """
        Initialize the scenario tracker.

        Args:
            db_path: Path to the DuckDB database file
        """
        self.db_path = db_path
        self._conn = None

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = duckdb.connect(self.db_path)
        return self._conn

    def start_scenario(
        self,
        scenario_id: str,
        scenario_name: str,
        duration_hours: float,
        random_seed: int,
        config: Dict[str, Any],
    ) -> None:
        """
        Record the start of a scenario execution.

        Args:
            scenario_id: Unique scenario identifier
            scenario_name: Human-readable scenario name
            duration_hours: Planned simulation duration
            random_seed: Random seed for reproducibility
            config: Full configuration dictionary
        """
        conn = self._get_connection()

        config_json = json.dumps(config)

        conn.execute(
            """
            INSERT INTO simulation_scenarios
                (scenario_id, scenario_name, run_timestamp, duration_hours,
                 random_seed, config_json, status)
            VALUES (?, ?, ?, ?, ?, ?, 'running')
            ON CONFLICT (scenario_id) DO UPDATE SET
                scenario_name = excluded.scenario_name,
                run_timestamp = excluded.run_timestamp,
                duration_hours = excluded.duration_hours,
                random_seed = excluded.random_seed,
                config_json = excluded.config_json,
                status = 'running'
            """,
            (
                scenario_id,
                scenario_name,
                datetime.now(),
                duration_hours,
                random_seed,
                config_json,
            ),
        )

        logger.info(f"Started tracking scenario: {scenario_id}")

    def complete_scenario(
        self,
        scenario_id: str,
        total_customers: int,
        total_orders: int,
        total_revenue: float,
        conversion_rate: float,
    ) -> None:
        """
        Record scenario completion with results.

        Args:
            scenario_id: Unique scenario identifier
            total_customers: Total number of customers in simulation
            total_orders: Total number of completed orders
            total_revenue: Total revenue generated
            conversion_rate: Conversion rate (0-100)
        """
        conn = self._get_connection()

        conn.execute(
            """
            UPDATE simulation_scenarios
            SET status = 'completed',
                total_customers = ?,
                total_orders = ?,
                total_revenue = ?,
                conversion_rate = ?
            WHERE scenario_id = ?
            """,
            (total_customers, total_orders, total_revenue, conversion_rate, scenario_id),
        )

        logger.info(
            f"Completed scenario {scenario_id}: "
            f"{total_customers} customers, {total_orders} orders, "
            f"${total_revenue:.2f} revenue, {conversion_rate:.1f}% conversion"
        )

    def fail_scenario(self, scenario_id: str, error_message: str) -> None:
        """
        Record scenario failure.

        Args:
            scenario_id: Unique scenario identifier
            error_message: Error description
        """
        conn = self._get_connection()

        # Store error in config_json
        conn.execute(
            """
            UPDATE simulation_scenarios
            SET status = 'failed',
                config_json = json_merge_patch(
                    config_json,
                    json_object('error', ?)
                )
            WHERE scenario_id = ?
            """,
            (error_message, scenario_id),
        )

        logger.error(f"Failed scenario {scenario_id}: {error_message}")

    def get_scenario(self, scenario_id: str) -> Optional[Dict[str, Any]]:
        """
        Get scenario details.

        Args:
            scenario_id: Unique scenario identifier

        Returns:
            Scenario data dictionary or None if not found
        """
        conn = self._get_connection()

        result = conn.execute(
            """
            SELECT scenario_id, scenario_name, run_timestamp, duration_hours,
                   random_seed, config_json, status, total_customers,
                   total_orders, total_revenue, conversion_rate
            FROM simulation_scenarios
            WHERE scenario_id = ?
            """,
            (scenario_id,),
        ).fetchone()

        if result is None:
            return None

        return {
            "scenario_id": result[0],
            "scenario_name": result[1],
            "run_timestamp": result[2],
            "duration_hours": result[3],
            "random_seed": result[4],
            "config_json": json.loads(result[5]) if result[5] else {},
            "status": result[6],
            "total_customers": result[7],
            "total_orders": result[8],
            "total_revenue": result[9],
            "conversion_rate": result[10],
        }

    def list_scenarios(
        self,
        sweep_name: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list:
        """
        List scenarios with optional filtering.

        Args:
            sweep_name: Filter by sweep name (prefix match)
            status: Filter by status ('running', 'completed', 'failed')

        Returns:
            List of scenario dictionaries
        """
        conn = self._get_connection()

        query = "SELECT * FROM simulation_scenarios WHERE 1=1"
        params = []

        if sweep_name:
            query += " AND scenario_id LIKE ?"
            params.append(f"{sweep_name}_%")

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY run_timestamp DESC"

        results = conn.execute(query, params).fetchall()
        columns = [
            "scenario_id", "scenario_name", "run_timestamp", "duration_hours",
            "random_seed", "config_json", "status", "total_customers",
            "total_orders", "total_revenue", "conversion_rate"
        ]

        return [dict(zip(columns, row)) for row in results]

    def get_sweep_summary(self, sweep_name: str) -> Dict[str, Any]:
        """
        Get summary statistics for a sweep.

        Args:
            sweep_name: Name of the sweep

        Returns:
            Summary statistics dictionary
        """
        conn = self._get_connection()

        result = conn.execute(
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
                MAX(conversion_rate) as max_conversion
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
        }

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
