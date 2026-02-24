#!/usr/bin/env python3
"""
Para que el training sea automático con datos frescos: primero se ejecutan
los pipelines de datos (bronze + carga a DuckDB + dbt) y después el entrenamiento.
Un solo cron puede ejecutar este script: datos al día y luego modelo nuevo.

Uso:
  python scripts/auto_data_then_train.py
  python scripts/auto_data_then_train.py --skip-data   # solo training (datos ya actualizados)
  python scripts/auto_data_then_train.py --data-only   # solo pipelines datos, sin entrenar
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _venv_python() -> str:
    for p in [REPO_ROOT / "venv" / "Scripts" / "python.exe", REPO_ROOT / "venv" / "bin" / "python"]:
        if p.exists():
            return str(p)
    return sys.executable


def _run(cmd: list[str], cwd: Path, env: dict | None = None) -> int:
    env = env or {}
    full = {**os.environ, **env}
    full.setdefault("LAKE_ROOT", str(REPO_ROOT / "data_lake"))
    full.setdefault("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))
    return subprocess.run(cmd, cwd=str(cwd), env=full).returncode


def step_bronze(python: str) -> int:
    """Refresco bronze: APIs (Binance, Bybit, OKX, FearGreed, etc.) -> data_lake/bronze."""
    print("\n[datos 1/3] Bronze: trayendo datos recientes de APIs...")
    return _run([python, "-m", "data_platform.pipeline", "--mode", "bronze"], REPO_ROOT)


def step_warehouse_load(python: str) -> int:
    """Carga bronze -> DuckDB y ejecuta dbt (decision_features actualizadas)."""
    print("\n[datos 2/3] Cargando bronze -> DuckDB...")
    code = _run(
        [python, "-c", """
from data_platform.config import DataPlatformConfig
from data_platform.loaders.bronze_to_duckdb import load_bronze_to_duckdb
import os
cfg = DataPlatformConfig()
db_path = os.environ.get('DBT_DUCKDB_PATH', 'artifacts/warehouse/crypto.duckdb')
if not os.path.isabs(db_path):
    db_path = os.path.join(os.getcwd(), db_path)
c = load_bronze_to_duckdb(cfg, db_path)
print('Loaded:', c)
"""],
        REPO_ROOT,
    )
    if code != 0:
        return code
    print("\n[datos 3/3] dbt run (decision_features)...")
    dbt_dir = REPO_ROOT / "data_platform" / "dbt"
    dbt = REPO_ROOT / "venv" / "bin" / "dbt"
    if not dbt.exists():
        dbt = REPO_ROOT / "venv" / "Scripts" / "dbt.exe"
    dbt_cmd = str(dbt) if dbt.exists() else "dbt"
    return _run(
        [dbt_cmd, "run", "--target", "local", "--profiles-dir", "."],
        dbt_dir,
        {"DBT_DUCKDB_PATH": str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb")},
    )


def step_train(python: str, set_champion: bool) -> int:
    """Entrenar modelo y opcionalmente marcar champion."""
    print("\n[training] auto_train_eval.py...")
    cmd = [python, str(REPO_ROOT / "scripts" / "auto_train_eval.py")]
    if set_champion:
        cmd.append("--set-champion")
    return _run(cmd, REPO_ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ejecutar pipelines de datos y luego training (para cron)."
    )
    parser.add_argument(
        "--skip-data",
        action="store_true",
        help="No ejecutar datos; solo training (si ya corriste datos antes).",
    )
    parser.add_argument(
        "--data-only",
        action="store_true",
        help="Solo pipelines datos; no entrenar.",
    )
    parser.add_argument("--set-champion", action="store_true", help="Marcar nuevo modelo como champion.")
    args = parser.parse_args()

    python = _venv_python()
    os.chdir(REPO_ROOT)

    if not args.skip_data:
        if step_bronze(python) != 0:
            print("❌ Bronze falló")
            return 1
        if step_warehouse_load(python) != 0:
            print("❌ Warehouse load falló")
            return 1
        print("✅ Datos actualizados (bronze + DuckDB + dbt)")
    if args.data_only:
        return 0

    if step_train(python, args.set_champion) != 0:
        print("❌ Training falló")
        return 1
    print("✅ Training terminado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
