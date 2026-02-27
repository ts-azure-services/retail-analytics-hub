"""
Demand forecasting model using Prophet.

Forecasts hourly order demand using Facebook Prophet.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .data_prep import get_demand_forecast_dataset

logger = logging.getLogger(__name__)


class DemandForecastModel:
    """
    Demand forecasting model using Prophet.

    Predicts hourly order counts based on temporal patterns.
    """

    def __init__(
        self,
        yearly_seasonality: bool = False,
        weekly_seasonality: bool = True,
        daily_seasonality: bool = True,
    ):
        """
        Initialize the demand forecast model.

        Args:
            yearly_seasonality: Include yearly seasonality
            weekly_seasonality: Include weekly seasonality
            daily_seasonality: Include daily seasonality
        """
        self.yearly_seasonality = yearly_seasonality
        self.weekly_seasonality = weekly_seasonality
        self.daily_seasonality = daily_seasonality
        self.model = None
        self.metrics: Dict[str, float] = {}
        self.is_fitted = False
        self._prophet_available = self._check_prophet()

    def _check_prophet(self) -> bool:
        """Check if Prophet is available."""
        try:
            from prophet import Prophet
            return True
        except ImportError:
            logger.warning(
                "Prophet not available. Install with: pip install prophet"
            )
            return False

    def train(
        self,
        scenario_ids: Optional[List[str]] = None,
        channel: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        Train the demand forecast model.

        Args:
            scenario_ids: Optional list of scenario IDs to use
            channel: Optional channel filter

        Returns:
            Dictionary of evaluation metrics
        """
        if not self._prophet_available:
            raise ImportError("Prophet is required for demand forecasting")

        from prophet import Prophet
        from prophet.diagnostics import cross_validation, performance_metrics

        # Load data
        df = get_demand_forecast_dataset(scenario_ids, channel)

        if len(df) < 24:  # At least one day of hourly data
            raise ValueError(f"Insufficient data: {len(df)} records. Need at least 24.")

        # Aggregate by datetime
        df_prophet = df.groupby('ds').agg({
            'y': 'sum',
            'arrivals': 'sum',
            'revenue': 'sum',
        }).reset_index()

        logger.info(f"Training data: {len(df_prophet)} hourly records")
        logger.info(f"Order count range: {df_prophet['y'].min()} - {df_prophet['y'].max()}")

        # Initialize Prophet model
        self.model = Prophet(
            yearly_seasonality=self.yearly_seasonality,
            weekly_seasonality=self.weekly_seasonality,
            daily_seasonality=self.daily_seasonality,
        )

        # Train model
        logger.info("Training Prophet model...")
        self.model.fit(df_prophet[['ds', 'y']])
        self.is_fitted = True

        # Evaluate with cross-validation if enough data
        if len(df_prophet) >= 48:  # At least 2 days
            try:
                # Use shorter periods for simulation data
                cv_results = cross_validation(
                    self.model,
                    initial='24 hours',
                    period='12 hours',
                    horizon='12 hours',
                )
                perf_metrics = performance_metrics(cv_results)

                self.metrics = {
                    'mae': perf_metrics['mae'].mean(),
                    'rmse': perf_metrics['rmse'].mean(),
                    'mape': perf_metrics['mape'].mean() * 100,
                    'train_samples': len(df_prophet),
                }
            except Exception as e:
                logger.warning(f"Cross-validation failed: {e}")
                self.metrics = {'train_samples': len(df_prophet)}
        else:
            self.metrics = {'train_samples': len(df_prophet)}

        # Store channel info
        self.metrics['channel'] = channel or 'all'

        logger.info(f"Model trained. Metrics: {self.metrics}")

        return self.metrics

    def forecast(self, periods: int = 24) -> pd.DataFrame:
        """
        Generate demand forecast.

        Args:
            periods: Number of hours to forecast

        Returns:
            DataFrame with forecast (ds, yhat, yhat_lower, yhat_upper)
        """
        if not self.is_fitted:
            raise ValueError("Model not fitted. Call train() first.")

        # Create future dataframe
        future = self.model.make_future_dataframe(periods=periods, freq='H')

        # Generate forecast
        forecast = self.model.predict(future)

        # Return relevant columns
        return forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].tail(periods)

    def get_components(self) -> pd.DataFrame:
        """
        Get forecast components (trend, seasonality).

        Returns:
            DataFrame with component breakdown
        """
        if not self.is_fitted:
            raise ValueError("Model not fitted. Call train() first.")

        future = self.model.make_future_dataframe(periods=24, freq='H')
        forecast = self.model.predict(future)

        components = ['ds', 'trend']
        if self.daily_seasonality:
            components.append('daily')
        if self.weekly_seasonality:
            components.append('weekly')

        available = [c for c in components if c in forecast.columns]
        return forecast[available]

    def save(self, path: str) -> None:
        """
        Save model to JSON file.

        Note: Prophet models are serialized as JSON.

        Args:
            path: Output file path
        """
        if not self.is_fitted:
            raise ValueError("Model not fitted. Call train() first.")

        from prophet.serialize import model_to_json

        model_data = {
            'prophet_model': model_to_json(self.model),
            'metrics': self.metrics,
            'yearly_seasonality': self.yearly_seasonality,
            'weekly_seasonality': self.weekly_seasonality,
            'daily_seasonality': self.daily_seasonality,
            'saved_at': datetime.now().isoformat(),
        }

        Path(path).parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w') as f:
            json.dump(model_data, f)

        logger.info(f"Model saved to {path}")

    def load(self, path: str) -> None:
        """
        Load model from JSON file.

        Args:
            path: Model file path
        """
        if not self._prophet_available:
            raise ImportError("Prophet is required to load demand forecast model")

        from prophet.serialize import model_from_json

        with open(path, 'r') as f:
            model_data = json.load(f)

        self.model = model_from_json(model_data['prophet_model'])
        self.metrics = model_data['metrics']
        self.yearly_seasonality = model_data.get('yearly_seasonality', False)
        self.weekly_seasonality = model_data.get('weekly_seasonality', True)
        self.daily_seasonality = model_data.get('daily_seasonality', True)
        self.is_fitted = True

        logger.info(f"Model loaded from {path}")
        logger.info(f"Metrics: {self.metrics}")

    def plot_forecast(self, forecast: pd.DataFrame):
        """
        Plot the forecast using matplotlib.

        Args:
            forecast: Forecast DataFrame from forecast() method

        Returns:
            matplotlib figure
        """
        if not self.is_fitted:
            raise ValueError("Model not fitted. Call train() first.")

        return self.model.plot(forecast)

    def plot_components(self):
        """
        Plot forecast components.

        Returns:
            matplotlib figure
        """
        if not self.is_fitted:
            raise ValueError("Model not fitted. Call train() first.")

        future = self.model.make_future_dataframe(periods=24, freq='H')
        forecast = self.model.predict(future)
        return self.model.plot_components(forecast)
