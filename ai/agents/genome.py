"""
Strategy Genome: parametric definition of a trading strategy.

A genome encodes every decision a strategy makes:
- Which features drive the signal and their weights
- Entry/exit thresholds
- Allocation sizing and risk limits
- Horizon and symbol filtering

Genomes support mutation and crossover for evolutionary search.
"""

from __future__ import annotations

import hashlib
import json
import random
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

# Features available in decision_features that carry potential alpha.
ALPHA_FEATURES = [
    "alpha_microstructure_score",
    "momentum_score",
    "basis_bps",
    "funding_rate_8h",
    "long_short_account_ratio",
    "buy_sell_ratio",
    "fear_greed_value",
    "btc_dominance",
    "liquidity_event_score",
    "cross_exchange_score",
    "dex_alpha_score",
    "cross_exchange_mean_diff_bps",
    "dex_cex_basis_bps",
    "dex_txn_imbalance_24h",
    "momentum_3",
    "momentum_12",
    "price_change_percent_24h",
]


@dataclass
class StrategyGenome:
    """Complete parametric definition of a strategy."""

    # Identity
    genome_id: str = ""
    parent_ids: list[str] = field(default_factory=list)
    generation: int = 0

    # Feature weights: which features contribute and how much.
    # Negative weight = contrarian use of that feature.
    feature_weights: dict[str, float] = field(default_factory=dict)

    # Entry thresholds: score must exceed these to take a position.
    long_threshold: float = 0.10
    short_threshold: float = -0.10

    # Allocation sizing
    min_allocation: float = 0.10
    max_allocation: float = 0.40

    # Risk limits
    max_exposure: float = 1.0
    max_per_symbol: float = 0.40
    max_drawdown_kill: float = 0.15

    # Horizon and universe
    horizon: str = "4h"

    # Exit rules
    max_bars_held: int | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None

    def __post_init__(self):
        if not self.genome_id:
            self.genome_id = self._hash()

    def _hash(self) -> str:
        blob = json.dumps(self.to_params(), sort_keys=True)
        return hashlib.md5(blob.encode()).hexdigest()[:12]

    def to_params(self) -> dict[str, Any]:
        return {
            "feature_weights": dict(self.feature_weights),
            "long_threshold": self.long_threshold,
            "short_threshold": self.short_threshold,
            "min_allocation": self.min_allocation,
            "max_allocation": self.max_allocation,
            "max_exposure": self.max_exposure,
            "max_per_symbol": self.max_per_symbol,
            "max_drawdown_kill": self.max_drawdown_kill,
            "horizon": self.horizon,
            "max_bars_held": self.max_bars_held,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
        }

    def to_dict(self) -> dict[str, Any]:
        d = self.to_params()
        d["genome_id"] = self.genome_id
        d["parent_ids"] = self.parent_ids
        d["generation"] = self.generation
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StrategyGenome:
        return cls(
            genome_id=d.get("genome_id", ""),
            parent_ids=d.get("parent_ids", []),
            generation=d.get("generation", 0),
            feature_weights=d.get("feature_weights", {}),
            long_threshold=d.get("long_threshold", 0.10),
            short_threshold=d.get("short_threshold", -0.10),
            min_allocation=d.get("min_allocation", 0.10),
            max_allocation=d.get("max_allocation", 0.40),
            max_exposure=d.get("max_exposure", 1.0),
            max_per_symbol=d.get("max_per_symbol", 0.40),
            max_drawdown_kill=d.get("max_drawdown_kill", 0.15),
            horizon=d.get("horizon", "4h"),
            max_bars_held=d.get("max_bars_held"),
            stop_loss_pct=d.get("stop_loss_pct"),
            take_profit_pct=d.get("take_profit_pct"),
        )


def random_genome(generation: int = 0) -> StrategyGenome:
    """Generate a random strategy genome."""
    n_features = random.randint(3, len(ALPHA_FEATURES))
    chosen = random.sample(ALPHA_FEATURES, n_features)
    weights = {}
    for f in chosen:
        weights[f] = round(random.uniform(-1.0, 1.0), 3)

    # Normalize so |weights| sums to ~1
    total = sum(abs(w) for w in weights.values())
    if total > 0:
        weights = {k: round(v / total, 4) for k, v in weights.items()}

    lt = round(random.uniform(0.03, 0.25), 3)
    st = -round(random.uniform(0.03, 0.25), 3)

    g = StrategyGenome(
        generation=generation,
        feature_weights=weights,
        long_threshold=lt,
        short_threshold=st,
        min_allocation=round(random.uniform(0.05, 0.20), 2),
        max_allocation=round(random.uniform(0.20, 0.50), 2),
        max_exposure=round(random.choice([0.6, 0.8, 1.0]), 1),
        max_per_symbol=round(random.choice([0.20, 0.30, 0.40]), 2),
        max_drawdown_kill=round(random.uniform(0.08, 0.25), 2),
        horizon=random.choice(["1h", "4h"]),
        max_bars_held=random.choice([None, None, 6, 12, 24]),
        stop_loss_pct=random.choice([None, None, -0.5, -1.0, -1.5]),
        take_profit_pct=random.choice([None, None, 1.0, 2.0, 3.0]),
    )
    g.genome_id = g._hash()
    return g


def mutate(genome: StrategyGenome, strength: float = 0.3) -> StrategyGenome:
    """Create a mutated copy. strength in [0, 1] controls mutation magnitude."""
    child = deepcopy(genome)
    child.parent_ids = [genome.genome_id]
    child.generation = genome.generation + 1

    def _perturb(val: float, lo: float, hi: float) -> float:
        delta = (hi - lo) * strength * random.gauss(0, 1)
        return round(max(lo, min(hi, val + delta)), 4)

    # Mutate feature weights (add/remove/perturb)
    if random.random() < 0.3 and len(child.feature_weights) > 2:
        drop = random.choice(list(child.feature_weights.keys()))
        del child.feature_weights[drop]

    if random.random() < 0.3:
        available = [f for f in ALPHA_FEATURES if f not in child.feature_weights]
        if available:
            new_f = random.choice(available)
            child.feature_weights[new_f] = round(random.uniform(-0.5, 0.5), 3)

    for f in list(child.feature_weights):
        if random.random() < 0.5:
            child.feature_weights[f] = _perturb(child.feature_weights[f], -1.0, 1.0)

    total = sum(abs(w) for w in child.feature_weights.values())
    if total > 0:
        child.feature_weights = {k: round(v / total, 4) for k, v in child.feature_weights.items()}

    if random.random() < 0.4:
        child.long_threshold = _perturb(child.long_threshold, 0.02, 0.30)
    if random.random() < 0.4:
        child.short_threshold = _perturb(child.short_threshold, -0.30, -0.02)
    if random.random() < 0.3:
        child.min_allocation = _perturb(child.min_allocation, 0.05, 0.25)
    if random.random() < 0.3:
        child.max_allocation = _perturb(child.max_allocation, 0.15, 0.60)
    if random.random() < 0.2:
        child.max_exposure = round(random.choice([0.6, 0.8, 1.0]), 1)
    if random.random() < 0.15:
        child.horizon = random.choice(["1h", "4h"])

    child.genome_id = child._hash()
    return child


def crossover(a: StrategyGenome, b: StrategyGenome) -> StrategyGenome:
    """Combine two genomes by blending weights and picking traits."""
    child = StrategyGenome(
        parent_ids=[a.genome_id, b.genome_id],
        generation=max(a.generation, b.generation) + 1,
    )

    # Blend feature weights from both parents
    all_features = set(a.feature_weights) | set(b.feature_weights)
    for f in all_features:
        wa = a.feature_weights.get(f, 0.0)
        wb = b.feature_weights.get(f, 0.0)
        alpha = random.uniform(0.3, 0.7)
        blended = alpha * wa + (1 - alpha) * wb
        if abs(blended) > 0.01:
            child.feature_weights[f] = round(blended, 4)

    total = sum(abs(w) for w in child.feature_weights.values())
    if total > 0:
        child.feature_weights = {k: round(v / total, 4) for k, v in child.feature_weights.items()}

    # Pick thresholds/sizing from one parent randomly
    pick = random.choice([a, b])
    child.long_threshold = pick.long_threshold
    child.short_threshold = pick.short_threshold
    pick2 = random.choice([a, b])
    child.min_allocation = pick2.min_allocation
    child.max_allocation = pick2.max_allocation
    child.max_exposure = random.choice([a, b]).max_exposure
    child.max_per_symbol = random.choice([a, b]).max_per_symbol
    child.max_drawdown_kill = random.choice([a, b]).max_drawdown_kill
    child.horizon = random.choice([a, b]).horizon
    child.max_bars_held = random.choice([a, b]).max_bars_held
    child.stop_loss_pct = random.choice([a, b]).stop_loss_pct
    child.take_profit_pct = random.choice([a, b]).take_profit_pct

    child.genome_id = child._hash()
    return child
