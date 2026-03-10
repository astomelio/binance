import duckdb
import os

c = duckdb.connect(os.environ.get('DBT_DUCKDB_PATH', 'artifacts/warehouse/crypto.duckdb'))

print("--- slv_decision_features info ---")
print(c.execute("SELECT table_type FROM information_schema.tables WHERE table_name='slv_decision_features'").fetchone())
