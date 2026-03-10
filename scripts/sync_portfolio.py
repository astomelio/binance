import os
import duckdb
import pandas as pd
import logging
from pathlib import Path
import sys
from datetime import datetime, timezone

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))
from trading_lib.api_client import BinanceConnectorClient
from trading_lib.hl_client import HyperliquidTestnetClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sync_portfolio(db_path: str):
    """
    Fetches real-time portfolio data from all exchanges and syncs it to DuckDB.
    Source of truth for positions, balances, and PnL.
    """
    conn = duckdb.connect(db_path)
    ts = datetime.now(timezone.utc).isoformat()
    
    portfolio_records = []
    
    # 1. Sync Binance
    try:
        binance = BinanceConnectorClient()
        # Balance
        balances = binance.get_futures_account_balance()
        usdt_bal = next((b for b in balances if b['asset'] == 'USDT'), None)
        if usdt_bal:
            portfolio_records.append({
                'event_time': ts,
                'exchange': 'binance',
                'asset': 'USDT',
                'symbol': None,
                'position_side': None,
                'entry_price': 0.0,
                'mark_price': 0.0,
                'quantity': float(usdt_bal['wallet_balance']),
                'unrealized_pnl': 0.0,
                'liquidation_price': 0.0,
                'type': 'BALANCE'
            })
            
        # Positions
        positions = binance.get_futures_positions()
        for p in positions:
            qty = float(p.get('positionAmt', 0))
            if qty != 0:
                portfolio_records.append({
                    'event_time': ts,
                    'exchange': 'binance',
                    'asset': p['symbol'].replace('USDT', ''),
                    'symbol': p['symbol'],
                    'position_side': 'LONG' if qty > 0 else 'SHORT',
                    'entry_price': float(p.get('entryPrice', 0)),
                    'mark_price': float(p.get('markPrice', 0)),
                    'quantity': abs(qty),
                    'unrealized_pnl': float(p.get('unRealizedProfit', 0)),
                    'liquidation_price': float(p.get('liquidationPrice', 0)),
                    'type': 'POSITION'
                })
        logger.info(f"Binance sync complete: {len(positions)} positions tracked.")
    except Exception as e:
        logger.error(f"Error syncing Binance: {e}")

    # 2. Sync Hyperliquid
    try:
        hl = HyperliquidTestnetClient()
        # Note: HL client currently lacks a generic get_positions/balance in the wrapper
        # For now, we skip detailed HL sync until wrapper is expanded, 
        # or we just log that we are in mirror mode.
        logger.info("Hyperliquid sync (placeholder): Operating in mirror mode.")
    except Exception as e:
        logger.error(f"Error syncing Hyperliquid: {e}")

    # 3. Save to DuckDB
    if portfolio_records:
        df = pd.DataFrame(portfolio_records)
        conn.execute("CREATE TABLE IF NOT EXISTS fct_live_portfolio (event_time TIMESTAMP, exchange VARCHAR, asset VARCHAR, symbol VARCHAR, position_side VARCHAR, entry_price DOUBLE, mark_price DOUBLE, quantity DOUBLE, unrealized_pnl DOUBLE, liquidation_price DOUBLE, type VARCHAR)")
        
        # We replace the state every time (Snapshot strategy)
        conn.execute("DELETE FROM fct_live_portfolio")
        conn.register('temp_portfolio', df)
        conn.execute("INSERT INTO fct_live_portfolio SELECT * FROM temp_portfolio")
        logger.info(f"Updated fct_live_portfolio with {len(df)} records.")
    
    conn.close()

if __name__ == "__main__":
    db_path = os.environ.get("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
    sync_portfolio(db_path)
