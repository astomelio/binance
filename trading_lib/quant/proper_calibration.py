from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
from scipy import optimize

from .labels import LabeledRow
from .real_model_wrapper import RealModelWrapper


def calibrate_per_split(
    train_rows: List[LabeledRow],
    validation_rows: List[LabeledRow],
    model_type: str,
    target_horizon: str,
    fee_percent: float = 0.04,
) -> Tuple[RealModelWrapper, float, Dict]:
    """
    Proper calibration workflow:
    1. Train model on train set
    2. Calibrate probabilities on train set
    3. Optimize threshold on validation set
    4. Return model + threshold
    
    NO LEAKAGE: Each split is independent.
    """
    from .calibration import train_calibration
    
    # Step 1: Train real model (learns weights, interactions)
    model = RealModelWrapper(model_type=model_type)
    model.fit(train_rows, target_horizon, fee_percent)
    
    # Step 2: Get scores from trained model (not average!)
    train_scores = model.predict_score(train_rows)
    
    # Step 3: Build labels for calibration
    from .improved_labels import build_improved_labels
    _, train_labels, _ = build_improved_labels(train_rows, target_horizon, fee_percent)
    
    # Step 4: Train calibration on train set
    from .calibration import CalibratedModel, train_calibration, predict_calibrated_probability
    calibration = train_calibration(
        scores=train_scores.tolist(),
        labels=train_labels,
        feature_name="model_score",
    )
    
    # Step 5: Optimize threshold on VALIDATION set (not test!)
    val_probs = model.predict_proba(validation_rows)[:, 1]
    val_scores = model.predict_score(validation_rows)
    val_calibrated_probs = np.array([
        predict_calibrated_probability(float(s), calibration)
        for s in val_scores
    ])
    
    # Get validation returns
    val_returns = np.array([getattr(r, target_horizon) for r in validation_rows])
    val_net_returns = val_returns - fee_percent
    
    # Optimize threshold on validation
    best_threshold = 0.5
    best_sharpe = -float("inf")
    
    for th in np.arange(0.45, 0.70, 0.01):
        signals = np.zeros_like(val_calibrated_probs)
        signals[val_calibrated_probs >= th] = 1.0
        signals[val_calibrated_probs <= (1.0 - th)] = -1.0
        
        active = signals != 0.0
        if not np.any(active):
            continue
        
        net = (signals[active] * val_net_returns[active])
        if len(net) < 5:
            continue
        
        avg_return = np.mean(net)
        std_return = np.std(net) if len(net) > 1 else 0.01
        sharpe = (avg_return / std_return) if std_return > 0 else 0.0
        
        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_threshold = th
    
    metrics = {
        "validation_sharpe": best_sharpe,
        "validation_trades": int(np.sum(val_calibrated_probs >= best_threshold)),
        "validation_win_rate": float(np.mean((signals[active] * val_net_returns[active]) > 0)) if np.any(active) else 0.0,
    }
    
    return model, best_threshold, metrics
