from __future__ import annotations

import argparse
import itertools
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import mlflow

from trading_lib import FeeModel, StrategySpec, load_jsonl_timeseries
from trading_lib.planner.engine import _run_rows
from trading_lib.quant import EntryMetaModel, predict_entry_probability
from trading_lib.timeseries import WalkForwardSplit, build_walk_forward_splits


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _score_row(row: Dict, weights: Dict[str, float]) -> float:
    return sum(float(weights.get(k, 0.0)) * float(row.get(k, 0.0) or 0.0) for k in weights.keys())


def _regime_label(row: Dict) -> str:
    m12 = float(row.get("momentum_12", 0.0) or 0.0)
    p24 = float(row.get("price_change_percent_24h", 0.0) or 0.0)
    if m12 >= 1.0 and p24 >= 0.5:
        return "BULL"
    if m12 <= -1.0 and p24 <= -0.5:
        return "BEAR"
    return "NEUTRAL"


def _vol_label(row: Dict) -> str:
    m3_abs = abs(float(row.get("momentum_3", 0.0) or 0.0))
    liq = float(row.get("liquidity_event_score", 0.0) or 0.0)
    return "HIGH_VOL" if (m3_abs >= 1.5 or liq >= 0.5) else "LOW_VOL"


def _normalize_fed_window(rows: List[Dict], allow_unknown_as_normal: bool) -> List[Dict]:
    if not allow_unknown_as_normal:
        return rows
    out: List[Dict] = []
    for row in rows:
        r = dict(row)
        if r.get("fed_window") in {"", None, "UNKNOWN"}:
            r["fed_window"] = "NORMAL"
        out.append(r)
    return out


def _load_entry_meta_model(path: str) -> EntryMetaModel:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return EntryMetaModel(
        feature_names=list(payload.get("feature_names", [])),
        means={k: float(v) for k, v in payload.get("means", {}).items()},
        stds={k: float(v) for k, v in payload.get("stds", {}).items()},
        weights={k: float(v) for k, v in payload.get("weights", {}).items()},
        bias=float(payload.get("bias", 0.0)),
        prob_threshold=float(payload.get("prob_threshold", 0.55)),
    )


def _apply_meta(row: Dict, meta_model: EntryMetaModel | None, prob_threshold: float, min_weight: float) -> Tuple[float, float]:
    if meta_model is None:
        return 1.0, 1.0
    prob = predict_entry_probability(row, meta_model)
    if prob < prob_threshold:
        return prob, 0.0
    conf = max(0.0, min(1.0, (prob - prob_threshold) / max(1e-9, 1.0 - prob_threshold)))
    weight = min_weight + ((1.0 - min_weight) * conf)
    return prob, weight


def _prepare_rows(
    rows: List[Dict],
    model_weights: Dict[str, float],
    score_threshold: float,
    meta_model: EntryMetaModel | None,
    meta_threshold: float,
    min_weight: float,
    allow_unknown_as_normal: bool,
) -> List[Dict]:
    out: List[Dict] = []
    for row in rows:
        r = dict(row)
        base_score = _score_row(r, model_weights)
        prob, w = _apply_meta(r, meta_model, meta_threshold, min_weight)
        weighted_score = base_score * w
        r["model_score"] = base_score
        r["entry_probability"] = prob
        r["entry_weight"] = w
        r["alpha_score"] = weighted_score
        r["regime_combo"] = f"{_regime_label(r)}__{_vol_label(r)}"
        out.append(r)

    out = _normalize_fed_window(out, allow_unknown_as_normal)
    # Keep score-threshold as planner entry boundary.
    for r in out:
        r["policy_score_threshold"] = score_threshold
    return out


def _apply_block_policy(rows: List[Dict], blocked: Sequence[str]) -> List[Dict]:
    blocked_set = {x.upper() for x in blocked}
    if not blocked_set:
        return rows
    out: List[Dict] = []
    for row in rows:
        r = dict(row)
        if str(r.get("regime_combo", "")).upper() in blocked_set:
            r["alpha_score"] = 0.0
        out.append(r)
    return out


def _candidate_policies(max_block_size: int = 2) -> List[Tuple[str, ...]]:
    combos = [
        "BULL__HIGH_VOL",
        "BULL__LOW_VOL",
        "BEAR__HIGH_VOL",
        "BEAR__LOW_VOL",
        "NEUTRAL__HIGH_VOL",
        "NEUTRAL__LOW_VOL",
    ]
    out: List[Tuple[str, ...]] = [tuple()]
    for k in range(1, max_block_size + 1):
        out.extend(tuple(x) for x in itertools.combinations(combos, k))
    return out


@dataclass
class FoldPolicyResult:
    split_index: int
    blocked_combos: Tuple[str, ...]
    train_net_return_percent: float
    train_mdd_percent: float
    train_trades: int
    test_net_return_percent: float
    test_mdd_percent: float
    test_trades: int


def _rows_in_range(rows: List[Dict], start: str, end: str) -> List[Dict]:
    a, b = _parse_iso(start), _parse_iso(end)
    return [r for r in rows if a <= _parse_iso(r["event_time"]) < b]


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward regime policy optimizer (no look-ahead)")
    parser.add_argument("--dataset", default="/Users/joaquincano/data/binance_lake/gold/signals/decision_features_backfill")
    parser.add_argument("--model-artifact", default="artifacts/quant_model/latest_walkforward_model.json")
    parser.add_argument("--entry-meta-model", default="")
    parser.add_argument("--score-threshold", type=float, default=0.25)
    parser.add_argument("--entry-prob-threshold", type=float, default=0.38)
    parser.add_argument("--entry-min-weight", type=float, default=0.4)
    parser.add_argument("--allow-unknown-fed-window", action="store_true")
    parser.add_argument("--train-days", type=int, default=60)
    parser.add_argument("--test-days", type=int, default=14)
    parser.add_argument("--step-days", type=int, default=14)
    parser.add_argument("--embargo-hours", type=int, default=12)
    parser.add_argument("--max-block-size", type=int, default=2)
    parser.add_argument("--min-train-trades", type=int, default=20)
    parser.add_argument("--max-train-mdd", type=float, default=12.0)
    parser.add_argument("--print-json", action="store_true", help="Also print full JSON report to stdout")
    parser.add_argument("--mlflow-uri", default="sqlite:///artifacts/quant_model/mlflow.db")
    parser.add_argument("--mlflow-experiment", default="quant-regime-optimizer")
    args = parser.parse_args()

    data_glob = args.dataset if "*" in args.dataset else f"{args.dataset}/**/part-*.jsonl"
    rows = load_jsonl_timeseries(data_glob, key_fields=("event_time", "symbol"))
    if not rows:
        raise ValueError(f"No rows found: {data_glob}")

    base = json.loads(Path(args.model_artifact).read_text(encoding="utf-8"))
    weights = {k: float(v) for k, v in base.get("weights", {}).items()}
    if not weights:
        raise ValueError(f"Model artifact has no weights: {args.model_artifact}")

    meta_model = _load_entry_meta_model(args.entry_meta_model) if args.entry_meta_model else None
    prepared = _prepare_rows(
        rows=rows,
        model_weights=weights,
        score_threshold=args.score_threshold,
        meta_model=meta_model,
        meta_threshold=args.entry_prob_threshold,
        min_weight=max(0.0, min(1.0, args.entry_min_weight)),
        allow_unknown_as_normal=args.allow_unknown_fed_window,
    )

    splits: List[WalkForwardSplit] = build_walk_forward_splits(
        rows=[{"event_time": r["event_time"]} for r in prepared],
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        embargo_hours=args.embargo_hours,
    )
    if not splits:
        raise ValueError("No walk-forward splits produced. Increase history or reduce window sizes.")

    policies = _candidate_policies(max_block_size=max(0, args.max_block_size))
    fee_model = FeeModel()
    fold_results: List[FoldPolicyResult] = []

    for idx, split in enumerate(splits, start=1):
        train_rows = _rows_in_range(prepared, split.train_start, split.train_end)
        test_rows = _rows_in_range(prepared, split.test_start, split.test_end)
        if not train_rows or not test_rows:
            continue

        best = None
        for blocked in policies:
            train_eval_rows = _apply_block_policy(train_rows, blocked)
            spec = StrategySpec(
                name="policy_opt_train",
                long_score_threshold=args.score_threshold,
                short_score_threshold=-args.score_threshold,
                allow_trading_in_event_window=False,
                min_open_interest=0.0,
                min_quote_volume_24h=0.0,
                max_gross_exposure_pct=1.0,
                max_symbol_pct=0.4,
            )
            tr, _ = _run_rows(train_eval_rows, spec, fee_model)

            # Feasibility constraints before objective.
            if tr.trades < args.min_train_trades:
                continue
            if tr.max_drawdown_percent > args.max_train_mdd:
                continue

            objective = tr.net_return_percent - (0.25 * tr.max_drawdown_percent)
            cand = (objective, blocked, tr)
            if best is None or cand[0] > best[0]:
                best = cand

        if best is None:
            blocked = tuple()
            tr = _run_rows(
                _apply_block_policy(train_rows, blocked),
                StrategySpec(
                    name="policy_opt_train_fallback",
                    long_score_threshold=args.score_threshold,
                    short_score_threshold=-args.score_threshold,
                    allow_trading_in_event_window=False,
                    min_open_interest=0.0,
                    min_quote_volume_24h=0.0,
                    max_gross_exposure_pct=1.0,
                    max_symbol_pct=0.4,
                ),
                fee_model,
            )[0]
        else:
            _, blocked, tr = best

        spec_test = StrategySpec(
            name="policy_opt_test",
            long_score_threshold=args.score_threshold,
            short_score_threshold=-args.score_threshold,
            allow_trading_in_event_window=False,
            min_open_interest=0.0,
            min_quote_volume_24h=0.0,
            max_gross_exposure_pct=1.0,
            max_symbol_pct=0.4,
        )
        te, _ = _run_rows(_apply_block_policy(test_rows, blocked), spec_test, fee_model)
        fold_results.append(
            FoldPolicyResult(
                split_index=idx,
                blocked_combos=blocked,
                train_net_return_percent=tr.net_return_percent,
                train_mdd_percent=tr.max_drawdown_percent,
                train_trades=tr.trades,
                test_net_return_percent=te.net_return_percent,
                test_mdd_percent=te.max_drawdown_percent,
                test_trades=te.trades,
            )
        )

    if not fold_results:
        raise ValueError("Optimizer did not produce fold results. Relax constraints.")

    from collections import Counter

    policy_counts = Counter(tuple(f.blocked_combos) for f in fold_results)
    summary = {
        "config": {
            "dataset": data_glob,
            "model_artifact": args.model_artifact,
            "entry_meta_model": args.entry_meta_model or None,
            "score_threshold": args.score_threshold,
            "entry_prob_threshold": args.entry_prob_threshold,
            "entry_min_weight": args.entry_min_weight,
            "allow_unknown_fed_window": args.allow_unknown_fed_window,
            "train_days": args.train_days,
            "test_days": args.test_days,
            "step_days": args.step_days,
            "embargo_hours": args.embargo_hours,
            "max_block_size": args.max_block_size,
            "min_train_trades": args.min_train_trades,
            "max_train_mdd": args.max_train_mdd,
        },
        "folds": [asdict(x) for x in fold_results],
        "aggregate": {
            "folds": len(fold_results),
            "avg_test_net_return_percent": sum(f.test_net_return_percent for f in fold_results) / len(fold_results),
            "avg_test_mdd_percent": sum(f.test_mdd_percent for f in fold_results) / len(fold_results),
            "avg_test_trades": sum(f.test_trades for f in fold_results) / len(fold_results),
            "most_selected_policy": {
                "blocked_combos": list(policy_counts.most_common(1)[0][0]),
                "count": policy_counts.most_common(1)[0][1],
            },
            "policy_frequency": {",".join(k) if k else "NONE": v for k, v in policy_counts.items()},
        },
        "leakage_guards": {
            "policy_selection_scope": "train-only per fold",
            "evaluation_scope": "next test fold only",
            "regime_features_used": ["momentum_12", "price_change_percent_24h", "momentum_3", "liquidity_event_score"],
            "future_features_forbidden": ["fwd_return_*", "target", "label", "future_*"],
        },
    }

    out_path = Path("artifacts/quant_model/regime_policy_optimizer_report.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    mlflow.set_tracking_uri(args.mlflow_uri)
    mlflow.set_experiment(args.mlflow_experiment)
    with mlflow.start_run(run_name="regime_policy_optimizer"):
        mlflow.log_params(
            {
                "dataset": data_glob,
                "model_artifact": args.model_artifact,
                "entry_meta_model": args.entry_meta_model or "none",
                "score_threshold": args.score_threshold,
                "entry_prob_threshold": args.entry_prob_threshold,
                "entry_min_weight": args.entry_min_weight,
                "allow_unknown_fed_window": args.allow_unknown_fed_window,
                "train_days": args.train_days,
                "test_days": args.test_days,
                "step_days": args.step_days,
                "embargo_hours": args.embargo_hours,
                "max_block_size": args.max_block_size,
                "min_train_trades": args.min_train_trades,
                "max_train_mdd": args.max_train_mdd,
            }
        )
        agg = summary["aggregate"]
        mlflow.log_metric("folds", float(agg["folds"]))
        mlflow.log_metric("avg_test_net_return_percent", float(agg["avg_test_net_return_percent"]))
        mlflow.log_metric("avg_test_mdd_percent", float(agg["avg_test_mdd_percent"]))
        mlflow.log_metric("avg_test_trades", float(agg["avg_test_trades"]))
        mlflow.log_dict(summary, "regime_policy_optimizer_report.json")

    agg = summary["aggregate"]
    print("=== Regime Policy Optimizer (Walk-Forward) ===")
    print(f"folds: {agg['folds']}")
    print(
        "avg_test | "
        f"net={agg['avg_test_net_return_percent']:.4f}% | "
        f"mdd={agg['avg_test_mdd_percent']:.4f}% | "
        f"trades={agg['avg_test_trades']:.2f}"
    )
    ms = agg["most_selected_policy"]
    blocked = ",".join(ms["blocked_combos"]) if ms["blocked_combos"] else "NONE"
    print(f"most_selected_policy: {blocked} (count={ms['count']})")
    print(f"policy_frequency: {agg['policy_frequency']}")
    if args.print_json:
        print(json.dumps(summary, indent=2))
    print(f"Saved optimizer report -> {out_path}")


if __name__ == "__main__":
    main()

