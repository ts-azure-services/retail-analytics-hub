"""
Fulfillment time prediction model.

Predicts order fulfillment duration based on order attributes.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)

from .data_prep import get_fulfillment_dataset

logger = logging.getLogger(__name__)


class FulfillmentModel:
    """
    Fulfillment time prediction model.

    Uses GradientBoostingRegressor to predict order fulfillment duration
    based on order attributes.
    """

    FEATURE_COLUMNS = [
        'channel',
        'order_hour',
        'day_of_week',
    ]
    TARGET_COLUMN = 'fulfillment_duration'

    def __init__(self, random_state: int = 42):
        """
        Initialize the fulfillment model.

        Args:
            random_state: Random state for reproducibility
        """
        self.random_state = random_state
        self.model = GradientBoostingRegressor(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            random_state=random_state,
        )
        self.label_encoders: Dict[str, LabelEncoder] = {}
        self.metrics: Dict[str, float] = {}
        self.is_fitted = False

    def _encode_features(
        self, df: pd.DataFrame, fit: bool = False
    ) -> pd.DataFrame:
        """
        Encode categorical features.

        Args:
            df: Input DataFrame
            fit: Whether to fit the encoders

        Returns:
            DataFrame with encoded features
        """
        df = df.copy()

        # Encode channel
        if 'channel' in df.columns:
            if fit:
                self.label_encoders['channel'] = LabelEncoder()
                df['channel'] = self.label_encoders['channel'].fit_transform(df['channel'])
            else:
                df['channel'] = self.label_encoders['channel'].transform(df['channel'])

        return df

    def train(
        self,
        scenario_ids: Optional[List[str]] = None,
        test_size: float = 0.2,
    ) -> Dict[str, float]:
        """
        Train the fulfillment model.

        Args:
            scenario_ids: Optional list of scenario IDs to use
            test_size: Fraction of data for testing

        Returns:
            Dictionary of evaluation metrics
        """
        # Load data
        df = get_fulfillment_dataset(scenario_ids)

        if len(df) < 50:
            raise ValueError(f"Insufficient data: {len(df)} records. Need at least 50.")

        logger.info(f"Training data: {len(df)} orders with fulfillment data")
        logger.info(f"Duration range: {df[self.TARGET_COLUMN].min():.1f} - {df[self.TARGET_COLUMN].max():.1f} minutes")
        logger.info(f"Mean duration: {df[self.TARGET_COLUMN].mean():.1f} minutes")

        # Prepare features
        X = df[self.FEATURE_COLUMNS].copy()
        y = df[self.TARGET_COLUMN]

        # Encode categorical features
        X = self._encode_features(X, fit=True)

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=self.random_state
        )

        # Train model
        logger.info("Training GradientBoostingRegressor...")
        self.model.fit(X_train, y_train)
        self.is_fitted = True

        # Evaluate
        y_pred = self.model.predict(X_test)

        self.metrics = {
            'mae': mean_absolute_error(y_test, y_pred),
            'rmse': np.sqrt(mean_squared_error(y_test, y_pred)),
            'r2': r2_score(y_test, y_pred),
            'mean_actual': y_test.mean(),
            'mean_predicted': y_pred.mean(),
            'train_samples': len(X_train),
            'test_samples': len(X_test),
        }

        # Cross-validation
        cv_scores = cross_val_score(self.model, X, y, cv=5, scoring='r2')
        self.metrics['cv_r2_mean'] = cv_scores.mean()
        self.metrics['cv_r2_std'] = cv_scores.std()

        # MAPE
        mape = np.mean(np.abs((y_test - y_pred) / y_test)) * 100
        self.metrics['mape'] = mape

        # Feature importance
        self.feature_importance = dict(zip(
            self.FEATURE_COLUMNS,
            self.model.feature_importances_
        ))

        logger.info(f"Model trained. R2: {self.metrics['r2']:.3f}, MAE: {self.metrics['mae']:.1f} min")
        logger.info(f"CV R2: {self.metrics['cv_r2_mean']:.3f} +/- {self.metrics['cv_r2_std']:.3f}")

        return self.metrics

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        """
        Predict fulfillment duration.

        Args:
            features: DataFrame with feature columns

        Returns:
            Array of predicted durations (in minutes)
        """
        if not self.is_fitted:
            raise ValueError("Model not fitted. Call train() first.")

        X = features[self.FEATURE_COLUMNS].copy()
        X = self._encode_features(X, fit=False)

        predictions = self.model.predict(X)

        # Ensure non-negative durations
        return np.maximum(predictions, 0)

    def predict_sla_compliance(
        self,
        features: pd.DataFrame,
        sla_minutes: float,
    ) -> np.ndarray:
        """
        Predict SLA compliance probability.

        Args:
            features: DataFrame with feature columns
            sla_minutes: SLA threshold in minutes

        Returns:
            Array of boolean predictions (True = likely compliant)
        """
        predicted_duration = self.predict(features)
        return predicted_duration <= sla_minutes

    def save(self, path: str) -> None:
        """
        Save model to file.

        Args:
            path: Output file path
        """
        if not self.is_fitted:
            raise ValueError("Model not fitted. Call train() first.")

        model_data = {
            'model': self.model,
            'label_encoders': self.label_encoders,
            'metrics': self.metrics,
            'feature_importance': self.feature_importance,
            'feature_columns': self.FEATURE_COLUMNS,
            'saved_at': datetime.now().isoformat(),
        }

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(model_data, path)
        logger.info(f"Model saved to {path}")

    def load(self, path: str) -> None:
        """
        Load model from file.

        Args:
            path: Model file path
        """
        model_data = joblib.load(path)

        self.model = model_data['model']
        self.label_encoders = model_data['label_encoders']
        self.metrics = model_data['metrics']
        self.feature_importance = model_data.get('feature_importance', {})
        self.is_fitted = True

        logger.info(f"Model loaded from {path}")
        logger.info(f"Metrics: {self.metrics}")

    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance scores."""
        if not self.is_fitted:
            raise ValueError("Model not fitted. Call train() first.")
        return self.feature_importance
