#!/usr/bin/env python3
"""
Flujo automatizable de agentes AI: data → warehouse → train → explorer → evaluation.
Para cron, Dagster, o ejecución manual.

Usage:
    python scripts/run_agent_flow.py --steps data
    python scripts/run_agent_flow.py --steps train
    python scripts/run_agent_flow.py --steps all
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _venv_python() -> str:
    root = _project_root()
    for candidate in [
        root / "venv" / "Scripts" / "python.exe",
        root / "venv" / "bin" / "python",
    ]:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _run(cmd: list[str], cwd: Path, env: dict | None = None) -> int:
    env = env or {}
    full_env = {**os.environ, **env}
    full_env.setdefault("LAKE_ROOT", str(cwd / "data_lake"))
    full_env.setdefault("DBT_DUCKDB_PATH", str(cwd / "artifacts" / "warehouse" / "crypto.duckdb"))
    result = subprocess.run(cmd, cwd=str(cwd), env=full_env)
    return result.returncode


def step_backfill_external(cwd: Path, python: str) -> int:
    print("\n[1/1] Backfill external sources (FRED, Fear&Greed, CoinGecko, FED, Glassnode)...")
    return _run([python, "-m", "data_platform.backfill_external_sources"], cwd)


def step_warehouse_load(cwd: Path, python: str) -> int:
    print("\n[1/2] Load bronze -> DuckDB...")
    code = _run(
        [python, "-c", """
from data_platform.config import DataPlatformConfig
from data_platform.loaders.bronze_to_duckdb import load_bronze_to_duckdb
import os
cfg = DataPlatformConfig()
db_path = os.environ.get('DBT_DUCKDB_PATH', 'artifacts/warehouse/crypto.duckdb')
if not os.path.isabs(db_path):
    db_path = os.path.join(os.getcwd(), db_path)
counts = load_bronze_to_duckdb(cfg, db_path)
print('Loaded:', counts)
"""],
        cwd,
    )
    if code != 0:
        return code
    print("\n[2/2] dbt run...")
    dbt_dir = cwd / "data_platform" / "dbt"
    venv_dbt = cwd / "venv" / "bin" / "dbt"
    if not venv_dbt.exists():
        venv_dbt = cwd / "venv" / "Scripts" / "dbt.exe"
    dbt_cmd = str(venv_dbt) if venv_dbt.exists() else "dbt"
    return _run(
        [dbt_cmd, "run", "--target", "local", "--profiles-dir", "."],
        dbt_dir,
        {"DBT_DUCKDB_PATH": str(cwd / "artifacts" / "warehouse" / "crypto.duckdb")},
    )


def step_train(cwd: Path, python: str, trials: int = 50) -> int:
    print("\n[1/1] Optuna tuning (LightGBM)...")
    return _run(
        [
            python,
            "examples/quant_optuna_tuning.py",
            "--trials", str(trials),
            "--mlflow-uri", f"sqlite:///{cwd}/artifacts/quant_model/mlflow.db",
            "--mlflow-experiment", "quant-optuna",
            "--register-model-name", "quant_alpha_entry_lgbm",
        ],
        cwd,
    )


def step_explorer(cwd: Path, python: str, mode: str = "quick") -> int:
    print(f"\n[1/1] Explorer agent ({mode})...")
    return _run(
        [python, "examples/ai_explorer_agent.py", mode],
        cwd,
    )


def step_model_eval(cwd: Path, python: str) -> int:
    print("\n[1/1] Model evaluation (LightGBM vs XGBoost vs mean reversion)...")
    dataset = cwd / "data_lake" / "gold" / "signals" / "decision_features_backfill"
    return _run(
        [python, "examples/quant_model_evaluation.py", "--dataset", str(dataset)],
        cwd,
    )


def main():
    parser = argparse.ArgumentParser(description="Run agent flows for AI models")
    parser.add_argument(
        "--steps",
        choices=["data", "train", "explorer", "eval", "all"],
        default="all",
        help="data=backfill+warehouse, train=optuna, explorer=ExplorationAgent, eval=model evaluation, all=full flow",
    )
    parser.add_argument("--trials", type=int, default=50, help="Optuna trials for train step")
    parser.add_argument("--explorer-mode", default="quick", choices=["quick", "grid", "full"])
    parser.add_argument("--skip-data", action="store_true", help="Skip data step when using all")
    args = parser.parse_args()

    cwd = _project_root()
    python = _venv_python()
    os.chdir(cwd)

    steps = args.steps
    if steps == "all":
        steps_list = ["data", "train", "explorer", "eval"]
        if args.skip_data:
            steps_list = ["train", "explorer", "eval"]
    else:
        steps_list = [steps]

    for s in steps_list:
        if s == "data":
            code = step_backfill_external(cwd, python)
            if code != 0:
                print(f"❌ Backfill external failed (exit {code})")
                return code
            code = step_warehouse_load(cwd, python)
            if code != 0:
                print(f"❌ Warehouse load failed (exit {code})")
                return code
        elif s == "train":
            code = step_train(cwd, python, trials=args.trials)
            if code != 0:
                print(f"❌ Train failed (exit {code})")
                return code
        elif s == "explorer":
            code = step_explorer(cwd, python, mode=args.explorer_mode)
            if code != 0:
                print(f"❌ Explorer failed (exit {code})")
                return code
        elif s == "eval":
            code = step_model_eval(cwd, python)
            if code != 0:
                print(f"❌ Model eval failed (exit {code})")
                return code

    print("\n✅ Agent flow completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
