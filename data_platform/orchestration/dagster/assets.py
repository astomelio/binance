from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dagster import MaterializeResult, asset

from data_platform.config import DataPlatformConfig
from data_platform.loaders.bronze_to_duckdb import load_bronze_to_duckdb
from data_platform.pipeline import run_bronze, run_gold, run_silver


@asset(group_name="crypto_lake_high")
def bronze_high_ingestion(context) -> MaterializeResult:
    cfg = DataPlatformConfig()
    run_bronze(cfg, source_groups=["high"])
    return MaterializeResult(metadata={"layer": "bronze", "group": "high", "lake_root": cfg.lake_root})


@asset(group_name="crypto_lake_high", deps=[bronze_high_ingestion])
def silver_high_transform(context) -> MaterializeResult:
    cfg = DataPlatformConfig()
    run_silver(cfg)
    return MaterializeResult(metadata={"layer": "silver", "group": "high", "lake_root": cfg.lake_root})


@asset(group_name="crypto_lake_high", deps=[silver_high_transform])
def gold_high_features(context) -> MaterializeResult:
    cfg = DataPlatformConfig()
    run_gold(cfg)
    return MaterializeResult(metadata={"layer": "gold", "group": "high", "dataset": "decision_features"})


@asset(group_name="crypto_lake_medium")
def bronze_medium_ingestion(context) -> MaterializeResult:
    cfg = DataPlatformConfig()
    run_bronze(cfg, source_groups=["medium"])
    return MaterializeResult(metadata={"layer": "bronze", "group": "medium", "lake_root": cfg.lake_root})


@asset(group_name="crypto_lake_medium", deps=[bronze_medium_ingestion])
def silver_medium_transform(context) -> MaterializeResult:
    cfg = DataPlatformConfig()
    run_silver(cfg)
    return MaterializeResult(metadata={"layer": "silver", "group": "medium", "lake_root": cfg.lake_root})


@asset(group_name="crypto_lake_medium", deps=[silver_medium_transform])
def gold_medium_features(context) -> MaterializeResult:
    cfg = DataPlatformConfig()
    run_gold(cfg)
    return MaterializeResult(metadata={"layer": "gold", "group": "medium", "dataset": "decision_features"})


@asset(group_name="crypto_lake_low")
def bronze_low_ingestion(context) -> MaterializeResult:
    cfg = DataPlatformConfig()
    run_bronze(cfg, source_groups=["low"])
    return MaterializeResult(metadata={"layer": "bronze", "group": "low", "lake_root": cfg.lake_root})


@asset(group_name="crypto_lake_low", deps=[bronze_low_ingestion])
def silver_low_transform(context) -> MaterializeResult:
    cfg = DataPlatformConfig()
    run_silver(cfg)
    return MaterializeResult(metadata={"layer": "silver", "group": "low", "lake_root": cfg.lake_root})


@asset(group_name="crypto_lake_low", deps=[silver_low_transform])
def gold_low_features(context) -> MaterializeResult:
    cfg = DataPlatformConfig()
    run_gold(cfg)
    return MaterializeResult(metadata={"layer": "gold", "group": "low", "dataset": "decision_features"})


@asset(
    group_name="crypto_lake_warehouse",
    deps=[bronze_high_ingestion, bronze_medium_ingestion, bronze_low_ingestion],
)
def warehouse_raw_load(context) -> MaterializeResult:
    cfg = DataPlatformConfig()
    repo_root = Path(__file__).resolve().parents[3]
    db_path_env = os.getenv("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
    db_path = str((repo_root / db_path_env).resolve()) if not Path(db_path_env).is_absolute() else db_path_env
    counts = load_bronze_to_duckdb(cfg, db_path=db_path)
    return MaterializeResult(
        metadata={
            "layer": "warehouse_raw",
            "tool": "duckdb",
            "db_path": db_path,
            "table_counts": counts,
        }
    )


@asset(
    group_name="crypto_lake_warehouse",
    deps=[warehouse_raw_load],
)
def warehouse_dbt_build(context) -> MaterializeResult:
    dbt_project_dir = Path(__file__).resolve().parents[2] / "dbt"
    repo_root = Path(__file__).resolve().parents[3]
    db_path_env = os.getenv("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
    db_path = str((repo_root / db_path_env).resolve()) if not Path(db_path_env).is_absolute() else db_path_env
    dbt_executable = Path(sys.executable).resolve().parent / "dbt"
    cmd = (
        [str(dbt_executable), "build", "--target", os.getenv("DBT_TARGET", "local"), "--profiles-dir", str(dbt_project_dir)]
        if dbt_executable.exists()
        else ["dbt", "build", "--target", os.getenv("DBT_TARGET", "local"), "--profiles-dir", str(dbt_project_dir)]
    )
    env = dict(os.environ)
    env["DBT_DUCKDB_PATH"] = db_path
    result = subprocess.run(cmd, cwd=str(dbt_project_dir), capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(
            "dbt build failed: "
            f"stdout={result.stdout[-1200:]} "
            f"stderr={result.stderr[-1200:]}"
        )
    return MaterializeResult(
        metadata={
            "layer": "warehouse",
            "tool": "dbt",
            "project_dir": str(dbt_project_dir),
            "db_path": db_path,
            "stdout_tail": result.stdout[-1000:],
        }
    )

