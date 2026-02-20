"""Config for AI module. Uses env vars, no hardcoded paths."""

from __future__ import annotations

import os


def get_warehouse_path() -> str:
    return os.environ.get("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")


def get_model_dir() -> str:
    return os.environ.get("AI_MODEL_DIR", "artifacts/models")


def get_calibration_dir() -> str:
    return os.environ.get("AI_CALIBRATION_DIR", "artifacts/calibration")


def get_registry_path() -> str:
    return os.environ.get("AI_REGISTRY_PATH", "artifacts/ai/runs.duckdb")
