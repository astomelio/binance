from __future__ import annotations

from typing import Dict, List, Tuple
from statistics import mean, pstdev


def build_improved_labels(
    labeled_rows: List,
    horizon: str,
    fee_percent: float = 0.04,
    min_sharpe: float = 0.5,
    max_drawdown_pct: float = 5.0,
) -> Tuple[List[float], List[int], List[Dict]]:
    """
    Build improved labels that account for:
    - Volatility (sharpe-like)
    - Drawdown risk
    - Asymmetry (skew)
    - Position sizing (confidence)
    
    Returns: (scores, labels, metadata)
    """
    scores: List[float] = []
    labels: List[int] = []
    metadata: List[Dict] = []
    
    # Calculate rolling volatility for risk adjustment
    returns_window: List[float] = []
    window_size = 20  # 20 periods for volatility
    
    for i, row in enumerate(labeled_rows):
        fwd_return = getattr(row, horizon)
        
        # Use model score from features (will be replaced by actual model predictions)
        # For now, use weighted sum (will be replaced)
        score = sum(float(v) for v in row.features.values()) / len(row.features) if row.features else 0.0
        scores.append(score)
        
        # Calculate net return with fees
        net_return = fwd_return - fee_percent
        
        # Add to rolling window
        returns_window.append(net_return)
        if len(returns_window) > window_size:
            returns_window.pop(0)
        
        # Calculate volatility-adjusted return (sharpe-like)
        if len(returns_window) > 5:
            vol = pstdev(returns_window) if len(returns_window) > 1 else 0.01
            vol = max(vol, 0.01)  # Floor volatility
            sharpe_like = net_return / vol if vol > 0 else 0.0
        else:
            sharpe_like = net_return / 0.01  # Default vol
        
        # Calculate drawdown risk (simplified: negative return magnitude)
        drawdown_risk = abs(min(0, net_return))
        
        # Improved label: positive if sharpe-like > threshold AND drawdown acceptable
        label = 1 if (sharpe_like > min_sharpe and drawdown_risk < max_drawdown_pct) else 0
        
        # Also consider asymmetry: prefer positive skew
        # (simplified: just use net_return sign for now)
        if net_return < -max_drawdown_pct:
            label = 0  # Block large losses
        
        labels.append(label)
        metadata.append({
            "net_return": net_return,
            "sharpe_like": sharpe_like,
            "drawdown_risk": drawdown_risk,
            "volatility": vol if len(returns_window) > 5 else 0.01,
        })
    
    return scores, labels, metadata
