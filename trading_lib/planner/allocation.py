from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .specs import StrategySpec


@dataclass
class AllocationDecision:
    symbol: str
    side: str
    score: float
    allocation_pct: float


def _is_row_tradeable(row: Dict, spec: StrategySpec) -> bool:
    if not spec.allow_trading_in_event_window and row.get("fed_window") != "NORMAL":
        return False
    if float(row.get("open_interest", 0) or 0) < spec.min_open_interest:
        return False
    if float(row.get("quote_volume_24h", 0) or 0) < spec.min_quote_volume_24h:
        return False
    return True


def _side_from_score(score: float, spec: StrategySpec) -> str:
    if score >= spec.long_score_threshold:
        return "LONG"
    if score <= spec.short_score_threshold:
        return "SHORT"
    return "NO_TRADE"


def compute_model_allocations(
    snapshot_rows: List[Dict],
    spec: StrategySpec,
    max_gross_exposure_pct: float = 1.0,
    max_symbol_pct: float = 0.4,
) -> List[AllocationDecision]:
    """Compute multi-currency portfolio allocations from model scores.

    - Uses |alpha_score| as relative strength.
    - Applies per-symbol cap and total gross cap.
    - Returns only actionable symbols (LONG/SHORT).
    """
    if max_gross_exposure_pct <= 0:
        return []

    candidates: List[Dict] = []
    for row in snapshot_rows:
        if not _is_row_tradeable(row, spec):
            continue
        symbol = row.get("symbol", "")
        if not symbol:
            continue
        score = float(row.get("alpha_score", 0) or 0)
        side = _side_from_score(score, spec)
        if side == "NO_TRADE":
            continue
        strength = abs(score)
        if strength <= 0:
            continue
        candidates.append({"symbol": symbol, "side": side, "score": score, "strength": strength})

    if not candidates:
        return []

    total_strength = sum(c["strength"] for c in candidates)
    if total_strength <= 0:
        return []

    # First pass: proportional weights with per-symbol cap.
    allocs: List[AllocationDecision] = []
    consumed = 0.0
    uncapped: List[Dict] = []
    for c in candidates:
        raw = max_gross_exposure_pct * (c["strength"] / total_strength)
        clipped = min(raw, max_symbol_pct)
        consumed += clipped
        allocs.append(
            AllocationDecision(
                symbol=c["symbol"],
                side=c["side"],
                score=c["score"],
                allocation_pct=clipped,
            )
        )
        if raw > max_symbol_pct:
            uncapped.append(c)

    # Second pass: redistribute remainder to non-capped positions (if any).
    remainder = max(0.0, max_gross_exposure_pct - consumed)
    if remainder > 0:
        growable = [a for a in allocs if a.allocation_pct < max_symbol_pct]
        if growable:
            grow_strength = sum(abs(a.score) for a in growable)
            if grow_strength > 0:
                for a in growable:
                    add = remainder * (abs(a.score) / grow_strength)
                    a.allocation_pct = min(max_symbol_pct, a.allocation_pct + add)

    # Final normalization to never exceed gross cap due to floating rounding.
    total_alloc = sum(a.allocation_pct for a in allocs)
    if total_alloc > max_gross_exposure_pct and total_alloc > 0:
        scale = max_gross_exposure_pct / total_alloc
        for a in allocs:
            a.allocation_pct *= scale

    return allocs

