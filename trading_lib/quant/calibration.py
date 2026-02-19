from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import numpy as np
from scipy import optimize


@dataclass
class CalibratedModel:
    """Calibrated probability model using Platt scaling (sigmoid)."""
    a: float  # slope
    b: float  # intercept
    feature_name: str  # which feature to calibrate (e.g., "model_score", "alpha_score")


def _sigmoid(x: float, a: float, b: float) -> float:
    """Sigmoid function: 1 / (1 + exp(a * x + b))"""
    z = a * x + b
    if z > 500:
        return 0.0
    if z < -500:
        return 1.0
    return 1.0 / (1.0 + np.exp(z))


def _platt_loss(params: np.ndarray, scores: np.ndarray, labels: np.ndarray) -> float:
    """Loss function for Platt scaling (negative log-likelihood)."""
    a, b = params
    probs = np.array([_sigmoid(s, a, b) for s in scores])
    # Avoid log(0)
    probs = np.clip(probs, 1e-15, 1.0 - 1e-15)
    loss = -np.sum(labels * np.log(probs) + (1.0 - labels) * np.log(1.0 - probs))
    return loss


def train_calibration(
    scores: List[float],
    labels: List[int],
    feature_name: str = "model_score",
) -> CalibratedModel:
    """
    Train Platt scaling calibration on raw model scores.
    
    Args:
        scores: Raw model scores (e.g., alpha_score, model_score)
        labels: Binary labels (1 = positive outcome, 0 = negative)
        feature_name: Name of the feature being calibrated
    
    Returns:
        CalibratedModel with fitted parameters
    """
    if len(scores) != len(labels):
        raise ValueError(f"Length mismatch: {len(scores)} scores vs {len(labels)} labels")
    
    scores_arr = np.array(scores, dtype=float)
    labels_arr = np.array(labels, dtype=int)
    
    # Remove NaN/Inf
    valid = np.isfinite(scores_arr) & np.isfinite(labels_arr)
    scores_arr = scores_arr[valid]
    labels_arr = labels_arr[valid]
    
    if len(scores_arr) < 10:
        raise ValueError(f"Insufficient valid samples: {len(scores_arr)}")
    
    # Initial guess: a=-1, b=0 (standard sigmoid)
    initial = np.array([-1.0, 0.0])
    
    # Optimize
    result = optimize.minimize(
        _platt_loss,
        initial,
        args=(scores_arr, labels_arr),
        method="BFGS",
        options={"maxiter": 1000},
    )
    
    if not result.success:
        # Fallback to simple linear mapping if optimization fails
        a, b = -1.0, 0.0
    else:
        a, b = result.x
    
    return CalibratedModel(a=float(a), b=float(b), feature_name=feature_name)


def predict_calibrated_probability(score: float, model: CalibratedModel) -> float:
    """Predict calibrated probability from raw score."""
    return _sigmoid(score, model.a, model.b)


def save_calibration(model: CalibratedModel, path: str) -> None:
    """Save calibrated model to JSON."""
    payload = {
        "a": model.a,
        "b": model.b,
        "feature_name": model.feature_name,
    }
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_calibration(path: str) -> CalibratedModel:
    """Load calibrated model from JSON."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return CalibratedModel(
        a=float(payload["a"]),
        b=float(payload["b"]),
        feature_name=str(payload["feature_name"]),
    )
