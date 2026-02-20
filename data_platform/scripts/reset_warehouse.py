#!/usr/bin/env python3
"""
Reset DuckDB warehouse to a clean state: one schema (main), only the pipeline tables.

Run with DBeaver CLOSED. Deletes crypto.duckdb and recreates from bronze data.

Usage:
    python -m data_platform.scripts.reset_warehouse
    make warehouse-reset
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from data_platform.config import DataPlatformConfig
from data_platform.loaders.bronze_to_duckdb import load_bronze_to_duckdb


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    db_env = os.environ.get("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
    db_path = db_env if Path(db_env).is_absolute() else str(repo_root / db_env)

    if Path(db_path).exists():
        Path(db_path).unlink()
        print(f"[reset] Deleted {db_path}")

    cfg = DataPlatformConfig()
    counts = load_bronze_to_duckdb(cfg, db_path)
    print(f"[reset] Loaded raw: {counts}")

    # Run dbt
    import subprocess
    env = dict(os.environ)
    env["DBT_DUCKDB_PATH"] = db_path
    dbt_path = repo_root / "venv" / "bin" / "dbt"
    if not dbt_path.exists():
        dbt_path = Path(sys.executable).parent / "dbt"
    result = subprocess.run(
        [str(dbt_path), "run", "--target", "local", "--profiles-dir", "."],
        cwd=str(repo_root / "data_platform" / "dbt"),
        env=env,
    )
    if result.returncode != 0:
        sys.exit(result.returncode)

    print("[reset] Done. Schema main, tables:")
    print("  - decision_features  <- TABLA PRINCIPAL (features + labels para ML/trading)")
    print("  - slv_decision_features, br_market_snapshot, br_macro_context (intermedias)")
    print("  - market_snapshot_raw, derivatives_*_raw, ... (input raw)")


if __name__ == "__main__":
    main()
