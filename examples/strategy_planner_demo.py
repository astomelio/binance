from __future__ import annotations

import argparse
import json

from trading_lib import (
    FeeModel,
    evaluate_strategy_walk_forward,
    load_jsonl_timeseries,
    load_specs_from_dicts,
    rank_results,
    write_experiment,
)


def main(config_path: str = "configs/strategy_planner/specs.json") -> None:
    cfg = json.loads(open(config_path, "r", encoding="utf-8").read())
    specs = load_specs_from_dicts(cfg["strategies"])
    data_glob = cfg["data_glob"]
    wf = cfg.get("walk_forward", {})

    rows = load_jsonl_timeseries(data_glob, key_fields=("event_time", "symbol"))
    if not rows:
        raise ValueError(f"No data found for planner at: {data_glob}")

    fee_model = FeeModel()
    planner_results = []
    all_folds = []

    for spec in specs:
        result, folds = evaluate_strategy_walk_forward(
            rows=rows,
            spec=spec,
            fee_model=fee_model,
            train_days=int(wf.get("train_days", 30)),
            test_days=int(wf.get("test_days", 7)),
            step_days=int(wf.get("step_days", 7)),
            embargo_hours=int(wf.get("embargo_hours", 12)),
        )
        planner_results.append(result)
        all_folds.extend(folds)

    ranked = rank_results(planner_results)
    out_file = write_experiment(
        experiment_name=cfg.get("experiment_name", "strategy-planner"),
        specs=specs,
        results=ranked,
        fold_results=all_folds,
    )

    print("=== Strategy Planner Leaderboard ===")
    for i, r in enumerate(ranked, start=1):
        print(
            f"[{i}] {r.strategy_name} | trades={r.trades} | "
            f"net={r.net_return_percent:.3f}% | win={r.win_rate:.2f}% | "
            f"mdd={r.max_drawdown_percent:.3f}% | turnover={r.turnover_percent:.2f}%"
        )
    print(f"Experiment saved: {out_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run strategy planner experiment")
    parser.add_argument(
        "config_path",
        nargs="?",
        default="configs/strategy_planner/specs.json",
        help="Path to planner config JSON",
    )
    args = parser.parse_args()
    main(args.config_path)

