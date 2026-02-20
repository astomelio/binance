"""AI/ML layer: training, inference, backtest. Single source of truth: DuckDB decision_features."""

from ai.config import get_calibration_dir, get_model_dir, get_warehouse_path
from ai.data.loader import get_connection, load_decision_features
from ai.allocation import AllocationVector, compute_allocations

__all__ = [
    "get_connection",
    "get_warehouse_path",
    "get_model_dir",
    "get_calibration_dir",
    "load_decision_features",
    "AllocationVector",
    "compute_allocations",
]
