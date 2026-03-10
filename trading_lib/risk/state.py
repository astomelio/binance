import os
import duckdb
import pandas as pd
from datetime import datetime
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")

def get_historical_peak(current_capital: float) -> float:
    """Gets the historical peak capital from DuckDB. If current_capital is higher, updates the peak."""
    try:
        conn = duckdb.connect(DB_PATH)
        
        # Create table if it doesn't exist
        conn.execute("""
            CREATE TABLE IF NOT EXISTS risk_engine_state (
                id INTEGER PRIMARY KEY,
                historical_peak_capital DOUBLE,
                last_updated TIMESTAMP
            )
        """)
        
        # Check if row exists
        result = conn.execute("SELECT historical_peak_capital FROM risk_engine_state WHERE id = 1").fetchone()
        
        if result:
            historical_peak = result[0]
            if current_capital > historical_peak:
                logger.info(f"New ATH! Updating historical peak from {historical_peak} to {current_capital}")
                historical_peak = current_capital
                conn.execute(f"UPDATE risk_engine_state SET historical_peak_capital = {historical_peak}, last_updated = CURRENT_TIMESTAMP WHERE id = 1")
        else:
            logger.info(f"Initializing historical peak with current capital: {current_capital}")
            historical_peak = current_capital
            conn.execute(f"INSERT INTO risk_engine_state (id, historical_peak_capital, last_updated) VALUES (1, {historical_peak}, CURRENT_TIMESTAMP)")
            
        conn.close()
        return historical_peak
        
    except Exception as e:
        logger.error(f"Error managing historical peak in DuckDB: {e}")
        return current_capital

if __name__ == "__main__":
    peak = get_historical_peak(10000)
    print(f"Current peak: {peak}")
