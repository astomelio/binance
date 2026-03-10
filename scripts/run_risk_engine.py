"""
Risk engine live: compute_allocations (backtest probado) + RiskEngine.
- EXIT: por flip o no_signal (modelo dice NO_TRADE).
- ENTRY: compute_allocations -> raw_signals -> RiskEngine -> size_usd.
- Circuit breaker: max_drawdown_limit + historical_peak.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from trading_lib import StrategySpec
from trading_lib.risk.engine import RiskEngine

from ai.allocation.strategies import compute_allocations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _load_risk_engine_params(report_path: Path) -> dict:
    """Carga risk_engine params optimizados desde auto_report."""
    if report_path.exists():
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            re = data.get("risk_engine")
            if isinstance(re, dict):
                return {
                    "max_open_trades": re.get("max_open_trades", 6),
                    "max_position_size_pct": re.get("max_position_size_pct", 0.20),
                    "max_drawdown_limit": re.get("max_drawdown_limit", 0.15),
                    "volatility_target": re.get("volatility_target", 0.20),
                }
        except Exception:
            pass
    return {"max_open_trades": 6, "max_position_size_pct": 0.20, "max_drawdown_limit": 0.15, "volatility_target": 0.20}


def _load_strategy_spec(report_path: Path) -> StrategySpec:
    """Carga StrategySpec desde auto_report o usa defaults."""
    if report_path.exists():
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            spec = data.get("strategy_spec") or data.get("spec")
            if spec:
                return StrategySpec.from_dict(spec)
        except Exception as e:
            logger.warning(f"Could not load spec from {report_path}: {e}")
    return StrategySpec(
        name="risk_engine_live",
        long_score_threshold=0.00,  # Lowered default for testing
        short_score_threshold=-0.00, # Lowered default for testing
        min_open_interest=0.0,
        min_quote_volume_24h=0.0,
        allow_trading_in_event_window=False,
        max_gross_exposure_pct=1.0,
        max_symbol_pct=0.4,
    )


def _load_latest_snapshot_rows(conn: duckdb.DuckDBPyConnection, db_path: str) -> list[dict]:
    """Carga las filas más recientes de decision_features (último event_time)."""
    try:
        conn.execute("SELECT 1 FROM main.decision_features LIMIT 1")
    except Exception:
        logger.warning(
            "decision_features no existe. Ejecuta primero 04_pipeline_datos_completo "
            "(o warehouse_dbt_build) para crear la tabla."
        )
        return []
    latest = conn.execute("SELECT max(event_time) FROM main.decision_features").fetchone()[0]
    if not latest:
        return []
    rows = conn.execute(
        "SELECT * FROM main.decision_features WHERE event_time = ?",
        [latest],
    ).fetchall()
    cols = [d[0] for d in conn.execute("DESCRIBE main.decision_features").fetchall()]
    return [dict(zip(cols, r)) for r in rows]


def _enrich_with_champion(rows: list[dict], model_uri: str, mlflow_uri: str | None) -> list[dict]:
    """Rellena alpha_score con el champion de MLflow."""
    if not rows:
        return rows
    try:
        from trading_lib.inference.champion_loader import enrich_rows_with_champion

        return enrich_rows_with_champion(
            rows,
            model_uri=model_uri,
            mlflow_tracking_uri=mlflow_uri,
        )
    except Exception as e:
        logger.warning(f"Champion load failed ({e}). Using alpha_score from DB if present.")
        # Fill missing alpha_score with dummy data for testing if not present
        for r in rows:
            if "alpha_score" not in r or r["alpha_score"] is None:
                import random
                r["alpha_score"] = random.uniform(-0.5, 0.5)
        return rows


def _build_rebalance_orders(
    engine: RiskEngine,
    raw_signals: list[dict],
    positions: list[dict],
    target_by_symbol: dict[str, str],
    current_capital: float,
    current_drawdown: float,
    open_trades: int,
) -> list[dict]:
    """Genera órdenes de REBALANCE para ajustar el tamaño de posiciones existentes que no cambiaron de lado."""
    rebalance_orders = []
    
    # Evaluar qué tamaño pediría el Risk Engine para TODOS los raw_signals si fueran nuevos
    # (Para ver el "tamaño ideal" de cada uno bajo las condiciones actuales de volatilidad y cuenta)
    ideal_allocations = engine.evaluate_signals(
        raw_signals=raw_signals,
        current_capital=current_capital,
        current_drawdown=current_drawdown,
        open_trades=open_trades,
    )
    ideal_by_symbol = {o["symbol"]: o for o in ideal_allocations}
    
    for pos in positions:
        qty = float(pos.get("position_amt", 0) or 0)
        if qty == 0:
            continue
            
        symbol = pos.get("symbol", "")
        side = "LONG" if qty > 0 else "SHORT"
        target_side = target_by_symbol.get(symbol, "NO_TRADE")
        
        # Si el modelo dictó salida o flip, ya se encargó _build_exit_orders_from_model
        if target_side != side:
            continue
            
        # Es un MANTENER (LONG -> LONG o SHORT -> SHORT)
        ideal = ideal_by_symbol.get(symbol)
        if not ideal:
            continue
            
        mark = float(pos.get("entry_price", 0) or 0)  # Reference price
        current_size_usd = mark * abs(qty)
        target_size_usd = ideal["size_usd"]
        
        # Calcular delta (cuánto agregar o quitar)
        delta_usd = target_size_usd - current_size_usd
        
        # Umbral: rebalancear solo si cambia más de un 10% o más de $10 USD
        if abs(delta_usd) > max(10.0, current_size_usd * 0.10):
            action = "INCREASE" if delta_usd > 0 else "REDUCE"
            logger.info(
                f"REBALANCE: {symbol} | {side} | current=${current_size_usd:.2f} -> target=${target_size_usd:.2f} | "
                f"delta=${delta_usd:.2f} ({action})"
            )
            rebalance_orders.append({
                "event_time": ideal["event_time"],
                "symbol": symbol,
                "signal_type": f"REBALANCE_{side}",  # REBALANCE_LONG or REBALANCE_SHORT
                "size_usd": delta_usd,  # Positive to add, negative to reduce
                "confidence": ideal["confidence"],
                "risk_vol_multiplier": ideal["risk_vol_multiplier"],
                "status": "PENDING",
            })
            
    return rebalance_orders

def _build_exit_orders_from_model(
    conn: duckdb.DuckDBPyConnection,
    target_by_symbol: dict[str, str],
) -> list[dict]:
    """
    Genera órdenes EXIT consultando la API de Binance (fuente de verdad).
    Si el modelo dice:
    - signal_flip: target.side != pos.side
    - no_signal: target es NO_TRADE
    """
    exit_orders = []
    
    # Intentar obtener posiciones reales de la API
    try:
        from trading_lib.api_client import BinanceConnectorClient
        api_url = os.environ.get("API_BASE_URL", "http://api:8000")
        client = BinanceConnectorClient(base_url=api_url)
        positions = client.get_futures_positions()
        
        for pos in positions:
            qty = float(pos.get("position_amt", 0) or 0)
            if qty == 0:
                continue
                
            symbol = pos["symbol"]
            side = "LONG" if qty > 0 else "SHORT"
            target_side = target_by_symbol.get(symbol, "NO_TRADE")

            if target_side == "NO_TRADE":
                reason = "no_signal"
            elif target_side != side:
                reason = "signal_flip"
            else:
                continue

            # Precio de entrada o actual como ref (no afecta el cierre total)
            mark = float(pos.get("entry_price", 0) or 0)
            size_usd = mark * abs(qty)

            logger.info(f"EXIT: {symbol} | {side} -> {target_side} | reason={reason}")
            exit_orders.append({
                "event_time": datetime.now(timezone.utc),
                "symbol": symbol,
                "signal_type": "EXIT_LONG" if side == "LONG" else "EXIT_SHORT",
                "size_usd": size_usd,
                "confidence": 1.0,
                "risk_vol_multiplier": 1.0,
                "status": "PENDING",
                "close_reason": reason,
            })
        return exit_orders

    except Exception as e:
        logger.warning(f"No se pudo consultar posiciones en vivo de Binance para EXITS: {e}")
        return exit_orders


def _alloc_to_raw_signals(
    alloc: dict[str, float],
    features_by_symbol: dict[str, dict],
) -> list[dict]:
    """Convierte AllocationVector (compute_allocations) a raw_signals para RiskEngine."""
    raw = []
    for symbol, frac in alloc.items():
        if abs(frac) < 1e-6:
            continue
        row = features_by_symbol.get(symbol, {})
        vol = float(row.get("price_deviation_pct_24h", 0) or row.get("asset_volatility_24h", 0) or 0.05)
        if vol <= 0:
            vol = 0.05
        conf = min(0.99, 0.5 + abs(frac) / 2)
        raw.append({
            "event_time": row.get("event_time", datetime.now(timezone.utc)),
            "symbol": symbol,
            "signal_type": "LONG" if frac > 0 else "SHORT",
            "confidence": conf,
            "asset_volatility_24h": vol,
            "model_version": "champion"
        })
    return raw


def generate_and_evaluate_signals(
    db_path: str,
    model_uri: str = "models:/quant_alpha_entry_lgbm@champion",
    mlflow_uri: str | None = None,
) -> None:
    """
    1. Carga decision_features (último snapshot)
    2. Enriquece con champion MLflow (alpha_score)
    3. compute_model_allocations -> target por símbolo
    4. EXIT: posiciones donde modelo dice NO_TRADE o flip
    5. ENTRY: RiskEngine sobre señales del modelo
    6. Escribe fct_approved_orders
    """
    import time
    conn = None
    for attempt in range(12): # Retry up to 1 minute
        try:
            conn = duckdb.connect(db_path)
            break
        except Exception as e:
            if "Could not set lock on file" in str(e):
                logger.warning(f"DuckDB lock held, waiting 5 seconds... (attempt {attempt+1}/12)")
                time.sleep(5)
            else:
                raise
    if not conn:
        raise RuntimeError("Failed to acquire DuckDB lock after 1 minute.")

    # 1. Snapshot
    snapshot_rows = _load_latest_snapshot_rows(conn, db_path)
    if not snapshot_rows:
        logger.warning("No decision_features in DB.")
        conn.close()
        return

    # 2. Champion
    spec = _load_strategy_spec(REPO_ROOT / "artifacts" / "quant_model" / "auto_report.json")
    enriched = _enrich_with_champion(snapshot_rows, model_uri, mlflow_uri)

    # 3. compute_allocations (misma lógica que backtest probado)
    for r in enriched:
        sym = r.get("symbol", "")
        if sym.endswith("-USD"):
            sym = sym.replace("-USD", "USDT")
            r["symbol"] = sym
    features_by_symbol = {r["symbol"]: r for r in enriched if r.get("symbol")}
    
    # Guardar precios de referencia para validación posterior en ejecución
    ref_prices = {sym: float(r.get("futures_last_price", 0) or 0) for sym, r in features_by_symbol.items()}
    
    alloc = compute_allocations(
        features_by_symbol,
        score_key="alpha_score",
        long_threshold=spec.long_score_threshold,
        short_threshold=spec.short_score_threshold,
        min_allocation=0.1,
        max_allocation=spec.max_symbol_pct,
        max_exposure=spec.max_gross_exposure_pct,
        fed_window_key="fed_window",
        vol_key="price_deviation_pct_24h",
        no_trade_windows=() if spec.allow_trading_in_event_window else ("PRE_EVENT", "POST_EVENT"),
    )
    target_by_symbol = {
        sym: "LONG" if a > 0 else ("SHORT" if a < 0 else "NO_TRADE")
        for sym, a in alloc.items()
    }
    snapshot_by_symbol = features_by_symbol

    # 4. EXIT (modelo: flip o no_signal)
    exit_orders = _build_exit_orders_from_model(conn, target_by_symbol)

    # 5. ENTRY (RiskEngine) - params desde auto_report si optimizados
    report_path = REPO_ROOT / "artifacts" / "quant_model" / "auto_report.json"
    rp = _load_risk_engine_params(report_path)
    engine = RiskEngine(
        base_capital=10000.0,
        max_drawdown_limit=rp["max_drawdown_limit"],
        volatility_target=rp["volatility_target"],
        max_position_size_pct=rp["max_position_size_pct"],
        max_open_trades=rp["max_open_trades"],
    )

    raw_signals = _alloc_to_raw_signals(alloc, snapshot_by_symbol)
    
    logger.info(f"DEBUG raw_signals count: {len(raw_signals)}")

    try:
        from trading_lib.api_client import BinanceConnectorClient
        api_url = os.environ.get("API_BASE_URL", "http://api:8000")
        client = BinanceConnectorClient(base_url=api_url)
        balances = client.get_futures_account_balance()
        usdt = next((float(b["wallet_balance"]) for b in balances if b["asset"] == "USDT"), 0.0)
        current_capital = usdt if usdt > 0 else 10000.0
        positions = client.get_futures_positions()
        open_trades = len(positions)
        open_symbols = {p["symbol"] for p in positions}
        
        # Filtro: las nuevas entradas son símbolos que NO tenemos abiertos
        raw_entries = [s for s in raw_signals if s["symbol"] not in open_symbols]
        # Filtro: las rebalanceos son símbolos que SÍ tenemos abiertos
        raw_rebalances = [s for s in raw_signals if s["symbol"] in open_symbols]
    except Exception as e:
        logger.warning(f"Binance state unavailable: {e}. Using fallback.")
        current_capital = 10000.0
        open_trades = 0
        positions = []
        raw_entries = raw_signals
        raw_rebalances = []

    try:
        from trading_lib.risk.state import get_historical_peak

        peak = get_historical_peak(current_capital)
        current_drawdown = (peak - current_capital) / peak if peak > 0 else 0.0
        logger.info(f"Capital peak={peak}, current={current_capital}, DD={current_drawdown:.2f}")
    except Exception as e:
        logger.warning(f"Historical peak unavailable: {e}")
        current_drawdown = 0.0

    logger.info(f"DEBUG raw_entries count: {len(raw_entries)}")
    approved_entries = engine.evaluate_signals(
        raw_signals=raw_entries,
        current_capital=current_capital,
        current_drawdown=current_drawdown,
        open_trades=open_trades,
    )
    logger.info(f"DEBUG raw_entries count: {len(raw_entries)} -> approved: {len(approved_entries)}")
    
    # 5.5 REBALANCE (RiskEngine en posiciones existentes)
    rebalance_orders = _build_rebalance_orders(
        engine=engine,
        raw_signals=raw_rebalances,
        positions=positions,
        target_by_symbol=target_by_symbol,
        current_capital=current_capital,
        current_drawdown=current_drawdown,
        open_trades=open_trades,
    )

    # 6. Write (Write raw signals first)
    if raw_signals:
        raw_df = pd.DataFrame(raw_signals)
        conn.register("temp_raw_signals", raw_df)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fct_raw_signals (
                event_time TIMESTAMP, symbol VARCHAR, signal_type VARCHAR,
                confidence DOUBLE, asset_volatility_24h DOUBLE, model_version VARCHAR
            )
        """)
        conn.execute("DELETE FROM fct_raw_signals")
        conn.execute("INSERT INTO fct_raw_signals SELECT * FROM temp_raw_signals")
        logger.info(f"Inserted {len(raw_signals)} raw signals")

    all_approved = []
    # Force write even if empty to ensure tables exist and UI feedback is correct
    model_id = model_uri.replace("models:/", "") if model_uri else "quant_alpha_entry_lgbm@champion"
    for o in approved_entries:
        symbol = o["symbol"]
        all_approved.append({
            "event_time": o["event_time"],
            "symbol": symbol,
            "signal_type": o["signal_type"],
            "size_usd": o["size_usd"],
            "confidence": o["confidence"],
            "risk_vol_multiplier": o["risk_vol_multiplier"],
            "status": "PENDING",
            "model_id": model_id,
            "reference_price": ref_prices.get(symbol, 0.0),
        })
    for o in exit_orders:
        symbol = o["symbol"]
        all_approved.append({
            "event_time": o["event_time"],
            "symbol": symbol,
            "signal_type": o["signal_type"],
            "size_usd": o["size_usd"],
            "confidence": o["confidence"],
            "risk_vol_multiplier": o["risk_vol_multiplier"],
            "status": "PENDING",
            "model_id": model_id,
            "reference_price": ref_prices.get(symbol, 0.0),
        })
    for o in rebalance_orders:
        symbol = o["symbol"]
        all_approved.append({
            "event_time": o["event_time"],
            "symbol": symbol,
            "signal_type": o["signal_type"],
            "size_usd": o["size_usd"],
            "confidence": o["confidence"],
            "risk_vol_multiplier": o["risk_vol_multiplier"],
            "status": "PENDING",
            "model_id": model_id,
            "reference_price": ref_prices.get(symbol, 0.0),
        })

    app_df = pd.DataFrame(all_approved) if all_approved else pd.DataFrame(columns=[
        "event_time", "symbol", "signal_type", "size_usd", "confidence", "risk_vol_multiplier", "status", "model_id", "reference_price"
    ])
    
    conn.register("temp_approved_orders", app_df)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fct_approved_orders (
            event_time TIMESTAMP, symbol VARCHAR, signal_type VARCHAR,
            size_usd DOUBLE, confidence DOUBLE, risk_vol_multiplier DOUBLE, status VARCHAR, model_id VARCHAR,
            reference_price DOUBLE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fct_order_history (
            event_time TIMESTAMP, symbol VARCHAR, signal_type VARCHAR,
            size_usd DOUBLE, confidence DOUBLE, risk_vol_multiplier DOUBLE, status VARCHAR, model_id VARCHAR,
            reference_price DOUBLE
        )
    """)
    try:
        conn.execute("ALTER TABLE fct_approved_orders ADD COLUMN model_id VARCHAR")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE fct_approved_orders ADD COLUMN reference_price DOUBLE")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE fct_order_history ADD COLUMN reference_price DOUBLE")
    except Exception:
        pass
    # fct_order_history lo llena execute_approved_orders al ejecutar/fallar (con error_message)
    conn.execute("DELETE FROM fct_approved_orders")
    conn.execute("INSERT INTO fct_approved_orders SELECT * FROM temp_approved_orders")

    # Persist risk stats for dashboard (raw vs approved = rejected by risk)
    raw_entries_count = len(raw_entries)
    approved_count = len(approved_entries)
    rejected_count = max(0, raw_entries_count - approved_count)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fct_risk_cycle_stats (
            event_time TIMESTAMP, raw_count INTEGER, approved_count INTEGER, rejected_count INTEGER
        )
    """)
    ts = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO fct_risk_cycle_stats (event_time, raw_count, approved_count, rejected_count) VALUES (?, ?, ?, ?)",
        [ts, raw_entries_count, approved_count, rejected_count],
    )

    logger.info(
        f"Inserted {len(all_approved)} orders (Entries: {len(approved_entries)}, "
        f"Exits: {len(exit_orders)}, Rebalances: {len(rebalance_orders)}). Risk rejected: {rejected_count}"
    )

    conn.close()


if __name__ == "__main__":
    db_path = os.environ.get("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))
    mlflow_uri = os.environ.get("MLFLOW_TRACKING_URI")
    model_uri = os.environ.get("RISK_MODEL_URI", "models:/quant_alpha_entry_lgbm@champion")
    generate_and_evaluate_signals(db_path, model_uri=model_uri, mlflow_uri=mlflow_uri)
