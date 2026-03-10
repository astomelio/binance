import duckdb
import os
db_path = "artifacts/warehouse/crypto.duckdb"
if not os.path.exists(db_path):
    print("ERROR: DB no existe")
    exit(1)
con = duckdb.connect(db_path)
print("--- ESTADO DUCKDB ---")
try:
    res = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()
    for row in res:
        t = row[0]
        c = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"TABLE: {t} | ROWS: {c}")
except Exception as e:
    print("Error:", e)
con.close()
