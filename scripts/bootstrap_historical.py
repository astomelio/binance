#!/usr/bin/env python3
"""
Bootstrap script to initialize the Data Lake and Warehouse on a new device.
This will fetch ~3 years (1095 days) of historical data from all sources.

Usage:
    python scripts/bootstrap_historical.py
    python scripts/bootstrap_historical.py --symbols BTCUSDT,ETHUSDT
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

def _venv_python() -> str:
    for p in [REPO_ROOT / "venv" / "Scripts" / "python.exe", REPO_ROOT / "venv" / "bin" / "python"]:
        if p.exists():
            return str(p)
    return sys.executable

def _run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> int:
    env = env or {}
    full = {**os.environ, **env}
    full.setdefault("LAKE_ROOT", str(REPO_ROOT / "data_lake"))
    full.setdefault("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))
    
    print(f"\n> Running: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(cwd or REPO_ROOT), env=full).returncode

def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap historical data for a new device")
    parser.add_argument("--days", type=int, default=1095, help="Days of history (default 1095)")
    parser.add_argument("--interval", type=str, default="1h", help="Kline interval (1m, 15m, 1h, 1d)")
    parser.add_argument("--symbols", type=str, help="Symbols to backfill (default from DP_SYMBOLS or all)")
    parser.add_argument("--skip-external", action="store_true", help="Skip external sources backfill")
    args = parser.parse_args()

    python = _venv_python()
    
    # 1. Environment check
    print("=== [1/5] Environment Setup ===")
    (REPO_ROOT / "data_lake").mkdir(exist_ok=True)
    (REPO_ROOT / "artifacts" / "warehouse").mkdir(parents=True, exist_ok=True)
    
    env_vars = {}
    if args.symbols:
        env_vars["DP_SYMBOLS"] = args.symbols
        print(f"Using symbols: {args.symbols}")

    # 2. Binance Historical (API)
    print(f"\n=== [2/5] Backfilling Binance Historical (~{args.days} days, interval {args.interval}) ===")
    # Note: Using backfill_bronze_historical instead of vision because it's more comprehensive 
    # for all exchange sources defined in the medallion architecture.
    res = _run([python, "-m", "data_platform.backfill_bronze_historical", "--days", str(args.days), "--interval", args.interval], env=env_vars)
    if res != 0:
        print("[FAIL] Binance backfill failed")
        return res

    # 3. External Sources (FearGreed, FRED, FED, etc.)
    if not args.skip_external:
        print("\n=== [3/5] Backfilling External Sources (FRED, FearGreed, FED) ===")
        res = _run([python, "-m", "data_platform.backfill_external_sources"], env=env_vars)
        if res != 0:
            print("[WARN] External sources backfill failed")
            # We continue even if external fails, as binance data is the core
    
    # 4. Load to DuckDB
    print("\n=== [4/5] Loading Bronze to DuckDB ===")
    # Using the same logic as 'make warehouse-load'
    db_path = str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb")
    db_path_posix = db_path.replace("\\", "/")
    load_code = f"""
from data_platform.config import DataPlatformConfig
from data_platform.loaders.bronze_to_duckdb import load_bronze_to_duckdb
import os
cfg = DataPlatformConfig()
db_path = '{db_path_posix}'
counts = load_bronze_to_duckdb(cfg, db_path)
print('Loaded records:', counts)
"""
    res = _run([python, "-c", load_code], env=env_vars)
    if res != 0:
        print("[FAIL] Warehouse load failed")
        return res

    # 5. DBT Transformation
    print("\n=== [5/5] Running DBT Transformations (Silver & Gold) ===")
    dbt_dir = REPO_ROOT / "data_platform" / "dbt"
    dbt_exe = REPO_ROOT / "venv" / "Scripts" / "dbt.exe" if os.name == "nt" else REPO_ROOT / "venv" / "bin" / "dbt"
    dbt_cmd = str(dbt_exe) if dbt_exe.exists() else "dbt"
    
    res = _run([dbt_cmd, "run", "--target", "local", "--profiles-dir", "."], cwd=dbt_dir, env=env_vars)
    if res != 0:
        print("[FAIL] DBT run failed")
        return res

    print("\n" + "="*60)
    print("[OK] BOOTSTRAP COMPLETE")
    print(f"Data lake and warehouse initialized with {args.days} days of history.")
    print(f"DuckDB location: {db_path}")
    print("="*60)
    return 0

if __name__ == "__main__":
    sys.exit(main())
