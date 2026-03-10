#!/usr/bin/env python3
import json
import os
import duckdb
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))
STATE_PATH = REPO_ROOT / "artifacts" / "quant_model" / "suite_state.json"

def main():
    print("=== VALIDACIÓN DE ESTRATEGIA: BACKTEST VS REALIDAD ===")
    
    # 1. Cargar el Champion actual
    if not STATE_PATH.exists():
        print(f"Error: No se encontró el estado de la suite en {STATE_PATH}")
        return
    
    with open(STATE_PATH, 'r') as f:
        state = json.load(f)
    
    champion_id = state.get("champion_id", "Desconocido")
    champion_metrics = state.get("champion_metrics", {})
    expected_return = champion_metrics.get("net_return_percent", 0.0)
    
    print(f"\n[BACKTEST CHAMPION]")
    print(f"  ID: {champion_id}")
    print(f"  Retorno Esperado (Backtest): {expected_return:+.2f}%")
    
    # 2. Consultar la Realidad (DuckDB)
    if not Path(DB_PATH).exists():
        print(f"Error: No se encontró la base de datos en {DB_PATH}")
        return
    
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        # PNL Real
        query = f"""
            SELECT 
                COUNT(*) as trades,
                COALESCE(SUM(realized_pnl), 0) as total_pnl,
                SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as wins,
                MIN(event_time) as first_trade,
                MAX(event_time) as last_trade
            FROM fct_order_history
            WHERE model_id LIKE '%{champion_id}%' OR model_id = 'quant_alpha_entry_lgbm@champion'
        """
        res = conn.execute(query).fetchone()
        
        trades = res[0]
        total_pnl = float(res[1])
        wins = res[2] or 0
        win_rate = (wins / trades * 100) if trades > 0 else 0.0
        
        print(f"\n[REALIDAD (PAPER TRADING)]")
        if trades == 0:
            print("  No se han encontrado operaciones reales ejecutadas para este champion todavía.")
        else:
            print(f"  Operaciones ejecutadas: {trades}")
            print(f"  PnL Realizado Total: ${total_pnl:+.4f} USDT")
            print(f"  Win Rate Real: {win_rate:.1f}%")
            print(f"  Periodo: {res[3]} -> {res[4]}")
            
            # 3. Comparación y Calibración
            print(f"\n[VERDICTO]")
            if total_pnl > 0 and expected_return > 0:
                print("  [OK] ESTRATEGIA POSITIVA: La realidad confirma la tendencia del backtest.")
            elif total_pnl < 0 and expected_return > 0:
                print("  [!] DISCREPANCIA: El backtest era positivo pero la realidad es negativa.")
                print("     Posibles causas: Overfitting, Look-ahead bias o Slippage alto.")
            else:
                print("  [?] Neutral: Se requieren más datos para un veredicto sólido.")
                
    except Exception as e:
        print(f"Error consultando DuckDB: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
