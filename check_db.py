import duckdb
con = duckdb.connect('/app/artifacts/warehouse/crypto.duckdb')
res = con.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'aster_dex_raw'").fetchall()
print([r[0] for r in res])
