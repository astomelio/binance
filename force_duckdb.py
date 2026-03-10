import sys
sys.path.append('/app')
import duckdb
from data_platform.config import DataPlatformConfig
from data_platform.loaders.bronze_to_duckdb import load_bronze_to_duckdb

db_path = '/app/artifacts/warehouse/crypto.duckdb'
con = duckdb.connect(db_path, read_only=False)

# Borramos las tablas que fallaron por schemas vacíos o fallbacks rotos
con.execute('DROP TABLE IF EXISTS main.fed_calendar_raw;')
con.execute('DROP TABLE IF EXISTS main.derivatives_snapshot_raw;')
con.execute('DROP TABLE IF EXISTS main.derivatives_flow_raw;')
con.execute('DROP TABLE IF EXISTS main.cross_exchange_snapshot_raw;')

# Limpiamos el historial para forzar re-ingesta total
try:
    con.execute("DELETE FROM main._loaded_files WHERE file_path LIKE '%fed_calendar%'")
    con.execute("DELETE FROM main._loaded_files WHERE file_path LIKE '%derivatives%'")
    con.execute("DELETE FROM main._loaded_files WHERE file_path LIKE '%cross_exchange%'")
except Exception as e:
    pass
con.close()

# Volvemos a correr la ingesta genérica para estas que acabamos de borrar
cfg = DataPlatformConfig(lake_root='/app/artifacts/data_lake')
load_bronze_to_duckdb(cfg, db_path)
print("Tablas restantes arregladas.")
