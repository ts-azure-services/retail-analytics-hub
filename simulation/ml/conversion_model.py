"""
Conversion prediction model.

Predicts whether a customer will complete a purchase based on
their journey attributes.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    classification_report,
)

from .data_prep import get_conversion_dataset

logger = logging.getLogger(__name__)


class ConversionModel:
    """
    Customer conversion prediction model.

    Uses GradientBoostingClassifier to predict whether a customer
    will complete a purchase based on their journey attributes.
    """

    FEATURE_COLUMNS = [
        'channel',
        'arrival_hour',
        'day_of_week',
        'browsing_duration',
        'basket_size',
        'queue_wait_time',
    ]
    TARGET_COLUMN = 'completed'

    def __init__(self, random_state: int = 42):
        """
        Initialize the conversion model.

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
        Train the conversion model.

        Args:
            scenario_ids: Optional list of scenario IDs to use
            test_size: Fraction of data for testing

        Returns:
            Dictionary of evaluation metrics
        """
        # Load data
        df = get_conversion_dataset(scenario_ids)

        if len(df) < 100:
            raise ValueError(f"Insufficient data: {len(df)} records. Need at least 100.")

        # Check class balance
        n_completed = df[self.TARGET_COLUMN].sum()
        n_not_completed = len(df) - n_completed

        logger.info(
            f"Training data: {len(df)} records "
            f"({n_completed} completed, {n_not_completed} not completed)"
        )

        # Prepare features
        X = df[self.FEATURE_COLUMNS].copy()
        y = df[self.TARGET_COLUMN].astype(int)

        # Encode categorical features
        X = self._encode_features(X, fit=True)

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=self.random_state, stratify=y
        )

        # Train model
        logger.info("Training GradientBoostingClassifier...")
        self.model.fit(X_train, y_train)
        self.is_fitted = True

        # Evaluate
        y_pred = self.model.predict(X_test)
        y_pred_proba = self.model.predict_proba(X_test)[:, 1]

        self.metrics = {
            'accuracy': accuracy_score(y_test, y_pred),
            'precision': precision_score(y_test, y_pred),
            'recall': recall_score(y_test, y_pred),
            'f1': f1_score(y_test, y_pred),
            'roc_auc': roc_auc_score(y_test, y_pred_proba),
            'train_samples': len(X_train),
            'test_samples': len(X_test),
        }

        # Cross-validation score
        cv_scores = cross_val_score(self.model, X, y, cv=5, scoring='roc_auc')
        self.metrics['cv_roc_auc_mean'] = cv_scores.mean()
        self.metrics['cv_roc_auc_std'] = cv_scores.std()

        # Feature importance
        self.feature_importance = dict(zip(
            self.FEATURE_COLUMNS,
            self.model.feature_importances_
        ))

        logger.info(f"Model trained. ROC AUC: {self.metrics['roc_auc']:.3f}")
        logger.info(f"CV ROC AUC: {self.metrics['cv_roc_auc_mean']:.3f} +/- {self.metrics['cv_roc_auc_std']:.3f}")

        return self.metrics

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        """
        Predict conversion probability.

        Args:
            features: DataFrame with feature columns

        Returns:
            Array of conversion probabilities
        """
        if not self.is_fitted:
            raise ValueError("Model not fitted. Call train() first.")

        X = features[self.FEATURE_COLUMNS].copy()
        X = self._encode_features(X, fit=False)

        return self.model.predict_proba(X)[:, 1]

    def predict_binary(self, features: pd.DataFrame, threshold: float = 0.5) -> np.ndarray:
        """
        Predict binary conversion outcome.

        Args:
            features: DataFrame with feature columns
            threshold: Classification threshold

        Returns:
            Array of binary predictions
        """
        proba = self.predict(features)
        return (proba >= threshold).astype(int)

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
