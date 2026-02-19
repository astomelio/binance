from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from .engine import PlannerFoldResult, PlannerResult
from .specs import StrategySpec


def write_experiment(
    experiment_name: str,
    specs: List[StrategySpec],
    results: List[PlannerResult],
    fold_results: List[PlannerFoldResult],
    root_dir: str = "logs/strategy_planner",
) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(root_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{experiment_name}-{ts}.json"

    payload: Dict = {
        "experiment_name": experiment_name,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "specs": [asdict(s) for s in specs],
        "results": [asdict(r) for r in results],
        "fold_results": [asdict(f) for f in fold_results],
    }
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_file

