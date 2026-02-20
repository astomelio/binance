"""Predict score and probability for latest decision_features row."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai.config import get_calibration_dir
from ai.data.loader import get_connection, load_decision_features
from trading_lib.quant.calibration import load_calibration, predict_calibrated_probability

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection


def predict(
    symbol: str,
    horizon: str = "4h",
    conn: DuckDBPyConnection | None = None,
    calibration_path: str | None = None,
) -> dict:
    """
    Predict for the latest event_time of symbol.
    Returns: score, prob, event_time, regime_combo, alpha_signal.
    """
    rows = load_decision_features(
        conn=conn,
        horizon=horizon,
        symbols=[symbol],
        label_not_null=False,
    )
    if not rows:
        return {"score": 0.0, "prob": 0.5, "event_time": None, "regime_combo": None, "alpha_signal": "NO_DATA"}

    latest = max(rows, key=lambda r: r.get("event_time") or "")
    score = float(latest.get("alpha_score") or 0.0)
    calib_path = calibration_path or f"{get_calibration_dir()}/champion_{horizon}_calibration.json"
    try:
        calib = load_calibration(calib_path)
        prob = predict_calibrated_probability(score, calib)
    except Exception:
        import math
        prob = 1.0 / (1.0 + math.exp(-score))

    return {
        "score": score,
        "prob": prob,
        "event_time": latest.get("event_time"),
        "regime_combo": latest.get("regime_combo"),
        "alpha_signal": latest.get("alpha_signal", "NO_TRADE"),
    }
