import duckdb
import os

db_path = 'artifacts/warehouse/crypto.duckdb'
if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = duckdb.connect(db_path)
try:
    res = conn.execute("SELECT model_id, COUNT(*), SUM(realized_pnl) FROM fct_order_history GROUP BY model_id").fetchall()
    for row in res:
        print(f"Model: {row[0]}, Count: {row[1]}, Total PnL: {row[2]}")
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
