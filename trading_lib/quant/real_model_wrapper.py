from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .labels import LabeledRow

try:
    from lightgbm import LGBMClassifier
    _HAS_LGBM = True
except ImportError:
    LGBMClassifier = None
    _HAS_LGBM = False


class RealModelWrapper:
    """
    Wrapper for real ML models that learn weights, interactions, and patterns.
    Replaces the fake "average of features" model.
    """
    
    def __init__(self, model_type: str = "lgbm", **params):
        self.model_type = model_type
        self.model = self._build_model(model_type, params)
        self.is_fitted = False
    
    def _build_model(self, model_type: str, params: Dict):
        if model_type == "logreg":
            return Pipeline([
                ("scaler", StandardScaler()),
                ("model", LogisticRegression(
                    C=float(params.get("C", 1.0)),
                    class_weight=params.get("class_weight", "balanced"),
                    max_iter=2000,
                    random_state=42,
                )),
            ])
        elif model_type == "rf":
            return RandomForestClassifier(
                n_estimators=int(params.get("n_estimators", 250)),
                max_depth=params.get("max_depth"),
                min_samples_leaf=int(params.get("min_samples_leaf", 1)),
                random_state=42,
                n_jobs=-1,
            )
        elif model_type == "lgbm":
            if not _HAS_LGBM:
                raise RuntimeError("LightGBM unavailable")
            import os
            kwargs = dict(
                n_estimators=int(params.get("n_estimators", 250)),
                learning_rate=float(params.get("learning_rate", 0.05)),
                num_leaves=int(params.get("num_leaves", 31)),
                subsample=float(params.get("subsample", 0.9)),
                colsample_bytree=float(params.get("colsample_bytree", 0.9)),
                random_state=42,
                verbose=-1,
            )
            if os.environ.get("USE_GPU", "").strip().lower() in ("1", "true", "yes"):
                kwargs["device"] = "gpu"
            return LGBMClassifier(**kwargs)
        else:
            raise ValueError(f"Unknown model type: {model_type}")
    
    def fit(self, labeled_rows: List[LabeledRow], target_horizon: str, fee_percent: float = 0.04):
        """Train model on labeled data with proper risk-adjusted labels."""
        from .improved_labels import build_improved_labels
        
        # Build improved labels
        scores, labels, metadata = build_improved_labels(
            labeled_rows, target_horizon, fee_percent
        )
        
        # Extract features
        feature_names = sorted(labeled_rows[0].features.keys())
        X = pd.DataFrame([
            {k: float(row.features.get(k, 0) or 0) for k in feature_names}
            for row in labeled_rows
        ], columns=feature_names)
        
        y = np.array(labels, dtype=int)
        
        # Train
        self.model.fit(X, y)
        self.is_fitted = True
        self.feature_names = feature_names
        return self
    
    def predict_proba(self, labeled_rows: List[LabeledRow]) -> np.ndarray:
        """Predict probabilities using learned model."""
        if not self.is_fitted:
            raise RuntimeError("Model not fitted")
        
        X = pd.DataFrame([
            {k: float(row.features.get(k, 0) or 0) for k in self.feature_names}
            for row in labeled_rows
        ], columns=self.feature_names)
        
        return self.model.predict_proba(X)
    
    def predict_score(self, labeled_rows: List[LabeledRow]) -> np.ndarray:
        """Predict raw scores (before sigmoid)."""
        if not self.is_fitted:
            raise RuntimeError("Model not fitted")
        
        X = pd.DataFrame([
            {k: float(row.features.get(k, 0) or 0) for k in self.feature_names}
            for row in labeled_rows
        ], columns=self.feature_names)
        
        if hasattr(self.model, "decision_function"):
            return self.model.decision_function(X)
        else:
            # For tree models, use probability
            proba = self.model.predict_proba(X)[:, 1]
            # Convert to log-odds (inverse sigmoid)
            proba = np.clip(proba, 1e-15, 1.0 - 1e-15)
            return np.log(proba / (1.0 - proba))
