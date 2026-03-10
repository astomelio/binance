"""
Data completeness check for DuckDB warehouse.
Run from repo root: python scripts/check_data_status.py
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

import duckdb

db_path = os.environ.get("DBT_DUCKDB_PATH") or str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb")
if not os.path.isabs(db_path):
    db_path = str((REPO_ROOT / db_path).resolve())
if not os.path.exists(db_path):
    print(f"Error: {db_path} not found.")
    sys.exit(1)

conn = duckdb.connect(db_path)

def check_table(table_name, symbol_col='symbol', time_col='event_time'):
    try:
        r = conn.execute(f"SELECT COUNT(1), MIN({time_col}), MAX({time_col}) FROM {table_name}").fetchone()
        print(f"Table {table_name}: {r[0]} rows, from {r[1]} to {r[2]}")
        
        if symbol_col:
            syms = conn.execute(f"SELECT COUNT(DISTINCT {symbol_col}) FROM {table_name}").fetchone()[0]
            print(f"  - Distinct {symbol_col}s: {syms}")
            
            if syms > 0:
                btc = conn.execute(f"SELECT COUNT(1) FROM {table_name} WHERE {symbol_col}='BTCUSDT'").fetchone()[0]
                print(f"  - BTCUSDT rows: {btc}")
    except Exception as e:
        print(f"Error checking {table_name}: {e}")

print("=== Data Completeness Check ===")
check_table('market_snapshot_raw')
check_table('derivatives_snapshot_raw')
check_table('fear_greed_raw', symbol_col=None)
check_table('br_macro_context', symbol_col=None)
check_table('slv_decision_features')
# Gold layer (if dbt ran)
try:
    conn.execute("SELECT 1 FROM decision_features LIMIT 1")
    check_table('decision_features')
except Exception:
    print("Table decision_features: not present (dbt gold not run or different alias)")

print("\n=== Summary ===")
conn.close()
