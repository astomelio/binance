#!/usr/bin/env python3
"""
Llena SOLO las tablas vacías (cross_exchange, dex, fear_greed) sin tocar las que ya tienen datos.

Proceso oficial:
1. Ejecuta bronze_high + bronze_medium (Bybit, OKX, DexScreener, FearGreed, CoinGecko)
2. Carga solo cross_exchange_snapshot_raw, dex_snapshot_raw, fear_greed_raw a DuckDB

NO sobrescribe market_snapshot_raw, derivatives_*, decision_features, etc.

Uso:
    python -m data_platform.scripts.fill_empty_tables
    make warehouse-fill-empty
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from data_platform.config import DataPlatformConfig
from data_platform.loaders.bronze_to_duckdb import load_bronze_to_duckdb
from data_platform.pipeline import run_bronze


def main() -> None:
    cfg = DataPlatformConfig()
    db_env = os.environ.get("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
    repo_root = Path(__file__).resolve().parents[2]
    db_path = db_env if Path(db_env).is_absolute() else str(repo_root / db_env)
    schema = os.environ.get("WAREHOUSE_SCHEMA", "main")

    print("[fill_empty] 1/2 Ejecutando bronze (high + medium)...")
    run_bronze(cfg, source_groups=["high", "medium"])

    print(f"[fill_empty] 2/2 Cargando solo cross_exchange, dex, fear_greed -> {schema}.*")
    counts = load_bronze_to_duckdb(
        cfg,
        db_path,
        schema=schema,
        tables_only=[
            "cross_exchange_snapshot_raw",
            "dex_snapshot_raw",
            "fear_greed_raw",
        ],
    )
    print(f"[fill_empty] Cargado: {counts}")
    print("[fill_empty] Hecho. Las demás tablas NO se tocaron.")


if __name__ == "__main__":
    main()
