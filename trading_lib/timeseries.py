from __future__ import annotations

import glob
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Sequence, Tuple


def _parse_event_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_jsonl_timeseries(path_glob: str, key_fields: Sequence[str]) -> List[Dict]:
    """Load jsonl rows sorted by event_time and deduped by key_fields."""
    rows: List[Dict] = []
    for file in glob.glob(path_glob, recursive=True):
        with open(file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))

    rows = [r for r in rows if r.get("event_time")]
    rows.sort(key=lambda x: x["event_time"])

    dedup: Dict[Tuple, Dict] = {}
    for row in rows:
        key = tuple(row.get(k) for k in key_fields)
        dedup[key] = row  # keep latest occurrence for same key

    out = list(dedup.values())
    out.sort(key=lambda x: x["event_time"])
    return out


@dataclass
class WalkForwardSplit:
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_rows: int
    test_rows: int


def build_walk_forward_splits(
    rows: List[Dict],
    train_days: int = 90,
    test_days: int = 14,
    step_days: int = 14,
    embargo_hours: int = 12,
) -> List[WalkForwardSplit]:
    """Create walk-forward windows with embargo to avoid look-ahead leakage."""
    if not rows:
        return []

    ts_rows = [(row, _parse_event_time(row["event_time"])) for row in rows]
    ts_rows.sort(key=lambda x: x[1])
    min_ts = ts_rows[0][1]
    max_ts = ts_rows[-1][1]

    splits: List[WalkForwardSplit] = []
    cursor = min_ts + timedelta(days=train_days)

    while cursor + timedelta(days=test_days) <= max_ts:
        train_end = cursor - timedelta(hours=embargo_hours)
        train_start = train_end - timedelta(days=train_days)
        test_start = cursor
        test_end = cursor + timedelta(days=test_days)

        train_count = len([1 for _, ts in ts_rows if train_start <= ts < train_end])
        test_count = len([1 for _, ts in ts_rows if test_start <= ts < test_end])
        if train_count > 0 and test_count > 0:
            splits.append(
                WalkForwardSplit(
                    train_start=train_start.isoformat(),
                    train_end=train_end.isoformat(),
                    test_start=test_start.isoformat(),
                    test_end=test_end.isoformat(),
                    train_rows=train_count,
                    test_rows=test_count,
                )
            )

        cursor += timedelta(days=step_days)

    return splits

