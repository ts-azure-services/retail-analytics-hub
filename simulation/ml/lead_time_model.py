"""
Lead time prediction model.

Predicts supplier delivery lead times based on order and supplier attributes.
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

from .data_prep import get_lead_time_dataset

logger = logging.getLogger(__name__)


class LeadTimeModel:
    """
    Supplier lead time prediction model.

    Uses GradientBoostingRegressor to predict actual delivery lead times
    based on supplier, order quantity, and temporal factors.
    """

    FEATURE_COLUMNS = [
        'supplier_id',
        'order_quantity',
        'day_of_week',
        'expected_lead_time_days',
    ]
    TARGET_COLUMN = 'actual_lead_time_days'

    def __init__(self, random_state: int = 42):
        """
        Initialize the lead time model.

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

        if 'supplier_id' in df.columns:
            if fit:
                self.label_encoders['supplier_id'] = LabelEncoder()
                df['supplier_id'] = self.label_encoders['supplier_id'].fit_transform(
                    df['supplier_id'].astype(str)
                )
            else:
                # Handle unseen suppliers
                known = set(self.label_encoders['supplier_id'].classes_)
                df['supplier_id'] = df['supplier_id'].astype(str).apply(
                    lambda x: x if x in known else self.label_encoders['supplier_id'].classes_[0]
                )
                df['supplier_id'] = self.label_encoders['supplier_id'].transform(df['supplier_id'])

        return df

    def train(
        self,
        scenario_ids: Optional[List[str]] = None,
        test_size: float = 0.2,
    ) -> Dict[str, float]:
        """
        Train the lead time model.

        Args:
            scenario_ids: Optional list of scenario IDs to use
            test_size: Fraction of data for testing

        Returns:
            Dictionary of evaluation metrics
        """
        df = get_lead_time_dataset(scenario_ids)

        if len(df) < 50:
            raise ValueError(f"Insufficient data: {len(df)} records. Need at least 50.")

        logger.info(f"Training data: {len(df)} delivery records")

        X = df[self.FEATURE_COLUMNS].copy()
        y = df[self.TARGET_COLUMN]

        X = self._encode_features(X, fit=True)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=self.random_state
        )

        logger.info("Training GradientBoostingRegressor for lead time prediction...")
        self.model.fit(X_train, y_train)
        self.is_fitted = True

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

        cv_scores = cross_val_score(self.model, X, y, cv=5, scoring='neg_mean_absolute_error')
        self.metrics['cv_mae_mean'] = -cv_scores.mean()
        self.metrics['cv_mae_std'] = cv_scores.std()

        self.feature_importance = dict(zip(
            self.FEATURE_COLUMNS,
            self.model.feature_importances_
        ))

        logger.info(f"Model trained. MAE: {self.metrics['mae']:.2f} days, R2: {self.metrics['r2']:.3f}")
        return self.metrics

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        """
        Predict lead time in days.

        Args:
            features: DataFrame with feature columns

        Returns:
            Array of predicted lead times
        """
        if not self.is_fitted:
            raise ValueError("Model not fitted. Call train() first.")

        X = features[self.FEATURE_COLUMNS].copy()
        X = self._encode_features(X, fit=False)

        return self.model.predict(X)

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
