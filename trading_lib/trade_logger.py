from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class TradingLogger:
    """Structured JSONL logger for backtest/live trading events."""

    def __init__(self, run_name: str, root_dir: str = "logs/trading") -> None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_id = f"{run_name}-{ts}"
        self.log_path = Path(root_dir) / f"{self.run_id}.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _to_jsonable(self, value: Any) -> Any:
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, dict):
            return {k: self._to_jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._to_jsonable(v) for v in value]
        return value

    def event(self, event_type: str, payload: Dict[str, Any]) -> None:
        row = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "event_type": event_type,
            "payload": self._to_jsonable(payload),
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

