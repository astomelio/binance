#!/usr/bin/env python3
"""
Prender todo: datos (temporales + gold) → entrenar modelo → suite con champion.
Usa todos los datos de la base de datos (DuckDB: tablas cargadas desde bronze + gold decision_features).
Flujo: 1) Pipeline datos (bronze → warehouse → dbt)  2) Entrenar LightGBM con máximos datos  3) Marcar champion
       4) Ejecutar suite de agentes con --use-champion --optimize sobre el mismo rango de datos.

Uso:
  python scripts/run_prender_full.py
  python scripts/run_prender_full.py --skip-data          # datos ya actualizados, solo train + suite
  python scripts/run_prender_full.py --train-days 365 --suite-days 180
  python scripts/run_prender_full.py --data-only          # solo pipeline datos (bronze + dbt)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))
os.environ.setdefault("LAKE_ROOT", str(REPO_ROOT / "data_lake"))


def _venv_python() -> str:
    for p in [
        REPO_ROOT / "venv" / "Scripts" / "python.exe",
        REPO_ROOT / "venv" / "bin" / "python",
    ]:
        if p.exists():
            return str(p)
    return sys.executable


def _run(cmd: list[str], cwd: Path | None = None, env: dict | None = None, timeout: int | None = 3600) -> int:
    full_env = {**os.environ, **(env or {})}
    full_env.setdefault("LAKE_ROOT", str(REPO_ROOT / "data_lake"))
    full_env.setdefault("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))
    return subprocess.run(
        cmd,
        cwd=str(cwd or REPO_ROOT),
        env=full_env,
        timeout=timeout,
    ).returncode


def step_data(python: str) -> int:
    """Bronze + carga DuckDB + dbt (gold decision_features)."""
    print("\n[1/4] Datos: bronze -> warehouse -> dbt (decision_features gold)...")
    return _run(
        [python, str(REPO_ROOT / "scripts" / "auto_data_then_train.py"), "--data-only"],
        timeout=7200,
    )


def step_train(python: str, train_days: int, set_champion: bool) -> int:
    """Entrena LightGBM con train_days de datos y opcionalmente marca champion."""
    print(f"\n[2/4] Entrenando modelo (ultimos {train_days} dias de decision_features)...")
    cmd = [
        python,
        str(REPO_ROOT / "scripts" / "auto_train_eval.py"),
        "--lookback-days", str(train_days),
        "--set-champion" if set_champion else "",
    ]
    cmd = [x for x in cmd if x]
    return _run(cmd, timeout=3600)


def step_suite(python: str, suite_days: int, use_champion: bool, optimize: bool, dry: bool) -> int:
    """Ejecuta un ciclo de la suite (con champion y optimize si se pide)."""
    print(f"\n[3/4] Suite de agentes (ultimos {suite_days} dias, champion={'si' if use_champion else 'no'}, optimize={optimize})...")
    cmd = [
        python,
        str(REPO_ROOT / "scripts" / "run_suite_cycle.py"),
        "--lookback-days", str(suite_days),
    ]
    if use_champion:
        cmd.append("--use-champion")
    if optimize:
        cmd.append("--optimize")
        cmd.extend(["--max-trials", "200"])
    if dry:
        cmd.extend(["--no-persist", "--no-report"])
    return _run(cmd, timeout=7200)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prender: datos (temporales+gold) → modelo → suite con todos los datos posibles."
    )
    parser.add_argument("--skip-data", action="store_true", help="No ejecutar pipeline datos (ya están actualizados)")
    parser.add_argument("--data-only", action="store_true", help="Solo pipeline datos; no entrenar ni suite")
    parser.add_argument("--train-days", type=int, default=365, help="Días de decision_features para entrenar (default 365)")
    parser.add_argument("--suite-days", type=int, default=180, help="Días para la suite (default 180; evita OOM)")
    parser.add_argument("--no-champion", action="store_true", help="No marcar el modelo como champion en MLflow")
    parser.add_argument("--no-use-champion", action="store_true", help="No rellenar alpha_score con champion en la suite")
    parser.add_argument("--no-optimize", action="store_true", help="Suite sin --optimize (más rápido, menos búsqueda)")
    parser.add_argument("--dry", action="store_true", help="Suite sin guardar estado ni informe")
    args = parser.parse_args()

    python = _venv_python()
    db_path = Path(os.environ.get("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb")))

    if not args.skip_data and not args.data_only:
        if step_data(python) != 0:
            print("[FAIL] Pipeline de datos fallo.", file=sys.stderr)
            return 1
        print("[OK] Datos (temporales + gold) actualizados.")
    elif args.data_only:
        if step_data(python) != 0:
            print("[FAIL] Pipeline de datos fallo.", file=sys.stderr)
            return 1
        print("[OK] Solo datos. Para entrenar y suite ejecuta sin --data-only.")
        return 0

    if not db_path.exists():
        print(f"[FAIL] DuckDB no encontrado: {db_path}. Ejecuta sin --skip-data.", file=sys.stderr)
        return 1

    if step_train(python, args.train_days, set_champion=not args.no_champion) != 0:
        print("[FAIL] Entrenamiento fallo.", file=sys.stderr)
        return 1
    print("[OK] Modelo entrenado (y champion actualizado).")

    if step_suite(
        python,
        suite_days=args.suite_days,
        use_champion=not args.no_use_champion,
        optimize=not args.no_optimize,
        dry=args.dry,
    ) != 0:
        print("[FAIL] Suite fallo.", file=sys.stderr)
        return 1
    print("\n[4/4] [OK] Prender completo: datos + modelo + suite. Estado e informes en artifacts/quant_model/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
