import duckdb
import glob
import os

db_path = 'artifacts/warehouse/crypto.duckdb'
conn = duckdb.connect(db_path)

print("Loading fear_greed_raw in chunks...")
all_files = glob.glob('data_lake/bronze/alternative_me/fear_greed_index/**/*.jsonl', recursive=True)
print(f"Total files: {len(all_files)}")

# Create table with first file to define schema
if all_files:
    conn.execute(f"CREATE OR REPLACE TABLE fear_greed_raw AS SELECT * FROM read_json_auto('{all_files[0]}', union_by_name=true)")
    
    # Load in chunks of 1000 files
    chunk_size = 1000
    for i in range(0, len(all_files), chunk_size):
        chunk = all_files[i:i+chunk_size]
        print(f"Loading chunk {i//chunk_size + 1}...")
        conn.execute(f"INSERT INTO fear_greed_raw SELECT * FROM read_json_auto({chunk}, union_by_name=true)")

print(f"Total rows: {conn.execute('SELECT COUNT(*) FROM fear_greed_raw').fetchone()[0]}")
conn.close()
