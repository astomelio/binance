import glob as _glob
import logging
import os
import time
from pathlib import Path
from typing import Dict, List

import duckdb

from data_platform.config import DataPlatformConfig

logger = logging.getLogger(__name__)


def load_bronze_to_duckdb(
    cfg: DataPlatformConfig,
    db_path: str,
    *,
    schema: str = "main",
    tables_only: List[str] | None = None,
) -> Dict[str, int]:
    lake_root = cfg.lake_root
    LOAD_BATCH_SIZE = 1000

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    con = None
    for attempt in range(12):
        try:
            con = duckdb.connect(db_path)
            break
        except Exception as e:
            if "Could not set lock on file" in str(e) or "Conflicting lock" in str(e):
                logger.warning(f"DuckDB lock held, waiting 5s... (attempt {attempt+1}/12)")
                time.sleep(5)
            else:
                raise
    if not con:
        raise RuntimeError("Failed to acquire DuckDB lock after 1 minute.")
    
    loaded_files = set()
    
    try:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        
        datasets = {
            "market_snapshot_raw": [
                f"{lake_root}/bronze/binance_local_api/market_snapshot/**/*part-*.jsonl",
                f"{lake_root}/bronze/binance_historical/market_snapshot/**/*part-*.jsonl",
                f"{lake_root}/bronze/binance_vision/market_snapshot/**/*part-*.jsonl",
            ],
            "derivatives_snapshot_raw": [
                f"{lake_root}/bronze/binance_public/derivatives_snapshot/**/*part-*.jsonl",
                f"{lake_root}/bronze/binance_historical/derivatives_snapshot/**/*part-*.jsonl",
                f"{lake_root}/bronze/binance_vision/derivatives_snapshot/**/*part-*.jsonl",
            ],
            "derivatives_flow_raw": [
                f"{lake_root}/bronze/binance_public/derivatives_flow/**/*part-*.jsonl",
                f"{lake_root}/bronze/binance_historical/derivatives_flow/**/*part-*.jsonl",
                f"{lake_root}/bronze/binance_vision/derivatives_flow/**/*part-*.jsonl",
            ],
            "cross_exchange_snapshot_raw": [
                f"{lake_root}/bronze/bybit_public/futures_snapshot/**/*part-*.jsonl",
                f"{lake_root}/bronze/okx_public/futures_snapshot/**/*part-*.jsonl",
                f"{lake_root}/bronze/bybit_historical/futures_snapshot/**/*part-*.jsonl",
                f"{lake_root}/bronze/okx_historical/futures_snapshot/**/*part-*.jsonl",
            ],
            "dex_snapshot_raw": [
                f"{lake_root}/bronze/dexscreener/dex_snapshot/**/*part-*.jsonl",
                f"{lake_root}/bronze/dexscreener_historical/dex_snapshot/**/*part-*.jsonl",
            ],
            "global_market_raw": [
                f"{lake_root}/bronze/coingecko/global_market/**/*part-*.jsonl",
            ],
            "fear_greed_raw": [
                f"{lake_root}/bronze/alternative_me/fear_greed_index/**/*part-*.jsonl",
                f"{lake_root}/bronze/alternative_me_historical/fear_greed_index/**/*part-*.jsonl",
            ],
            "macro_rates_raw": [
                f"{lake_root}/bronze/fred/macro_rates/**/*part-*.jsonl",
                f"{lake_root}/bronze/fred_historical/macro_rates/**/*part-*.jsonl",
            ],
            "macro_assets_raw": [
                f"{lake_root}/bronze/fred_historical/macro_assets/**/*part-*.jsonl",
            ],
            "fed_calendar_raw": [
                f"{lake_root}/bronze/fed_calendar/decision_dates/**/*part-*.jsonl",
                f"{lake_root}/bronze/fed_calendar_historical/decision_dates/**/*part-*.jsonl",
            ],
            "hyperliquid_raw": [
                f"{lake_root}/bronze/hyperliquid/meta_and_ctx/**/*part-*.jsonl",
            ],
            "aster_dex_raw": [
                f"{lake_root}/bronze/aster_dex/futures_snapshot/**/*part-*.jsonl",
            ],
        }

        counts: Dict[str, int] = {}
        
        try:
            con.execute(f"CREATE TABLE IF NOT EXISTS {schema}._loaded_files (file_path VARCHAR PRIMARY KEY, loaded_at TIMESTAMP)")
            loaded_files_result = con.execute(f"SELECT file_path FROM {schema}._loaded_files").fetchall()
            loaded_files = {row[0] for row in loaded_files_result}
        except Exception as e:
            print(f"Error inicializando _loaded_files: {e}")
            
        for table_name, patterns in datasets.items():
            if tables_only and table_name not in tables_only:
                continue
                
            print(f"Ingestando {table_name}...")
            all_files = []
            is_initial_load = len(loaded_files) < 1000 
            
            for p in patterns:
                if is_initial_load:
                    all_files.extend(_glob.glob(p, recursive=True))
                else:
                    base_path = p.replace("/**/*part-*.jsonl", "")
                    from datetime import datetime, timedelta
                    today = datetime.now()
                    yesterday = today - timedelta(days=1)
                    
                    for dt in [yesterday, today]:
                        date_str = dt.strftime("%Y-%m-%d")
                        p_fast = f"{base_path}/{date_str}/*part-*.jsonl"
                        all_files.extend(_glob.glob(p_fast))
                    
                    if not all_files:
                         all_files.extend(_glob.glob(p.replace("/**/", "/*/")))
            
            # SI NO HAY ARCHIVOS, CREA LA ESTRUCTURA QUE DBT ESPERA PARA QUE NO FALLE BINDER
            if not all_files:
                print(f"  Aviso: No se encontraron archivos para {table_name}")
                try:
                    table_exists_chk = con.execute(f"SELECT count(*) FROM information_schema.tables WHERE table_schema = '{schema}' AND table_name = '{table_name}'").fetchone()[0] > 0
                    if not table_exists_chk:
                        if table_name == "global_market_raw":
                            con.execute(f"CREATE TABLE {schema}.{table_name} (event_time VARCHAR, payload JSON, symbol VARCHAR)")
                        elif table_name == "market_snapshot_raw":
                            con.execute(f"CREATE TABLE {schema}.{table_name} (event_time VARCHAR, symbol VARCHAR, spot_ticker JSON, futures_ticker JSON)")
                        elif table_name == "fed_calendar_raw":
                            con.execute(f"CREATE TABLE {schema}.{table_name} (event_time VARCHAR, dt VARCHAR, event VARCHAR)")
                        elif table_name == "macro_rates_raw":
                            con.execute(f"CREATE TABLE {schema}.{table_name} (event_time VARCHAR, fed_funds_rate DOUBLE)")
                        elif table_name == "macro_assets_raw":
                            con.execute(f"CREATE TABLE {schema}.{table_name} (event_time VARCHAR, event_date VARCHAR, sp500_close DOUBLE, oil_wti_usd DOUBLE)")
                        elif table_name == "fear_greed_raw":
                            con.execute(f"CREATE TABLE {schema}.{table_name} (event_time VARCHAR, fear_greed_value DOUBLE)")
                        elif table_name == "dex_snapshot_raw":
                            con.execute(f"CREATE TABLE {schema}.{table_name} (event_time VARCHAR, symbol VARCHAR, dex_price_usd DOUBLE, dex_liquidity_usd DOUBLE, dex_volume_24h_usd DOUBLE)")
                        elif table_name == "aster_dex_raw":
                            con.execute(f"CREATE TABLE {schema}.{table_name} (event_time VARCHAR, symbol VARCHAR, last_price DOUBLE, bid_price DOUBLE, ask_price DOUBLE, quote_volume_24h DOUBLE)")
                        elif table_name == "derivatives_snapshot_raw":
                            con.execute(f"CREATE TABLE {schema}.{table_name} (event_time VARCHAR, symbol VARCHAR, mark_price DOUBLE, index_price DOUBLE, last_funding_rate DOUBLE, open_interest DOUBLE, price_change_percent_24h DOUBLE, quote_volume_24h DOUBLE)")
                        elif table_name == "derivatives_flow_raw":
                            con.execute(f"CREATE TABLE {schema}.{table_name} (event_time VARCHAR, symbol VARCHAR, long_short_account_ratio DOUBLE, buy_sell_ratio DOUBLE, long_account DOUBLE, short_account DOUBLE, buy_vol DOUBLE, sell_vol DOUBLE)")
                        elif table_name == "cross_exchange_snapshot_raw":
                            con.execute(f"CREATE TABLE {schema}.{table_name} (event_time VARCHAR, exchange VARCHAR, symbol VARCHAR, last_price DOUBLE, bid_price DOUBLE, ask_price DOUBLE, quote_volume_24h DOUBLE)")
                        else:
                            con.execute(f"CREATE TABLE {schema}.{table_name} (event_time VARCHAR, symbol VARCHAR)")
                except Exception as e:
                    pass
                counts[table_name] = 0
                continue

            try:
                table_exists = con.execute(f"SELECT count(*) FROM information_schema.tables WHERE table_schema = '{schema}' AND table_name = '{table_name}'").fetchone()[0] > 0
                
                new_files = [f for f in all_files if Path(f).as_posix() not in loaded_files]
                max_new_files = 1000
                if len(new_files) > max_new_files:
                    new_files = new_files[:max_new_files]
                
                if not new_files:
                    print(f"  -> 0 archivos nuevos. Saltando ingestión.")
                    if table_exists:
                        counts[table_name] = con.execute(f"SELECT COUNT(*) FROM {schema}.{table_name}").fetchone()[0]
                    else:
                        counts[table_name] = 0
                    continue
                
                # Opciones fuertes de forzado para DuckDB (previene la amnesia de Schema en dicts o nulos)
                opts = "ignore_errors=true, union_by_name=true"
                if table_name == "market_snapshot_raw":
                    opts += ", columns={'event_time':'VARCHAR','symbol':'VARCHAR','spot_ticker':'JSON','futures_ticker':'JSON'}"
                elif table_name == "global_market_raw":
                    opts += ", columns={'event_time':'VARCHAR','payload':'JSON','symbol':'VARCHAR'}"
                elif table_name == "derivatives_snapshot_raw":
                    opts += ", columns={'event_time':'VARCHAR','symbol':'VARCHAR','mark_price':'DOUBLE','index_price':'DOUBLE','last_funding_rate':'DOUBLE','open_interest':'DOUBLE','price_change_percent_24h':'DOUBLE','quote_volume_24h':'DOUBLE'}"
                elif table_name == "fed_calendar_raw":
                    opts += ", columns={'event_time':'VARCHAR','dt':'VARCHAR','event':'VARCHAR'}"
                elif table_name == "derivatives_flow_raw":
                    opts += ", columns={'event_time':'VARCHAR','symbol':'VARCHAR','long_short_account_ratio':'DOUBLE','long_account':'DOUBLE','short_account':'DOUBLE','buy_sell_ratio':'DOUBLE','buy_vol':'DOUBLE','sell_vol':'DOUBLE'}"
                
                if not table_exists:
                    con.execute(f"CREATE TABLE {schema}.{table_name} AS SELECT * FROM read_json_auto({new_files[:LOAD_BATCH_SIZE]}, {opts})")
                    remaining_files = new_files[LOAD_BATCH_SIZE:]
                else:
                    remaining_files = new_files
                    
                if remaining_files:
                    for b in range(0, len(remaining_files), LOAD_BATCH_SIZE):
                        batch = remaining_files[b : b + LOAD_BATCH_SIZE]
                        con.execute(f"INSERT INTO {schema}.{table_name} SELECT * FROM read_json_auto({batch}, {opts})")
                
                if new_files:
                    con.executemany(f"INSERT INTO {schema}._loaded_files VALUES (?, CURRENT_TIMESTAMP)", [(Path(f).as_posix(),) for f in new_files])
                
                counts[table_name] = con.execute(f"SELECT COUNT(*) FROM {schema}.{table_name}").fetchone()[0]
                print(f"  -> {counts[table_name]} filas cargadas.")
            except Exception as e:
                print(f"  Error cargando {table_name}: {e}")
                counts[table_name] = 0

        # FALLBACK de Cripto Incremental - Forzando tipos JSON a Strings literales como struct workaround
        if counts.get("market_snapshot_raw", 0) == 0 and counts.get("derivatives_snapshot_raw", 0) > 0:
            print("Aplicando fallback incremental: Derivando market_snapshot de derivatives_snapshot...")
            try:
                con.execute(f"CREATE TABLE IF NOT EXISTS {schema}.market_snapshot_raw (event_time VARCHAR, symbol VARCHAR, spot_ticker JSON, futures_ticker JSON)")
                
                con.execute(f"""
                    INSERT INTO {schema}.market_snapshot_raw
                    SELECT 
                        event_time, symbol,
                        '{{"lastPrice":"' || cast(mark_price as varchar) || '", "volume":"0.0"}}'::JSON as spot_ticker,
                        '{{"lastPrice":"' || cast(mark_price as varchar) || '", "volume":"' || cast(quote_volume_24h as varchar) || '"}}'::JSON as futures_ticker
                    FROM {schema}.derivatives_snapshot_raw d
                    WHERE NOT EXISTS (
                        SELECT 1 FROM {schema}.market_snapshot_raw m 
                        WHERE m.event_time = d.event_time AND m.symbol = d.symbol
                    )
                """)
                counts["market_snapshot_raw"] = con.execute(f"SELECT COUNT(*) FROM {schema}.market_snapshot_raw").fetchone()[0]
            except Exception as e:
                print(f"Error en fallback de market_snapshot: {e}")

    finally:
        con.close()
        
    return counts
