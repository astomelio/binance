#!/usr/bin/env python3
"""
Evaluación por etapas: alpha solo, risk solo, mean reversion solo, sensores, combinaciones.
Carga datos de DuckDB, ejecuta las 5 etapas y escribe un informe en artifacts/quant_model/.

Uso:
  python scripts/run_staged_eval.py
  python scripts/run_staged_eval.py --lookback-days 45 --out artifacts/quant_model/staged_report.json
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Run staged evaluation: alpha, risk, mean reversion, sensors, combinations")
    parser.add_argument("--lookback-days", type=int, default=45)
    parser.add_argument("--horizon", default="4h")
    parser.add_argument("--out", default="artifacts/quant_model/staged_report.json")
    parser.add_argument("--top-per-stage", type=int, default=2)
    args = parser.parse_args()

    db_path = os.environ.get("DBT_DUCKDB_PATH", str(REPO_ROOT / "artifacts" / "warehouse" / "crypto.duckdb"))
    if not Path(db_path).exists():
        print(f"DuckDB no encontrado: {db_path}", file=sys.stderr)
        return 1

    from datetime import datetime, timedelta, timezone
    from ai.data.loader import load_decision_features
    from ai.explorer.staged_eval import run_all_stages, StageResult

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=args.lookback_days)
    rows = load_decision_features(
        db_path=db_path,
        horizon=args.horizon,
        label_not_null=True,
        start=start_dt.strftime("%Y-%m-%d"),
        end=end_dt.strftime("%Y-%m-%d"),
    )
    if not rows or len(rows) < 200:
        print(f"Datos insuficientes: {len(rows)} filas.", file=sys.stderr)
        return 1

    def _serialize(sr: StageResult) -> dict:
        return {
            "stage": sr.stage,
            "config": sr.config,
            "net_return_percent": sr.net_return_percent,
            "trades_count": sr.trades_count,
        }

    print("Ejecutando etapas: alpha, risk, mean_reversion, sensors, combinaciones...")
    out = run_all_stages(
        rows,
        horizons=[args.horizon],
        symbol_sets=["top50", "all"],
        top_per_stage=args.top_per_stage,
        alpha_combos=20,
        mean_rev_combos=30,
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": args.lookback_days,
        "rows": len(rows),
        "stage_alpha_top5": [_serialize(s) for s in out["stage_alpha"]],
        "stage_risk_top5": [_serialize(s) for s in out["stage_risk"]],
        "stage_mean_reversion_top5": [_serialize(s) for s in out["stage_mean_reversion"]],
        "stage_sensors_top5": [_serialize(s) for s in out["stage_sensors"]],
        "stage_combinations_top10": [_serialize(s) for s in out["stage_combinations"]],
        "best_overall": _serialize(out["best_overall"]) if out["best_overall"] else None,
    }

    out_path = REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Informe:", out_path)
    if report["best_overall"]:
        print("Mejor global:", report["best_overall"]["stage"], report["best_overall"]["net_return_percent"], "%", report["best_overall"]["trades_count"], "trades")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
