#!/usr/bin/env python3
"""
Compara backtest (con un modelo) vs paper en el mismo periodo.
- Saca el periodo del paper (paper_scenarios.jsonl).
- Carga decision_features para ese periodo con velas de 1h (horizon 1h).
- El alpha_score lo rellena el modelo: pasando --model-uri se hace inferencia y
  el backtest refleja entradas/salidas según el modelo, solo con velas 1h.
Uso:
  python scripts/run_backtest_vs_paper.py --model-uri models:/quant_alpha_entry_lgbm@champion
  python scripts/run_backtest_vs_paper.py --model-uri sqlite:///artifacts/quant_model/mlflow.db/models:/quant_alpha_entry_lgbm@champion
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backtest vs paper en el mismo periodo; modelo rellena alpha_score, backtest 1h."
    )
    parser.add_argument(
        "--model-uri",
        default="",
        help="URI del modelo (ej. models:/quant_alpha_entry_lgbm@champion). Obligatorio si DuckDB no tiene alpha_score.",
    )
    parser.add_argument(
        "--mlflow-uri",
        default="sqlite:///artifacts/quant_model/mlflow.db",
        help="Tracking URI de MLflow para cargar el modelo.",
    )
    parser.add_argument(
        "--horizon",
        default="1h",
        choices=("1h", "4h", "24h"),
        help="Horizonte del backtest (velas). Por defecto 1h (lo que tienes ahora).",
    )
    parser.add_argument(
        "--prob-threshold",
        type=float,
        default=0.55,
        help="Umbral de probabilidad para long/short en compute_allocations.",
    )
    parser.add_argument(
        "--paper-scenarios",
        default="artifacts/quant_model/paper_scenarios.jsonl",
        help="Ruta a paper_scenarios.jsonl.",
    )
    args = parser.parse_args()

    paper_scenarios_path = Path(args.paper_scenarios)
    if not paper_scenarios_path.exists():
        print("No existe paper_scenarios.jsonl. Ejecuta antes:")
        print(
            "  python examples/compare_backtest_vs_paper.py --scenarios --out-scenarios artifacts/quant_model/paper_scenarios.jsonl"
        )
        return 1

    scenarios = []
    for line in paper_scenarios_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            scenarios.append(json.loads(line))
    if not scenarios:
        print("paper_scenarios.jsonl vacío.")
        return 1

    min_ts = min(s["entry_time"] for s in scenarios)
    max_ts = max(s["exit_time"] for s in scenarios)
    start_str = min_ts.replace("Z", "").replace("+00:00", "").strip()
    end_str = max_ts.replace("Z", "").replace("+00:00", "").strip()

    print(f"Periodo paper: {min_ts} -> {max_ts}")

    total_notional = sum(s["notional_usd"] for s in scenarios)
    paper_return = (
        sum(s["pnl_pct"] * s["notional_usd"] for s in scenarios) / total_notional
        if total_notional else 0.0
    )
    print(f"Paper retorno realizado %: {paper_return:+.3f}%")

    db_path = os.environ.get("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
    if not Path(db_path).exists():
        print(f"DuckDB no encontrado: {db_path}")
        print("Backtest net %: N/A (ejecuta make warehouse-load)")
        _write_report(min_ts, max_ts, None, paper_return, model_uri=args.model_uri or None)
        return 0

    from ai.data.loader import load_decision_features
    from ai.allocation.backtest import run_allocation_backtest
    from ai.allocation.strategies import compute_allocations

    # Cargar solo ese periodo; horizon 1h = velas de 1h (fwd_return_1h)
    rows = load_decision_features(
        horizon=args.horizon,
        label_not_null=True,
        db_path=db_path,
        start=start_str,
        end=end_str,
    )
    if not rows:
        print("No hay filas en decision_features para ese periodo. Backtest net %: N/A")
        _write_report(min_ts, max_ts, None, paper_return, model_uri=args.model_uri or None)
        return 0

    # Rellenar alpha_score con el modelo (es el trabajo de los modelos que saquemos)
    if args.model_uri:
        import mlflow
        mlflow.set_tracking_uri(args.mlflow_uri)
        try:
            model = mlflow.lightgbm.load_model(args.model_uri)
        except Exception as e:
            print(f"No se pudo cargar el modelo: {e}")
            print("Usa --model-uri con un modelo LightGBM registrado (ej. models:/quant_alpha_entry_lgbm@champion).")
            return 1
        from ai.inference.model_scorer import enrich_rows_with_model
        rows = enrich_rows_with_model(
            rows,
            model,
            feature_names=None,
            prob_threshold=args.prob_threshold,
        )
        print(f"Modelo aplicado: {args.model_uri} (alpha_score rellenado por inferencia)")
    else:
        has_alpha = any(
            r.get("alpha_score") is not None and str(r.get("alpha_score")).strip() != ""
            for r in rows
        )
        if not has_alpha:
            print(
                "alpha_score en DuckDB está vacío. El backtest necesita scores del modelo."
            )
            print(
                "Pasa --model-uri (ej. models:/quant_alpha_entry_lgbm@champion) para que el modelo rellene alpha_score."
            )
            return 1

    result = run_allocation_backtest(
        rows,
        horizon=args.horizon,
        fee_percent=0.04,
        slippage_percent=0.02,
        compute_fn=lambda f, _: compute_allocations(
            f,
            prob_threshold=args.prob_threshold,
            min_allocation=0.1,
            max_allocation=0.4,
            max_exposure=1.0,
        ),
    )
    backtest_net = result.net_return_percent
    print(f"Backtest retorno net % (mismo periodo, {args.horizon}): {backtest_net:+.3f}%")
    print(f"Trades backtest: {result.trades_count} | Paper trades cerrados: {len(scenarios)}")

    diff = backtest_net - paper_return
    print(f"Diferencia (backtest - paper): {diff:+.3f}%")

    _write_report(
        min_ts,
        max_ts,
        backtest_net,
        paper_return,
        result.trades_count,
        len(scenarios),
        model_uri=args.model_uri or None,
        horizon=args.horizon,
    )
    return 0


def _write_report(
    start: str,
    end: str,
    backtest_net: float | None,
    paper_return: float,
    backtest_trades: int | None = None,
    paper_trades: int | None = None,
    model_uri: str | None = None,
    horizon: str = "1h",
) -> None:
    out = Path("artifacts/quant_model/comparacion_backtest_vs_paper.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"Periodo: {start} -> {end}",
        f"Horizon (velas): {horizon}",
        f"Backtest net %: {backtest_net:+.3f}%" if backtest_net is not None else "Backtest net %: N/A",
        f"Paper realizado %: {paper_return:+.3f}%",
    ]
    if backtest_net is not None:
        lines.append(f"Diferencia (backtest - paper): {backtest_net - paper_return:+.3f}%")
    if model_uri:
        lines.append(f"Modelo: {model_uri}")
    if backtest_trades is not None:
        lines.append(f"Trades backtest: {backtest_trades}")
    if paper_trades is not None:
        lines.append(f"Trades paper (cerrados): {paper_trades}")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Reporte escrito: {out}")


if __name__ == "__main__":
    raise SystemExit(main())
