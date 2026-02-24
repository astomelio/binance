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


@asset(
    group_name="crypto_lake_ml",
    deps=[warehouse_dbt_build],
    description="Entrena modelo LightGBM con decision_features, registra en MLflow y ejecuta backtest.",
)
def quant_model_train(context) -> MaterializeResult:
    """Ejecuta scripts/auto_train_eval.py (datos ya actualizados por warehouse_dbt_build)."""
    repo_root = Path(__file__).resolve().parents[3]
    db_path_env = os.getenv("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
    db_path = str((repo_root / db_path_env).resolve()) if not Path(db_path_env).is_absolute() else db_path_env
    script = repo_root / "scripts" / "auto_train_eval.py"
    python_exec = Path(sys.executable).resolve()
    cmd = [str(python_exec), str(script), "--set-champion"]
    env = dict(os.environ)
    env["DBT_DUCKDB_PATH"] = db_path
    env["PYTHONPATH"] = str(repo_root)
    result = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, env=env, timeout=3600)
    if result.returncode != 0:
        raise RuntimeError(
            "quant_model_train failed: "
            f"stdout={result.stdout[-1500:]!r} "
            f"stderr={result.stderr[-1500:]!r}"
        )
    report_path = repo_root / "artifacts" / "quant_model" / "auto_report.json"
    report_data = {}
    if report_path.exists():
        import json
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
    return MaterializeResult(
        metadata={
            "layer": "ml",
            "script": str(script),
            "db_path": db_path,
            "backtest_net_pct": report_data.get("backtest", {}).get("net_return_percent"),
            "trades_count": report_data.get("backtest", {}).get("trades_count"),
            "stdout_tail": result.stdout[-800:],
        }
    )


@asset(
    group_name="crypto_lake_ml",
    description="Un ciclo de la suite de agentes quant: tuning → decisión → informe → evolución (champion). Usa los datos ya cargados en DuckDB.",
)
def quant_suite_cycle(context) -> MaterializeResult:
    """Ejecuta scripts/run_suite_cycle.py; persiste estado e informe en artifacts/quant_model/."""
    repo_root = Path(__file__).resolve().parents[3]
    db_path_env = os.getenv("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
    db_path = str((repo_root / db_path_env).resolve()) if not Path(db_path_env).is_absolute() else db_path_env
    script = repo_root / "scripts" / "run_suite_cycle.py"
    python_exec = Path(sys.executable).resolve()
    cmd = [str(python_exec), str(script), "--horizon", "4h", "--lookback-days", "90"]
    env = dict(os.environ)
    env["DBT_DUCKDB_PATH"] = db_path
    env["PYTHONPATH"] = str(repo_root)
    result = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, env=env, timeout=3600)
    if result.returncode != 0:
        raise RuntimeError(
            "quant_suite_cycle failed: "
            f"stdout={result.stdout[-1500:]!r} "
            f"stderr={result.stderr[-1500:]!r}"
        )
    state_path = repo_root / "artifacts" / "quant_model" / "suite_state.json"
    report_data = {}
    if state_path.exists():
        import json
        report_data = json.loads(state_path.read_text(encoding="utf-8"))
    return MaterializeResult(
        metadata={
            "layer": "ml",
            "script": str(script),
            "db_path": db_path,
            "champion_id": report_data.get("champion_id"),
            "champion_version": report_data.get("version"),
            "stdout_tail": result.stdout[-800:],
        }
    )

