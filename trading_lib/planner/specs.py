from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class StrategySpec:
    name: str
    long_score_threshold: float
    short_score_threshold: float
    min_open_interest: float = 0.0
    min_quote_volume_24h: float = 0.0
    allow_trading_in_event_window: bool = False
    max_gross_exposure_pct: float = 1.0
    max_symbol_pct: float = 0.4

    @staticmethod
    def from_dict(payload: Dict) -> "StrategySpec":
        return StrategySpec(
            name=str(payload["name"]),
            long_score_threshold=float(payload.get("long_score_threshold", 0.4)),
            short_score_threshold=float(payload.get("short_score_threshold", -0.4)),
            min_open_interest=float(payload.get("min_open_interest", 0.0)),
            min_quote_volume_24h=float(payload.get("min_quote_volume_24h", 0.0)),
            allow_trading_in_event_window=bool(payload.get("allow_trading_in_event_window", False)),
            max_gross_exposure_pct=float(payload.get("max_gross_exposure_pct", 1.0)),
            max_symbol_pct=float(payload.get("max_symbol_pct", 0.4)),
        )


def load_specs_from_dicts(items: List[Dict]) -> List[StrategySpec]:
    return [StrategySpec.from_dict(item) for item in items]

