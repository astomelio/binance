from __future__ import annotations

from trading_lib import build_walk_forward_splits, load_jsonl_timeseries


def main() -> None:
    rows = load_jsonl_timeseries(
        "data_lake/gold/signals/decision_features/**/part-*.jsonl",
        key_fields=("event_time", "symbol"),
    )
    print(f"Loaded rows: {len(rows)}")
    if rows:
        print(f"Range: {rows[0]['event_time']} -> {rows[-1]['event_time']}")

    splits = build_walk_forward_splits(
        rows=rows,
        train_days=30,
        test_days=7,
        step_days=7,
        embargo_hours=12,
    )
    print(f"Walk-forward splits: {len(splits)}")
    for i, s in enumerate(splits[:5], start=1):
        print(
            f"[{i}] train=({s.train_start} -> {s.train_end}) "
            f"test=({s.test_start} -> {s.test_end}) "
            f"rows(train={s.train_rows}, test={s.test_rows})"
        )


if __name__ == "__main__":
    main()

