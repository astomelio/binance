"""
Prueba la cadena: estado de entrada -> modelo a órdenes (risk engine) -> órdenes en cadena (execute).

Uso:
  python scripts/test_order_chain_and_model_to_orders.py
  python scripts/test_order_chain_and_model_to_orders.py --run-risk-engine   # ejecuta risk engine (modelo -> fct_approved_orders)
  python scripts/test_order_chain_and_model_to_orders.py --execute         # envía PENDING a Binance en cadena
  python scripts/test_order_chain_and_model_to_orders.py --run-risk-engine --execute  # cadena completa
  python scripts/test_order_chain_and_model_to_orders.py --execute --dry-run  # solo lista órdenes, no envía

Requiere: DBT_DUCKDB_PATH (o artifacts/warehouse/crypto.duckdb), API en localhost:8000 para --execute.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _db_path() -> str:
    return os.environ.get("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))


def _state_entrada_anterior(db_path: str) -> None:
    """Muestra estado de la entrada anterior: decision_features, fct_approved_orders, opcional API."""
    import duckdb
    print("\n=== ESTADO ENTRADA ANTERIOR ===\n")
    conn = duckdb.connect(db_path)
    try:
        # decision_features
        try:
            r = conn.execute("SELECT count(*) as n, max(event_time) as last_ts FROM main.decision_features").fetchone()
            print(f"  decision_features: {r[0]} filas, último event_time: {r[1]}")
        except Exception as e:
            print(f"  decision_features: no existe o error ({e})")
            print("    -> Ejecuta 04_pipeline_datos_completo y dbt build para tener decision_features.")

        # fct_approved_orders por status
        try:
            df = conn.execute(
                "SELECT status, count(*) as n FROM fct_approved_orders GROUP BY status"
            ).fetchdf()
            print("  fct_approved_orders:")
            for _, row in df.iterrows():
                print(f"    {row['status']}: {row['n']}")
        except Exception as e:
            print(f"  fct_approved_orders: no existe o error ({e})")

        # Binance state (opcional)
        api_url = os.environ.get("API_BASE_URL", "http://localhost:8000")
        try:
            from trading_lib.api_client import BinanceConnectorClient
            client = BinanceConnectorClient(base_url=api_url)
            balances = client.get_futures_account_balance()
            if isinstance(balances, list):
                usdt = next((float(b.get("wallet_balance", 0) or 0) for b in balances if b.get("asset") == "USDT"), 0.0)
            else:
                usdt = float(balances.get("USDT", {}).get("wallet_balance", 0) or 0)
            positions = client.get_futures_positions()
            open_count = sum(1 for p in (positions or []) if float(p.get("position_amt", 0) or p.get("quantity", 0) or 0) != 0)
            print(f"  API Binance: USDT ~{usdt:.2f}, posiciones abiertas: {open_count}")
        except Exception as e:
            print(f"  API Binance: no disponible ({e})")
    finally:
        conn.close()


def _run_risk_engine(db_path: str) -> bool:
    """Ejecuta run_risk_engine.py: decision_features + champion -> fct_approved_orders (traducción modelo a órdenes)."""
    script = REPO_ROOT / "scripts" / "run_risk_engine.py"
    env = {**os.environ, "DBT_DUCKDB_PATH": db_path, "PYTHONPATH": str(REPO_ROOT)}
    print("\n=== RISK ENGINE (modelo -> órdenes) ===\n")
    r = subprocess.run([sys.executable, str(script)], cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=120)
    if r.stdout:
        print(r.stdout[-2000:])
    if r.stderr:
        print(r.stderr[-2000:])
    if r.returncode != 0:
        print(f"  Risk engine falló (exit {r.returncode})")
        return False
    print("  Risk engine OK. fct_approved_orders actualizado con señales del modelo.")
    return True


def _run_execute(db_path: str, dry_run: bool) -> bool:
    """Ejecuta execute_approved_orders: envía PENDING a Binance en cadena (o --dry-run solo lista)."""
    script = REPO_ROOT / "scripts" / "execute_approved_orders.py"
    env = {**os.environ, "DBT_DUCKDB_PATH": db_path, "PYTHONPATH": str(REPO_ROOT)}
    print("\n=== EJECUCIÓN ÓRDENES EN CADENA ===\n")
    cmd = [sys.executable, str(script)]
    if dry_run:
        cmd.append("--dry-run")
    r = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=300)
    if r.stdout:
        print(r.stdout)
    if r.stderr:
        print(r.stderr)
    if r.returncode != 0:
        print(f"  Execute falló (exit {r.returncode})")
        return False
    print("  Execute OK.")
    return True


def main():
    import argparse
    p = argparse.ArgumentParser(description="Prueba cadena modelo->órdenes y órdenes en cadena.")
    p.add_argument("--run-risk-engine", action="store_true", help="Ejecutar risk engine (decision_features + champion -> fct_approved_orders).")
    p.add_argument("--execute", action="store_true", help="Ejecutar PENDING órdenes en Binance (en cadena).")
    p.add_argument("--dry-run", action="store_true", help="Con --execute: solo listar órdenes, no enviar.")
    args = p.parse_args()

    db_path = _db_path()
    if not Path(db_path).exists():
        print(f"DB no encontrada: {db_path}")
        print("  Ejecuta antes el pipeline (04) para crear el warehouse.")
        return 1

    _state_entrada_anterior(db_path)

    if args.run_risk_engine:
        if not _run_risk_engine(db_path):
            return 1
        _state_entrada_anterior(db_path)

    if args.execute:
        if not _run_execute(db_path, dry_run=args.dry_run):
            return 1

    if not args.run_risk_engine and not args.execute:
        print("\nOpciones: --run-risk-engine (modelo->órdenes), --execute (enviar en cadena), --execute --dry-run (solo listar).")
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
