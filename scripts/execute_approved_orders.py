import os
import duckdb
import pandas as pd
import logging
from typing import Dict, List, Optional, Tuple
import time
from pathlib import Path
import sys
import math

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))
from trading_lib.api_client import BinanceConnectorClient
from trading_lib.hl_client import HyperliquidTestnetClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Stop loss: % below entry for LONG, % above entry for SHORT (env: STOP_LOSS_PCT)
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.02"))
# Mínimo notional USD para entradas/rebalance (Binance suele pedir ~5-20; usar 25 para margen)
MIN_NOTIONAL_USD = float(os.getenv("MIN_NOTIONAL_USD", "25"))
            # Entradas en LIMIT (maker) para bajar comisiones. Offset: BUY=ask*(1-offset), SELL=bid*(1+offset)
    USE_LIMIT_ENTRY = os.getenv("USE_LIMIT_ENTRY", "false").lower() in ("true", "1", "yes")
    LIMIT_ENTRY_OFFSET_PCT = float(os.getenv("LIMIT_ENTRY_OFFSET_PCT", "0.05"))
    # Máxima desviación de precio permitida desde la aprobación (evita perseguir precios movidos)
    MAX_PRICE_DEVIATION_PCT = float(os.getenv("MAX_PRICE_DEVIATION_PCT", "1.25"))
    # Máximo tiempo permitido para una orden PENDING (evita ejecutar señales viejas)
    MAX_ORDER_AGE_MINUTES = int(os.getenv("MAX_ORDER_AGE_MINUTES", "30"))
    # Reintentos para errores de red/API (transitorios)
    EXECUTE_RETRIES = int(os.getenv("EXECUTE_RETRIES", "3"))
    EXECUTE_RETRY_DELAY = float(os.getenv("EXECUTE_RETRY_DELAY", "5"))


def _get_symbol_filters(client: BinanceConnectorClient, symbol: str) -> Tuple[float, float, float]:
    """Returns (step_size, min_qty, min_notional) for symbol."""
    try:
        info = client.get_futures_exchange_info()
        symbols = info.get("symbols", [])
        for s in symbols:
            if s.get("symbol") == symbol:
                step_size, min_qty, min_notional = 0.001, 0.001, 20.0
                for f in s.get("filters", []):
                    if f.get("filterType") == "LOT_SIZE":
                        step_size = float(f.get("stepSize", "0.001"))
                        min_qty = float(f.get("minQty", "0.001"))
                    if f.get("filterType") in ("MIN_NOTIONAL", "NOTIONAL"):
                        min_notional = float(f.get("notional", f.get("minNotional", "20")))
                return (step_size, min_qty, min_notional)
    except Exception as e:
        logger.warning(f"Could not fetch exchange info: {e}. Using defaults.")
    return (0.001, 0.001, 20.0)


def _round_quantity(quantity: float, step_size: float, min_qty: float, min_notional: float, price: float) -> Optional[float]:
    """Round quantity to valid lot size. Returns None if below minimums."""
    if quantity <= 0:
        return None
    # Round down to stepSize
    precision = 0 if step_size >= 1 else len(str(step_size).rstrip("0").split(".")[-1])
    qty = round(math.floor(quantity / step_size) * step_size, precision)
    if qty < min_qty:
        qty = min_qty
    if qty * price < min_notional:
        # Need more notional - round up to meet min
        needed_qty = min_notional / price
        qty = round(math.ceil(needed_qty / step_size) * step_size, precision)
    if qty < min_qty:
        return None
    return round(qty, precision)

def execute_pending_orders(db_path: str, dry_run: bool = False):
    """
    1. Reads PENDING orders from fct_approved_orders.
    2. If dry_run: only lists them (no API calls, no DB updates).
    3. Else: sends to Binance in chain, updates status to EXECUTED/FAILED.
    """
    import time
    conn = None
    # Aumentar a 24 reintentos (2 minutos) para dar tiempo a que procesos lentos suelten el lock
    for attempt in range(24):
        try:
            conn = duckdb.connect(db_path)
            break
        except Exception as e:
            if "Could not set lock on file" in str(e) or "resource temporarily unavailable" in str(e).lower():
                logger.warning(f"DuckDB lock held, waiting 5 seconds... (attempt {attempt+1}/24)")
                time.sleep(5)
            else:
                raise
    if not conn:
        raise RuntimeError("No se pudo obtener el lock de DuckDB tras 2 minutos. Comprueba si otro proceso (DBeaver, etc.) tiene la BD abierta.")
    
    try:
        # 0. Limpieza: Si hay órdenes PENDING muy viejas, marcarlas como STALE/EXPIRED
        # Esto evita que una orden "zombie" se ejecute mucho después por error.
        conn.execute(f"""
            UPDATE fct_approved_orders 
            SET status = 'EXPIRED' 
            WHERE status = 'PENDING' 
              AND event_time < (now() - INTERVAL '{MAX_ORDER_AGE_MINUTES} minutes')
        """)

        # 1. Fetch PENDING orders (solo las frescas)
        query = """
            SELECT 
                event_time, symbol, signal_type, size_usd, confidence, risk_vol_multiplier,
                COALESCE(model_id, 'quant_alpha_entry_lgbm@champion') as model_id,
                reference_price
            FROM fct_approved_orders
            WHERE status = 'PENDING'
        """
        pending_orders_df = conn.execute(query).fetchdf()
        
        if pending_orders_df.empty:
            logger.info(
                "No PENDING orders in fct_approved_orders. "
                "Run pipeline 04 -> 06 (or 09) so risk engine produces approved orders first."
            )
            conn.close()
            return

        logger.info(f"Found {len(pending_orders_df)} PENDING orders to execute (Binance Futures Testnet).")
        if dry_run:
            for _, row in pending_orders_df.iterrows():
                logger.info(
                    "  [DRY-RUN] %s %s size_usd=%.2f",
                    row["symbol"], row["signal_type"], row["size_usd"],
                )
            conn.close()
            return

        # API: probar api y binance-connector (según compose)
        api_urls = [
            os.getenv("API_BASE_URL", "http://api:8000"),
            "http://api:8000",
            "http://binance-connector:8000",
        ]
        api_urls = list(dict.fromkeys(api_urls))
        binance_client = None
        for url in api_urls:
            try:
                client = BinanceConnectorClient(base_url=url)
                client.get_futures_ticker_price("BTCUSDT")
                binance_client = client
                logger.info(f"API conectada: {url}")
                break
            except Exception as e:
                logger.warning(f"API {url} no disponible: {e}")
        if not binance_client:
            raise RuntimeError(f"No se pudo conectar a la API. Probados: {api_urls}")
        hl_client = None  # Ignore Hyperliquid to prevent errors, we only use Binance

        for _, row in pending_orders_df.iterrows():
            symbol = row['symbol']
            if symbol.endswith("-USD"):
                symbol = symbol.replace("-USD", "USDT")
            signal_type = row['signal_type']
            size_usd = row['size_usd']
            # Correctly handle timestamps formatting for duckdb updates
            event_time = row['event_time'].strftime('%Y-%m-%d %H:%M:%S.%f') if isinstance(row['event_time'], pd.Timestamp) else str(row['event_time'])
            
            order_type = "MARKET"
            limit_price = None
            realized_pnl_on_close = None
            try:
                # Determine Side and Order Logic
                if signal_type == 'LONG':
                    side = 'BUY'
                    is_close = False
                elif signal_type == 'SHORT':
                    side = 'SELL'
                    is_close = False
                elif signal_type == 'EXIT_LONG':
                    side = 'SELL'
                    is_close = True
                elif signal_type == 'EXIT_SHORT':
                    side = 'BUY'
                    is_close = True
                elif signal_type == 'REBALANCE_LONG':
                    # size_usd can be positive (add to LONG) or negative (reduce LONG)
                    side = 'BUY' if size_usd > 0 else 'SELL'
                    is_close = False  # It's a partial reduction, not a full close
                elif signal_type == 'REBALANCE_SHORT':
                    # size_usd can be positive (add to SHORT) or negative (reduce SHORT)
                    side = 'SELL' if size_usd > 0 else 'BUY'
                    is_close = False
                else:
                    logger.error(f"Unknown signal type: {signal_type}")
                    continue

                # --- BINANCE EXECUTION (Primary) ---
                price_binance = binance_client.get_futures_ticker_price(symbol)
                
                # VALIDACIÓN: ¿Sigue teniendo sentido el precio?
                ref_price = row.get('reference_price', 0.0)
                if ref_price > 0:
                    deviation = abs(price_binance - ref_price) / ref_price * 100.0
                    if deviation > MAX_PRICE_DEVIATION_PCT:
                        reason = f"Price deviation too high: {deviation:.2f}% > {MAX_PRICE_DEVIATION_PCT}% (ref={ref_price:.2f}, curr={price_binance:.2f})"
                        logger.warning(f"SKIPPING order for {symbol}: {reason}")
                        _update_order_status(conn, event_time, symbol, 'FAILED_PRICE_DEVIATION')
                        _append_to_order_history(conn, row, 'FAILED_PRICE_DEVIATION', reason)
                        continue

                step_size, min_qty, min_notional = _get_symbol_filters(binance_client, symbol)

                raw_qty = 0.0
                if is_close and not signal_type.startswith('REBALANCE'):
                    # FETCH EXACT QUANTITY FOR FULL CLOSING + unrealized PnL (becomes realized on close)
                    positions = binance_client.get_futures_positions()
                    pos = next((p for p in positions if p.get('symbol') == symbol), None)
                    realized_pnl_on_close = None
                    if pos:
                        raw_qty = abs(float(pos.get("position_amt") or pos.get("positionAmt", 0) or 0))
                        quantity_binance = _round_quantity(raw_qty, step_size, min_qty, min_notional, price_binance)
                        up = pos.get("unRealizedProfit") or pos.get("unrealizedProfit")
                        if up is not None:
                            realized_pnl_on_close = float(up)
                    else:
                        quantity_binance = None
                        reason = f"EXIT: no position found for {symbol}. API positions: {[p.get('symbol') for p in positions]}"
                        logger.warning(reason)
                        _update_order_status(conn, event_time, symbol, 'FAILED')
                        _append_to_order_history(conn, row, 'FAILED', reason, order_type="MARKET", limit_price=None)
                        continue
                else:
                    # CALCULATE QUANTITY FOR ENTRY OR REBALANCE (lot size rounding)
                    size_eff = abs(size_usd)
                    if size_eff < MIN_NOTIONAL_USD:
                        reason = f"size_usd={size_usd:.2f} < MIN_NOTIONAL_USD={MIN_NOTIONAL_USD}"
                        logger.warning(f"Order below min notional for {symbol} ({signal_type}): {reason}")
                        _update_order_status(conn, event_time, symbol, 'FAILED_BELOW_MIN')
                        _append_to_order_history(conn, row, 'FAILED_BELOW_MIN', reason, order_type="MARKET", limit_price=None)
                        continue
                    raw_qty = size_eff / price_binance
                    quantity_binance = _round_quantity(raw_qty, step_size, min_qty, min_notional, price_binance)

                if quantity_binance is None or quantity_binance <= 0:
                    reason = f"qty invalid: size_usd={size_usd:.2f} price={price_binance} raw_qty={raw_qty:.6f}"
                    logger.warning(f"Calculated Binance quantity invalid for {symbol} ({signal_type}): {reason}")
                    _update_order_status(conn, event_time, symbol, 'FAILED_INVALID_QTY')
                    _append_to_order_history(conn, row, 'FAILED_INVALID_QTY', reason, order_type="MARKET", limit_price=None)
                    continue

                if USE_LIMIT_ENTRY and not is_close and signal_type in ("LONG", "SHORT"):
                    try:
                        ob = binance_client.get_futures_order_book(symbol, limit=5)
                        bids = ob.get("bids", [])
                        asks = ob.get("asks", [])
                        if bids and asks:
                            best_bid = float(bids[0][0])
                            best_ask = float(asks[0][0])
                            if side == "BUY":
                                limit_price = round(best_ask * (1 - LIMIT_ENTRY_OFFSET_PCT / 100), 2)
                            else:
                                limit_price = round(best_bid * (1 + LIMIT_ENTRY_OFFSET_PCT / 100), 2)
                            order_type = "LIMIT"
                            logger.info(f"[BINANCE] LIMIT entry (maker): {side} {symbol} @ {limit_price}")
                    except Exception as ob_e:
                        logger.warning(f"Could not get order book for LIMIT, falling back to MARKET: {ob_e}")

                logger.info(f"[BINANCE] Executing {signal_type} {side} {quantity_binance} {symbol} ({order_type})")
                order_params = dict(
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    quantity=quantity_binance,
                    reduce_only=is_close,
                )
                if order_type == "LIMIT" and limit_price is not None:
                    order_params["price"] = limit_price
                    order_params["time_in_force"] = "GTC"
                response_binance = None
                for attempt in range(EXECUTE_RETRIES):
                    try:
                        response_binance = binance_client.create_futures_order(**order_params)
                        break
                    except Exception as e:
                        is_retryable = any(x in str(e).lower() for x in ("connection", "resolve", "timeout", "max retries"))
                        if is_retryable and attempt < EXECUTE_RETRIES - 1:
                            logger.warning(f"Retry {attempt+1}/{EXECUTE_RETRIES} en {EXECUTE_RETRY_DELAY}s: {e}")
                            time.sleep(EXECUTE_RETRY_DELAY)
                        else:
                            raise
                data = response_binance.get("data") or response_binance
                order_id = data.get("order_id") or data.get("orderId")
                logger.info(
                    "[BINANCE] Orden enviada a Futures Testnet: orderId=%s symbol=%s status=%s | "
                    "Ver historial: https://testnet.binancefuture.com/futures/BTCUSDT",
                    order_id,
                    data.get("symbol", symbol),
                    data.get("status", response_binance.get("status", "OK")),
                )

                # --- STOP LOSS (solo para entradas LONG/SHORT, no EXIT ni REBALANCE) ---
                if not is_close and signal_type in ("LONG", "SHORT"):
                    try:
                        if signal_type == "LONG":
                            stop_price = round(price_binance * (1 - STOP_LOSS_PCT), 2)
                            stop_side = "SELL"
                        else:  # SHORT
                            stop_price = round(price_binance * (1 + STOP_LOSS_PCT), 2)
                            stop_side = "BUY"
                        sl_resp = binance_client.create_futures_order(
                            symbol=symbol,
                            side=stop_side,
                            quantity=quantity_binance,
                            order_type="STOP_MARKET",
                            reduce_only=True,
                            stop_price=stop_price,
                        )
                        logger.info(f"[BINANCE] Stop Loss colocado: {symbol} @ {stop_price} ({STOP_LOSS_PCT*100}%)")
                    except Exception as sl_e:
                        logger.warning(f"[BINANCE] No se pudo colocar Stop Loss para {symbol}: {sl_e}")

                # --- HYPERLIQUID EXECUTION (Secondary / Mirror) ---
                if hl_client and hl_client.exchange:
                    try:
                        price_hl = hl_client.get_futures_ticker_price(symbol)
                        quantity_hl = round(size_usd / price_hl, 3)
                        
                        logger.info(f"[HYPERLIQUID] Executing {'CLOSE' if is_close else 'ENTRY'} {side} {quantity_hl} {symbol}")
                        response_hl = hl_client.create_futures_order(
                            symbol=symbol, 
                            side=side, 
                            order_type="MARKET", 
                            quantity=quantity_hl,
                            reduce_only=is_close
                        )
                        logger.info(f"[HYPERLIQUID] Execution result: {response_hl.get('status')}")
                    except Exception as hl_e:
                        logger.error(f"[HYPERLIQUID] Failed to execute mirror order for {symbol}: {hl_e}")
                
                # Update status to EXECUTED (driven by Binance primary success)
                _update_order_status(conn, event_time, symbol, 'EXECUTED')
                _append_to_order_history(conn, row, 'EXECUTED', order_type=order_type, limit_price=limit_price, realized_pnl=realized_pnl_on_close)

                # Small delay to avoid API rate limits
                time.sleep(0.5)

            except Exception as e:
                err_msg = str(e)
                logger.error(f"Failed to execute order for {symbol}: {err_msg}")
                import traceback
                logger.error(traceback.format_exc())
                _update_order_status(conn, event_time, symbol, 'FAILED')
                _append_to_order_history(conn, row, 'FAILED', err_msg, order_type=order_type, limit_price=limit_price)

    except Exception as e:
        logger.error(f"Error in execution loop: {e}")
    finally:
        conn.close()

def _update_order_status(conn: duckdb.DuckDBPyConnection, event_time, symbol: str, status: str):
    """Updates the status of an order in the database."""
    try:
        query = f"""
            UPDATE fct_approved_orders
            SET status = '{status}'
            WHERE event_time = '{event_time}' AND symbol = '{symbol}' AND status = 'PENDING'
        """
        conn.execute(query)
    except Exception as e:
        logger.error(f"Failed to update status to {status} for {symbol} at {event_time}: {e}")


def _append_to_order_history(conn: duckdb.DuckDBPyConnection, row: pd.Series, status: str, error_message: str = "", order_type: str = "MARKET", limit_price: Optional[float] = None, realized_pnl: Optional[float] = None, reference_price: Optional[float] = None):
    """Append executed/failed order to fct_order_history (order_type/limit_price, realized_pnl para dashboard)."""
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fct_order_history (
                event_time TIMESTAMP, symbol VARCHAR, signal_type VARCHAR,
                size_usd DOUBLE, confidence DOUBLE, risk_vol_multiplier DOUBLE, status VARCHAR, model_id VARCHAR, error_message VARCHAR, order_type VARCHAR, limit_price DOUBLE, realized_pnl DOUBLE,
                reference_price DOUBLE
            )
        """)
        for col, ctype in [("error_message", "VARCHAR"), ("order_type", "VARCHAR"), ("limit_price", "DOUBLE"), ("realized_pnl", "DOUBLE"), ("reference_price", "DOUBLE")]:
            try:
                conn.execute(f"ALTER TABLE fct_order_history ADD COLUMN {col} {ctype}")
            except Exception:
                pass
        et = row['event_time']
        if hasattr(et, 'strftime'):
            et = et.strftime('%Y-%m-%d %H:%M:%S.%f')
        sym = str(row['symbol'])
        if sym.endswith("-USD"):
            sym = sym.replace("-USD", "USDT")
        model_id = str(row.get('model_id', 'quant_alpha_entry_lgbm@champion'))
        err = (error_message or "")[:500]
        ot = order_type or "MARKET"
        lp = limit_price
        rpnl = realized_pnl if realized_pnl is not None else 0.0
        ref_p = reference_price or row.get('reference_price', 0.0)
        
        try:
            conn.execute("""
                INSERT INTO fct_order_history (event_time, symbol, signal_type, size_usd, confidence, risk_vol_multiplier, status, model_id, error_message, order_type, limit_price, realized_pnl, reference_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [et, sym, str(row['signal_type']), float(row['size_usd']), float(row['confidence']),
                 float(row['risk_vol_multiplier']), status, model_id, err, ot, lp, rpnl, float(ref_p)])
        except Exception:
            try:
                conn.execute("""
                    INSERT INTO fct_order_history (event_time, symbol, signal_type, size_usd, confidence, risk_vol_multiplier, status, model_id, error_message, order_type, limit_price, realized_pnl)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [et, sym, str(row['signal_type']), float(row['size_usd']), float(row['confidence']),
                     float(row['risk_vol_multiplier']), status, model_id, err, ot, lp, rpnl])
            except Exception:
                conn.execute("""
                    INSERT INTO fct_order_history (event_time, symbol, signal_type, size_usd, confidence, risk_vol_multiplier, status, model_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, [et, sym, str(row['signal_type']), float(row['size_usd']), float(row['confidence']),
                     float(row['risk_vol_multiplier']), status, model_id])
    except Exception as e:
        logger.warning(f"Could not append to order history: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Execute PENDING orders from fct_approved_orders (Binance Futures).")
    parser.add_argument("--dry-run", action="store_true", help="Only list PENDING orders, do not send to API.")
    args = parser.parse_args()
    db_path = os.environ.get("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
    execute_pending_orders(db_path, dry_run=args.dry_run)
