#!/usr/bin/env python3
"""
Prender todo: comprueba entorno y datos, luego ejecuta un ciclo de la suite de agentes.
- Si falta DuckDB o hay pocas filas, indica qué comando ejecutar (o --ensure-data para intentar datos).
- Usa el mismo Python que tengas activo (venv recomendado).

Uso:
  python scripts/run_suite_prender_todo.py
  python scripts/run_suite_prender_todo.py --ensure-data   # datos + suite
  python scripts/run_suite_prender_todo.py --dry            # no guardar estado ni informe
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))


def _venv_python() -> str:
    for p in [
        REPO_ROOT / "venv" / "Scripts" / "python.exe",
        REPO_ROOT / "venv" / "bin" / "python",
    ]:
        if p.exists():
            return str(p)
    return sys.executable


def check_imports() -> str | None:
    """None si todo ok; mensaje de error si falta algo."""
    try:
        import duckdb  # noqa: F401
    except ImportError:
        return "Falta duckdb. Ejecuta: pip install -r requirements.txt"
    try:
        from ai.data.loader import load_decision_features  # noqa: F401
        from ai.suite import QuantAgentSuite  # noqa: F401
    except ImportError as e:
        return f"Falta módulo: {e}. ¿Ejecutaste pip install -r requirements.txt?"
    return None


def check_data(db_path: Path, min_rows: int = 200) -> tuple[bool, int, str]:
    """(ok, rows, message)."""
    if not db_path.exists():
        return False, 0, f"DuckDB no encontrado: {db_path}"
    try:
        import duckdb
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            out = con.execute(
                "SELECT COUNT(*) FROM main.decision_features WHERE fwd_return_4h IS NOT NULL"
            ).fetchone()
            n = out[0] if out else 0
        finally:
            con.close()
    except Exception as e:
        return False, 0, f"Error leyendo DuckDB: {e}"
    if n < min_rows:
        return False, n, f"Pocas filas en decision_features: {n} (mínimo ~{min_rows}). Necesitas cargar datos."
    return True, n, ""


def run_data_pipeline(python: str) -> int:
    """Bronze + warehouse load + dbt. Devuelve 0 si ok."""
    env = {**os.environ, "LAKE_ROOT": str(REPO_ROOT / "data_lake")}
    print("\n[prender] Ejecutando pipelines de datos (bronze + DuckDB + dbt)...")
    code = subprocess.run(
        [python, str(REPO_ROOT / "scripts" / "auto_data_then_train.py"), "--data-only"],
        cwd=str(REPO_ROOT),
        env=env,
    ).returncode
    return code


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Prender todo y ejecutar un ciclo de la suite de agentes")
    parser.add_argument("--ensure-data", action="store_true", help="Ejecutar pipelines de datos antes si faltan")
    parser.add_argument("--dry", action="store_true", help="No guardar estado ni informe (solo probar)")
    parser.add_argument("--horizon", default="4h", choices=("1h", "4h", "24h"))
    parser.add_argument("--lookback-days", type=int, default=90, help="Días de datos (0 = todo el dataset)")
    args = parser.parse_args()

    python = _venv_python()
    db_path = Path(os.environ.get("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb")))

    err = check_imports()
    if err:
        print(err, file=sys.stderr)
        return 1

    ok, rows, msg = check_data(db_path)
    if not ok:
        print(msg, file=sys.stderr)
        if args.ensure_data:
            if run_data_pipeline(python) != 0:
                print("❌ Pipeline de datos falló.", file=sys.stderr)
                return 1
            ok, rows, msg = check_data(db_path)
            if not ok:
                print(msg, file=sys.stderr)
                return 1
        else:
            print("\nPara tener datos ejecuta uno de:", file=sys.stderr)
            print("  make auto-data-then-train   # datos + training", file=sys.stderr)
            print("  make warehouse-load        # solo cargar bronze -> DuckDB + dbt", file=sys.stderr)
            print("O vuelve a lanzar con:  python scripts/run_suite_prender_todo.py --ensure-data", file=sys.stderr)
            return 1

    print(f"[prender] DuckDB ok, {rows} filas en decision_features. Ejecutando suite (últimos {args.lookback_days} días)...")
    cmd = [python, str(REPO_ROOT / "scripts" / "run_suite_cycle.py"), "--horizon", args.horizon, "--lookback-days", str(args.lookback_days)]
    if args.dry:
        cmd.extend(["--no-persist", "--no-report"])
    code = subprocess.run(cmd, cwd=str(REPO_ROOT), env=os.environ).returncode
    if code != 0:
        return code
    print("\n✅ Suite terminada. Estado e informe en artifacts/quant_model/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
