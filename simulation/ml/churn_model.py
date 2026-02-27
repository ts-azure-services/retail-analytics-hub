"""
Customer churn prediction model.

Predicts whether a customer will churn based on their engagement
and purchase history.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
)

from .data_prep import get_churn_dataset

logger = logging.getLogger(__name__)


class ChurnModel:
    """
    Customer churn prediction model.

    Uses GradientBoostingClassifier to predict whether a customer
    will churn based on their engagement and purchase patterns.
    """

    FEATURE_COLUMNS = [
        'days_since_last_purchase',
        'days_since_join',
        'total_spend',
        'purchase_count',
        'avg_order_value',
        'loyalty_points',
        'unresponsive_count',
        'value_tier',
        'churn_risk_score',
    ]
    TARGET_COLUMN = 'churned'

    def __init__(self, random_state: int = 42):
        """
        Initialize the churn model.

        Args:
            random_state: Random state for reproducibility
        """
        self.random_state = random_state
        self.model = GradientBoostingClassifier(
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

        categorical_cols = ['value_tier']
        for col in categorical_cols:
            if col in df.columns:
                if fit:
                    self.label_encoders[col] = LabelEncoder()
                    df[col] = self.label_encoders[col].fit_transform(df[col].astype(str))
                else:
                    known = set(self.label_encoders[col].classes_)
                    df[col] = df[col].astype(str).apply(
                        lambda x: x if x in known else self.label_encoders[col].classes_[0]
                    )
                    df[col] = self.label_encoders[col].transform(df[col])

        return df

    def train(
        self,
        scenario_ids: Optional[List[str]] = None,
        test_size: float = 0.2,
    ) -> Dict[str, float]:
        """
        Train the churn prediction model.

        Args:
            scenario_ids: Optional list of scenario IDs to use
            test_size: Fraction of data for testing

        Returns:
            Dictionary of evaluation metrics
        """
        df = get_churn_dataset(scenario_ids)

        if len(df) < 100:
            raise ValueError(f"Insufficient data: {len(df)} records. Need at least 100.")

        n_churned = df[self.TARGET_COLUMN].sum()
        logger.info(
            f"Training data: {len(df)} records ({n_churned} churned)"
        )

        X = df[self.FEATURE_COLUMNS].copy()
        y = df[self.TARGET_COLUMN].astype(int)

        X = self._encode_features(X, fit=True)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=self.random_state,
            stratify=y if n_churned > 10 else None
        )

        logger.info("Training GradientBoostingClassifier for churn prediction...")
        self.model.fit(X_train, y_train)
        self.is_fitted = True

        y_pred = self.model.predict(X_test)
        y_pred_proba = self.model.predict_proba(X_test)[:, 1]

        self.metrics = {
            'accuracy': accuracy_score(y_test, y_pred),
            'precision': precision_score(y_test, y_pred, zero_division=0),
            'recall': recall_score(y_test, y_pred, zero_division=0),
            'f1': f1_score(y_test, y_pred, zero_division=0),
            'roc_auc': roc_auc_score(y_test, y_pred_proba) if n_churned > 10 else 0.0,
            'train_samples': len(X_train),
            'test_samples': len(X_test),
        }

        if n_churned > 10:
            cv_scores = cross_val_score(self.model, X, y, cv=5, scoring='roc_auc')
            self.metrics['cv_roc_auc_mean'] = cv_scores.mean()
            self.metrics['cv_roc_auc_std'] = cv_scores.std()

        self.feature_importance = dict(zip(
            self.FEATURE_COLUMNS,
            self.model.feature_importances_
        ))

        logger.info(f"Model trained. ROC AUC: {self.metrics.get('roc_auc', 0):.3f}")
        return self.metrics

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        """
        Predict churn probability.

        Args:
            features: DataFrame with feature columns

        Returns:
            Array of churn probabilities
        """
        if not self.is_fitted:
            raise ValueError("Model not fitted. Call train() first.")

        X = features[self.FEATURE_COLUMNS].copy()
        X = self._encode_features(X, fit=False)

        return self.model.predict_proba(X)[:, 1]

    def predict_binary(self, features: pd.DataFrame, threshold: float = 0.5) -> np.ndarray:
        """
        Predict binary churn outcome.

        Args:
            features: DataFrame with feature columns
            threshold: Classification threshold

        Returns:
            Array of binary predictions
        """
        proba = self.predict(features)
        return (proba >= threshold).astype(int)

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
