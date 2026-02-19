from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable


class LakeWriter:
    """Writes JSONL events to bronze/silver/gold partitions in a local data lake."""

    def __init__(self, lake_root: str) -> None:
        self.lake_root = Path(lake_root)

    def _partition_path(self, layer: str, source: str, dataset: str, event_time: datetime) -> Path:
        dt = event_time.astimezone(timezone.utc)
        return (
            self.lake_root
            / layer
            / source
            / dataset
            / f"dt={dt:%Y-%m-%d}"
            / f"hour={dt:%H}"
        )

    def write_events(self, layer: str, source: str, dataset: str, events: Iterable[Dict]) -> Path:
        now = datetime.now(timezone.utc)
        out_dir = self._partition_path(layer, source, dataset, now)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"part-{now:%Y%m%dT%H%M%S}.jsonl"

        with out_file.open("w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return out_file

    def write_events_by_event_time(
        self, layer: str, source: str, dataset: str, events: Iterable[Dict]
    ) -> list[Path]:
        """Write events partitioned by each event's event_time (for historical backfill)."""
        paths: list[Path] = []
        buffer: dict[tuple[str, str], list[Dict]] = {}
        for event in events:
            raw_ts = event.get("event_time", "")
            try:
                ts = (
                    datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                    if isinstance(raw_ts, str)
                    else raw_ts
                )
                if not getattr(ts, "tzinfo", None):
                    ts = ts.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                ts = datetime.now(timezone.utc)
            key = (ts.strftime("%Y-%m-%d"), ts.strftime("%H"))
            buffer.setdefault(key, []).append(event)

        for (date_str, hour_str), batch in buffer.items():
            out_dir = (
                self.lake_root / layer / source / dataset / f"dt={date_str}" / f"hour={hour_str}"
            )
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / "part-0000.jsonl"
            with out_file.open("w", encoding="utf-8") as f:
                for ev in batch:
                    f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            paths.append(out_file)
        return paths

