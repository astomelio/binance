#!/usr/bin/env python3
"""
Reload external sources (Fear&Greed, FRED, FED) into the data lake, load to DuckDB, and run dbt.
Use after bootstrap if fear_greed_raw / br_macro_context are empty or stale so that
slv_decision_features and decision_features get full history.

Run from repo root: python scripts/reload_external_and_dbt.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

def _run(cmd: list, cwd: Path | None = None) -> int:
    env = {**os.environ}
    env.setdefault("LAKE_ROOT", str(REPO_ROOT / "data_lake"))
    env.setdefault("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))
    return subprocess.run(cmd, cwd=str(cwd or REPO_ROOT), env=env).returncode

def main() -> int:
    python = sys.executable
    db_path = REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    print("=== [1/3] Backfilling external sources (Fear&Greed, FRED, FED) ===")
    if _run([python, "-m", "data_platform.backfill_external_sources"]) != 0:
        print("[WARN] External backfill had errors; continuing.")
    print("\n=== [2/3] Loading bronze to DuckDB ===")
    load_code = """
from data_platform.config import DataPlatformConfig
from data_platform.loaders.bronze_to_duckdb import load_bronze_to_duckdb
cfg = DataPlatformConfig()
db_path = r'""" + str(db_path).replace("\\", "/") + """'
counts = load_bronze_to_duckdb(cfg, db_path)
print('Loaded:', counts)
"""
    if _run([python, "-c", load_code]) != 0:
        print("[FAIL] Warehouse load failed")
        return 1
    print("\n=== [3/3] Running dbt (Silver & Gold) ===")
    dbt_dir = REPO_ROOT / "data_platform" / "dbt"
    # Usar el Python actual (venv) para evitar fallo del launcher dbt.exe con rutas antiguas (OneDrive, etc.)
    if _run([python, "-m", "dbt", "run", "--target", "local", "--profiles-dir", "."], cwd=dbt_dir) != 0:
        print("[FAIL] dbt run failed")
        return 1
    print("\n[OK] External data reload and dbt complete.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
