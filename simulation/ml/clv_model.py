"""
Customer Lifetime Value (CLV) prediction model.

Predicts expected customer lifetime value based on purchase history
and engagement metrics.
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
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from .data_prep import get_clv_dataset

logger = logging.getLogger(__name__)


class CLVModel:
    """
    Customer Lifetime Value prediction model.

    Uses GradientBoostingRegressor to predict total customer spend
    based on their profile and purchase patterns.
    """

    FEATURE_COLUMNS = [
        'days_since_join',
        'purchase_count',
        'avg_order_value',
        'loyalty_points',
        'value_tier',
    ]
    TARGET_COLUMN = 'total_spend'

    def __init__(self, random_state: int = 42):
        """
        Initialize the CLV model.

        Args:
            random_state: Random state for reproducibility
        """
        self.random_state = random_state
        self.model = GradientBoostingRegressor(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            random_state=random_state,
        )
        self.label_encoders: Dict[str, LabelEncoder] = {}
        self.metrics: Dict[str, float] = {}
        self.feature_importance: Dict[str, float] = {}
        self.is_fitted = False

    def _encode_features(
        self, df: pd.DataFrame, fit: bool = False
    ) -> pd.DataFrame:
        """Encode categorical features."""
        df = df.copy()

        if 'value_tier' in df.columns:
            if fit:
                self.label_encoders['value_tier'] = LabelEncoder()
                df['value_tier'] = self.label_encoders['value_tier'].fit_transform(
                    df['value_tier'].astype(str)
                )
            else:
                known = set(self.label_encoders['value_tier'].classes_)
                df['value_tier'] = df['value_tier'].astype(str).apply(
                    lambda x: x if x in known else self.label_encoders['value_tier'].classes_[0]
                )
                df['value_tier'] = self.label_encoders['value_tier'].transform(df['value_tier'])

        return df

    def train(
        self,
        scenario_ids: Optional[List[str]] = None,
        test_size: float = 0.2,
    ) -> Dict[str, float]:
        """
        Train the CLV model.

        Args:
            scenario_ids: Optional list of scenario IDs to use
            test_size: Fraction of data for testing

        Returns:
            Dictionary of evaluation metrics
        """
        df = get_clv_dataset(scenario_ids)

        if len(df) < 50:
            raise ValueError(f"Insufficient data: {len(df)} records. Need at least 50.")

        logger.info(f"Training data: {len(df)} customer records")
        logger.info(f"Target range: ${df[self.TARGET_COLUMN].min():.2f} - ${df[self.TARGET_COLUMN].max():.2f}")

        X = df[self.FEATURE_COLUMNS].copy()
        y = df[self.TARGET_COLUMN]

        X = self._encode_features(X, fit=True)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=self.random_state
        )

        logger.info("Training GradientBoostingRegressor for CLV prediction...")
        self.model.fit(X_train, y_train)
        self.is_fitted = True

        y_pred = self.model.predict(X_test)

        self.metrics = {
            'mae': mean_absolute_error(y_test, y_pred),
            'rmse': np.sqrt(mean_squared_error(y_test, y_pred)),
            'r2': r2_score(y_test, y_pred),
            'mean_actual': y_test.mean(),
            'mean_predicted': y_pred.mean(),
            'mape': np.mean(np.abs((y_test - y_pred) / y_test)) * 100,  # Mean Absolute Percentage Error
            'train_samples': len(X_train),
            'test_samples': len(X_test),
        }

        cv_scores = cross_val_score(self.model, X, y, cv=5, scoring='neg_mean_absolute_error')
        self.metrics['cv_mae_mean'] = -cv_scores.mean()
        self.metrics['cv_mae_std'] = cv_scores.std()

        self.feature_importance = dict(zip(
            self.FEATURE_COLUMNS,
            self.model.feature_importances_
        ))

        logger.info(f"Model trained. MAE: ${self.metrics['mae']:.2f}, R2: {self.metrics['r2']:.3f}")
        return self.metrics

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        """
        Predict customer lifetime value.

        Args:
            features: DataFrame with feature columns

        Returns:
            Array of predicted CLV values
        """
        if not self.is_fitted:
            raise ValueError("Model not fitted. Call train() first.")

        X = features[self.FEATURE_COLUMNS].copy()
        X = self._encode_features(X, fit=False)

        # Ensure non-negative predictions
        predictions = self.model.predict(X)
        return np.maximum(predictions, 0)

    def predict_segments(
        self, features: pd.DataFrame, thresholds: Optional[List[float]] = None
    ) -> np.ndarray:
        """
        Predict CLV segments (low, medium, high, premium).

        Args:
            features: DataFrame with feature columns
            thresholds: Optional list of 3 threshold values [low/med, med/high, high/premium]
                       Default: [100, 500, 2000]

        Returns:
            Array of segment labels
        """
        if thresholds is None:
            thresholds = [100, 500, 2000]

        clv = self.predict(features)

        segments = np.empty(len(clv), dtype=object)
        segments[clv < thresholds[0]] = 'low'
        segments[(clv >= thresholds[0]) & (clv < thresholds[1])] = 'medium'
        segments[(clv >= thresholds[1]) & (clv < thresholds[2])] = 'high'
        segments[clv >= thresholds[2]] = 'premium'

        return segments

    def save(self, path: str) -> None:
        """Save model to file."""
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
        """Load model from file."""
        model_data = joblib.load(path)

        self.model = model_data['model']
        self.label_encoders = model_data['label_encoders']
        self.metrics = model_data['metrics']
        self.feature_importance = model_data.get('feature_importance', {})
        self.is_fitted = True

        logger.info(f"Model loaded from {path}")

    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance scores."""
        if not self.is_fitted:
            raise ValueError("Model not fitted. Call train() first.")
        return self.feature_importance
