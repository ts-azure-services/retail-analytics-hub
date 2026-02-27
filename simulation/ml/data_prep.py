"""
Data preparation for ML model training.

Extracts and transforms simulation data into formats suitable for training.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import duckdb
import pandas as pd

from ..shared.local_backend import POSTGRES_DB_PATH

logger = logging.getLogger(__name__)


class DataExtractor:
    """Extracts and prepares data for ML training."""

    def __init__(self, db_path: str = POSTGRES_DB_PATH):
        """
        Initialize the data extractor.

        Args:
            db_path: Path to the DuckDB database
        """
        self.db_path = db_path
        self._conn = None

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = duckdb.connect(self.db_path, read_only=True)
        return self._conn

    def get_conversion_dataset(
        self,
        scenario_ids: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Extract dataset for conversion prediction model.

        Features: channel, arrival_hour, day_of_week, browsing_duration,
                  basket_size, queue_wait_time
        Target: completed (bool)

        Args:
            scenario_ids: Optional list of scenario IDs to filter

        Returns:
            DataFrame with features and target
        """
        conn = self._get_connection()

        query = """
            SELECT
                channel,
                arrival_hour,
                day_of_week,
                browsing_duration,
                basket_size,
                queue_wait_time,
                completed
            FROM customer_journeys
            WHERE basket_size > 0
        """

        if scenario_ids:
            placeholders = ", ".join(["?" for _ in scenario_ids])
            query += f" AND scenario_id IN ({placeholders})"
            df = conn.execute(query, scenario_ids).df()
        else:
            df = conn.execute(query).df()

        logger.info(f"Extracted {len(df)} records for conversion model")
        return df

    def get_order_value_dataset(
        self,
        scenario_ids: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Extract dataset for order value prediction model.

        Features: channel, basket_size, arrival_hour, day_of_week
        Target: total_amount (float)

        Args:
            scenario_ids: Optional list of scenario IDs to filter

        Returns:
            DataFrame with features and target
        """
        conn = self._get_connection()

        query = """
            SELECT
                channel,
                basket_size,
                arrival_hour,
                day_of_week,
                browsing_duration,
                queue_wait_time,
                total_amount
            FROM customer_journeys
            WHERE completed = TRUE
              AND total_amount > 0
        """

        if scenario_ids:
            placeholders = ", ".join(["?" for _ in scenario_ids])
            query += f" AND scenario_id IN ({placeholders})"
            df = conn.execute(query, scenario_ids).df()
        else:
            df = conn.execute(query).df()

        logger.info(f"Extracted {len(df)} records for value model")
        return df

    def get_demand_forecast_dataset(
        self,
        scenario_ids: Optional[List[str]] = None,
        channel: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Extract dataset for demand forecasting (Prophet format).

        Returns data in Prophet-compatible format:
        - ds: datetime (synthesized from hour_of_day)
        - y: order_count (target)

        Args:
            scenario_ids: Optional list of scenario IDs to filter
            channel: Optional channel filter

        Returns:
            DataFrame with ds and y columns
        """
        conn = self._get_connection()

        query = """
            SELECT
                hour_of_day,
                day_of_week,
                channel,
                SUM(order_count) as y,
                SUM(arrival_count) as arrivals,
                SUM(revenue) as revenue
            FROM hourly_demand
            WHERE 1=1
        """

        params = []

        if scenario_ids:
            placeholders = ", ".join(["?" for _ in scenario_ids])
            query += f" AND scenario_id IN ({placeholders})"
            params.extend(scenario_ids)

        if channel:
            query += " AND channel = ?"
            params.append(channel)

        query += " GROUP BY hour_of_day, day_of_week, channel"

        if params:
            df = conn.execute(query, params).df()
        else:
            df = conn.execute(query).df()

        # Create synthetic datetime for Prophet
        # Use a reference date and add hours
        if len(df) > 0:
            df['ds'] = pd.to_datetime('2024-01-01') + \
                pd.to_timedelta(df['day_of_week'] * 24 + df['hour_of_day'], unit='h')

        logger.info(f"Extracted {len(df)} hourly records for demand forecast")
        return df

    def get_fulfillment_dataset(
        self,
        scenario_ids: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Extract dataset for fulfillment time prediction model.

        Features: channel, order_hour, day_of_week
        Target: fulfillment_duration (float)

        Args:
            scenario_ids: Optional list of scenario IDs to filter

        Returns:
            DataFrame with features and target
        """
        conn = self._get_connection()

        query = """
            SELECT
                channel,
                order_hour,
                day_of_week,
                fulfillment_duration
            FROM order_metrics
            WHERE fulfillment_duration IS NOT NULL
              AND fulfillment_duration > 0
        """

        if scenario_ids:
            placeholders = ", ".join(["?" for _ in scenario_ids])
            query += f" AND scenario_id IN ({placeholders})"
            df = conn.execute(query, scenario_ids).df()
        else:
            df = conn.execute(query).df()

        logger.info(f"Extracted {len(df)} records for fulfillment model")
        return df

    def get_scenario_list(self, status: str = "completed", workflow_type: Optional[str] = None) -> List[str]:
        """
        Get list of scenario IDs.

        Args:
            status: Filter by status (default: "completed")
            workflow_type: Optional filter by workflow type

        Returns:
            List of scenario IDs
        """
        conn = self._get_connection()

        query = "SELECT scenario_id FROM simulation_scenarios WHERE status = ?"
        params = [status]

        if workflow_type:
            query += " AND workflow_type = ?"
            params.append(workflow_type)

        result = conn.execute(query, params).fetchall()

        return [row[0] for row in result]

    # ===== INVENTORY WORKFLOW DATASETS =====

    def get_stockout_dataset(
        self,
        scenario_ids: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Extract dataset for stockout prediction model.

        Features: quantity_before, reorder_point, safety_stock, on_order_qty,
                  event_hour, day_of_week
        Target: stockout_occurred (bool)

        Args:
            scenario_ids: Optional list of scenario IDs to filter

        Returns:
            DataFrame with features and target
        """
        conn = self._get_connection()

        query = """
            SELECT
                quantity_before,
                reorder_point,
                safety_stock,
                on_order_qty,
                event_hour,
                day_of_week,
                stockout_occurred
            FROM inventory_events
            WHERE event_type IN ('SALE', 'demand_consumed')
        """

        if scenario_ids:
            placeholders = ", ".join(["?" for _ in scenario_ids])
            query += f" AND scenario_id IN ({placeholders})"
            df = conn.execute(query, scenario_ids).df()
        else:
            df = conn.execute(query).df()

        logger.info(f"Extracted {len(df)} records for stockout model")
        return df

    def get_lead_time_dataset(
        self,
        scenario_ids: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Extract dataset for lead time prediction model.

        Features: supplier_id, order_quantity, day_of_week (from order_time)
        Target: actual_lead_time_days (float)

        Args:
            scenario_ids: Optional list of scenario IDs to filter

        Returns:
            DataFrame with features and target
        """
        conn = self._get_connection()

        query = """
            SELECT
                supplier_id,
                order_quantity,
                CAST(order_time / 24 AS INTEGER) % 7 as day_of_week,
                expected_lead_time_days,
                actual_lead_time_days,
                on_time,
                short_shipped
            FROM supplier_deliveries
            WHERE actual_lead_time_days IS NOT NULL
              AND actual_lead_time_days > 0
        """

        if scenario_ids:
            placeholders = ", ".join(["?" for _ in scenario_ids])
            query += f" AND scenario_id IN ({placeholders})"
            df = conn.execute(query, scenario_ids).df()
        else:
            df = conn.execute(query).df()

        logger.info(f"Extracted {len(df)} records for lead time model")
        return df

    def get_inventory_demand_dataset(
        self,
        scenario_ids: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Extract dataset for inventory demand forecasting.

        Returns daily demand aggregates by SKU/location.

        Args:
            scenario_ids: Optional list of scenario IDs to filter

        Returns:
            DataFrame with demand data
        """
        conn = self._get_connection()

        query = """
            SELECT
                sku,
                location,
                snapshot_day,
                daily_demand,
                daily_receipts,
                quantity_on_hand,
                stockout_hours,
                reorder_triggered
            FROM inventory_snapshots
            WHERE 1=1
        """

        if scenario_ids:
            placeholders = ", ".join(["?" for _ in scenario_ids])
            query += f" AND scenario_id IN ({placeholders})"
            df = conn.execute(query, scenario_ids).df()
        else:
            df = conn.execute(query).df()

        logger.info(f"Extracted {len(df)} records for inventory demand forecast")
        return df

    # ===== ENGAGEMENT WORKFLOW DATASETS =====

    def get_churn_dataset(
        self,
        scenario_ids: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Extract dataset for churn prediction model.

        Features: days_since_last_purchase, total_spend, purchase_count,
                  unresponsive_count, value_tier, churn_risk_score
        Target: churned (bool)

        Args:
            scenario_ids: Optional list of scenario IDs to filter

        Returns:
            DataFrame with features and target
        """
        conn = self._get_connection()

        query = """
            SELECT
                days_since_last_purchase,
                days_since_join,
                total_spend,
                purchase_count,
                avg_order_value,
                loyalty_points,
                unresponsive_count,
                value_tier,
                rfm_segment,
                churn_risk_score,
                churned
            FROM customer_snapshots
            WHERE 1=1
        """

        if scenario_ids:
            placeholders = ", ".join(["?" for _ in scenario_ids])
            query += f" AND scenario_id IN ({placeholders})"
            df = conn.execute(query, scenario_ids).df()
        else:
            df = conn.execute(query).df()

        logger.info(f"Extracted {len(df)} records for churn model")
        return df

    def get_campaign_response_dataset(
        self,
        scenario_ids: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Extract dataset for campaign response prediction model.

        Features: campaign_type, value_tier, rfm_segment,
                  unresponsive_count, days_since_last_engagement
        Target: clicked (bool) or converted (bool)

        Args:
            scenario_ids: Optional list of scenario IDs to filter

        Returns:
            DataFrame with features and target
        """
        conn = self._get_connection()

        query = """
            SELECT
                campaign_type,
                value_tier,
                rfm_segment,
                unresponsive_count,
                days_since_last_engagement,
                opened,
                clicked,
                converted
            FROM campaign_interactions
            WHERE 1=1
        """

        if scenario_ids:
            placeholders = ", ".join(["?" for _ in scenario_ids])
            query += f" AND scenario_id IN ({placeholders})"
            df = conn.execute(query, scenario_ids).df()
        else:
            df = conn.execute(query).df()

        logger.info(f"Extracted {len(df)} records for campaign response model")
        return df

    def get_clv_dataset(
        self,
        scenario_ids: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Extract dataset for customer lifetime value prediction.

        Features: days_since_join, purchase_count, avg_order_value,
                  loyalty_points, value_tier
        Target: total_spend (float)

        Args:
            scenario_ids: Optional list of scenario IDs to filter

        Returns:
            DataFrame with features and target
        """
        conn = self._get_connection()

        query = """
            SELECT
                days_since_join,
                purchase_count,
                avg_order_value,
                loyalty_points,
                value_tier,
                rfm_segment,
                total_spend
            FROM customer_snapshots
            WHERE total_spend > 0
        """

        if scenario_ids:
            placeholders = ", ".join(["?" for _ in scenario_ids])
            query += f" AND scenario_id IN ({placeholders})"
            df = conn.execute(query, scenario_ids).df()
        else:
            df = conn.execute(query).df()

        logger.info(f"Extracted {len(df)} records for CLV model")
        return df

    def get_dataset_stats(self) -> Dict[str, Any]:
        """Get statistics about available training data."""
        conn = self._get_connection()

        stats = {}

        # Scenario stats
        result = conn.execute("""
            SELECT
                COUNT(*) as total_scenarios,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed
            FROM simulation_scenarios
        """).fetchone()
        stats['scenarios'] = {
            'total': result[0],
            'completed': result[1],
        }

        # Journey stats
        result = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN completed THEN 1 ELSE 0 END) as completed,
                COUNT(DISTINCT scenario_id) as scenarios
            FROM customer_journeys
        """).fetchone()
        stats['journeys'] = {
            'total': result[0],
            'completed': result[1],
            'scenarios': result[2],
        }

        # Order stats
        result = conn.execute("""
            SELECT COUNT(*) FROM order_metrics
        """).fetchone()
        stats['orders'] = {'total': result[0]}

        # Hourly demand stats
        result = conn.execute("""
            SELECT COUNT(*) FROM hourly_demand
        """).fetchone()
        stats['hourly_demand'] = {'total': result[0]}

        return stats

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


# Convenience functions

def get_conversion_dataset(
    scenario_ids: Optional[List[str]] = None,
    db_path: str = POSTGRES_DB_PATH,
) -> pd.DataFrame:
    """Extract conversion dataset."""
    extractor = DataExtractor(db_path)
    try:
        return extractor.get_conversion_dataset(scenario_ids)
    finally:
        extractor.close()


def get_order_value_dataset(
    scenario_ids: Optional[List[str]] = None,
    db_path: str = POSTGRES_DB_PATH,
) -> pd.DataFrame:
    """Extract order value dataset."""
    extractor = DataExtractor(db_path)
    try:
        return extractor.get_order_value_dataset(scenario_ids)
    finally:
        extractor.close()


def get_demand_forecast_dataset(
    scenario_ids: Optional[List[str]] = None,
    channel: Optional[str] = None,
    db_path: str = POSTGRES_DB_PATH,
) -> pd.DataFrame:
    """Extract demand forecast dataset."""
    extractor = DataExtractor(db_path)
    try:
        return extractor.get_demand_forecast_dataset(scenario_ids, channel)
    finally:
        extractor.close()


def get_fulfillment_dataset(
    scenario_ids: Optional[List[str]] = None,
    db_path: str = POSTGRES_DB_PATH,
) -> pd.DataFrame:
    """Extract fulfillment dataset."""
    extractor = DataExtractor(db_path)
    try:
        return extractor.get_fulfillment_dataset(scenario_ids)
    finally:
        extractor.close()


# ===== INVENTORY WORKFLOW CONVENIENCE FUNCTIONS =====

def get_stockout_dataset(
    scenario_ids: Optional[List[str]] = None,
    db_path: str = POSTGRES_DB_PATH,
) -> pd.DataFrame:
    """Extract stockout prediction dataset."""
    extractor = DataExtractor(db_path)
    try:
        return extractor.get_stockout_dataset(scenario_ids)
    finally:
        extractor.close()


def get_lead_time_dataset(
    scenario_ids: Optional[List[str]] = None,
    db_path: str = POSTGRES_DB_PATH,
) -> pd.DataFrame:
    """Extract lead time prediction dataset."""
    extractor = DataExtractor(db_path)
    try:
        return extractor.get_lead_time_dataset(scenario_ids)
    finally:
        extractor.close()


def get_inventory_demand_dataset(
    scenario_ids: Optional[List[str]] = None,
    db_path: str = POSTGRES_DB_PATH,
) -> pd.DataFrame:
    """Extract inventory demand forecast dataset."""
    extractor = DataExtractor(db_path)
    try:
        return extractor.get_inventory_demand_dataset(scenario_ids)
    finally:
        extractor.close()


# ===== ENGAGEMENT WORKFLOW CONVENIENCE FUNCTIONS =====

def get_churn_dataset(
    scenario_ids: Optional[List[str]] = None,
    db_path: str = POSTGRES_DB_PATH,
) -> pd.DataFrame:
    """Extract churn prediction dataset."""
    extractor = DataExtractor(db_path)
    try:
        return extractor.get_churn_dataset(scenario_ids)
    finally:
        extractor.close()


def get_campaign_response_dataset(
    scenario_ids: Optional[List[str]] = None,
    db_path: str = POSTGRES_DB_PATH,
) -> pd.DataFrame:
    """Extract campaign response prediction dataset."""
    extractor = DataExtractor(db_path)
    try:
        return extractor.get_campaign_response_dataset(scenario_ids)
    finally:
        extractor.close()


def get_clv_dataset(
    scenario_ids: Optional[List[str]] = None,
    db_path: str = POSTGRES_DB_PATH,
) -> pd.DataFrame:
    """Extract customer lifetime value prediction dataset."""
    extractor = DataExtractor(db_path)
    try:
        return extractor.get_clv_dataset(scenario_ids)
    finally:
        extractor.close()
