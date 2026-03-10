import duckdb
import os

db_path = 'artifacts/warehouse/crypto.duckdb'
conn = duckdb.connect(db_path)

print("Loading fear_greed_raw...")
conn.execute("CREATE OR REPLACE TABLE fear_greed_raw AS SELECT * FROM read_json_auto('data_lake/bronze/alternative_me/fear_greed_index/**/*.jsonl', ignore_errors=true, union_by_name=true)")
print(f"Loaded: {conn.execute('SELECT COUNT(*) FROM fear_greed_raw').fetchone()[0]} rows")
print(conn.execute('DESCRIBE fear_greed_raw').fetchall())

print("Loading global_market_raw...")
# There is only 1 day of global_market_raw but let's load it anyway
conn.execute("CREATE OR REPLACE TABLE global_market_raw AS SELECT * FROM read_json_auto('data_lake/bronze/coingecko/global_market/**/*.jsonl', ignore_errors=true, union_by_name=true)")

print("Loading macro_rates_raw...")
conn.execute("CREATE OR REPLACE TABLE macro_rates_raw AS SELECT * FROM read_json_auto('data_lake/bronze/fred/macro_rates/**/*.jsonl', ignore_errors=true, union_by_name=true)")

print("Loading macro_assets_raw...")
# Need to make sure macro_assets_raw exists even if empty
conn.execute("CREATE TABLE IF NOT EXISTS macro_assets_raw (event_time VARCHAR, sp500_close DOUBLE, oil_wti_usd DOUBLE)")

print("Loading fed_calendar_raw...")
conn.execute("CREATE OR REPLACE TABLE fed_calendar_raw AS SELECT * FROM read_json_auto('data_lake/bronze/fed_calendar/decision_dates/**/*.jsonl', ignore_errors=true, union_by_name=true)")

conn.close()
