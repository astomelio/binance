import sqlite3
import os
import json
import time

run_id = '13894d60-aa7e-4cec-8ce0-b7c72bcf9817'
db_path = f'artifacts/dagster/history/runs/{run_id}.db'

if not os.path.exists(db_path):
    print(f"Error: {db_path} not found")
    exit(1)

conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT dagster_event_type, event FROM event_logs ORDER BY timestamp DESC LIMIT 20")
rows = cur.fetchall()

print(f"Latest 20 events for run {run_id}:")
for etype, event_json in rows:
    event_data = json.loads(event_json)
    ts = event_data.get('timestamp')
    msg = event_data.get('message', '')
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(ts))}] {etype}: {msg}")

conn.close()
