import sqlite3
import os

db_path = 'artifacts/dagster/history/runs.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT run_id, pipeline_name, status FROM runs WHERE status IN ('STARTED', 'STARTING')")
rows = cur.fetchall()

print(f"Active runs: {len(rows)}")
for rid, pname, status in rows:
    print(f"[{status}] {rid}: {pname}")

conn.close()
