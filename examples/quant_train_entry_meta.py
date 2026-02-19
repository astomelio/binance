from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_lib import FeeModel
from trading_lib.quant import build_labeled_rows, train_entry_meta_model
from trading_lib.timeseries import load_jsonl_timeseries


def main() -> None:
    parser = argparse.ArgumentParser(description="Train entry meta-model (logistic) to predict profitable entries")
    parser.add_argument(
        "--dataset",
        default="/Users/joaquincano/data/binance_lake/gold/signals/decision_features_backfill",
        help="Path to decision features directory or glob",
    )
    parser.add_argument(
        "--base-model-artifact",
        default="artifacts/quant_model/latest_walkforward_model.json",
        help="Path to base quant model artifact with feature weights",
    )
    parser.add_argument("--horizon", default="fwd_return_4h", choices=["fwd_return_1h", "fwd_return_4h", "fwd_return_24h"])
    args = parser.parse_args()

    data_glob = args.dataset if "*" in args.dataset else f"{args.dataset}/**/part-*.jsonl"
    rows = load_jsonl_timeseries(data_glob, key_fields=("event_time", "symbol"))
    labeled = build_labeled_rows(rows)
    base = json.loads(Path(args.base_model_artifact).read_text(encoding="utf-8"))
    weights = base.get("weights", {})
    if not weights:
        raise ValueError(f"Base model artifact has no weights: {args.base_model_artifact}")

    fee_model = FeeModel()
    fee_percent = fee_model.round_trip_fee_percent("futures", is_maker=True)

    model, report = train_entry_meta_model(
        labeled_rows=labeled,
        base_weights=weights,
        fee_percent=fee_percent,
        horizon=args.horizon,
    )

    artifact = {
        "type": "entry_meta_logistic",
        "horizon": args.horizon,
        "source_dataset": data_glob,
        "source_base_model": args.base_model_artifact,
        "feature_names": model.feature_names,
        "means": model.means,
        "stds": model.stds,
        "weights": model.weights,
        "bias": model.bias,
        "prob_threshold": model.prob_threshold,
        "validation_report": {
            "samples": report.samples,
            "hit_rate_percent": report.hit_rate_percent,
            "selected_rate_percent": report.selected_rate_percent,
            "avg_net_return_percent": report.avg_net_return_percent,
            "threshold": report.threshold,
        },
    }

    out = Path("artifacts/quant_model/entry_meta_model.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(json.dumps(artifact["validation_report"], indent=2))
    print(f"Saved entry meta model -> {out}")


if __name__ == "__main__":
    main()

