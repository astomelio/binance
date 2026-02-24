"""
Strategy refiner: continuous improvement of top genomes.

The refiner takes the best genomes from the registry and:
1. Re-evaluates them with the latest data (decay old fitness)
2. Runs focused mutation around the best parameter regions
3. Compares incumbent vs challengers to detect regime changes
4. Promotes genomes that pass consistency checks

This is the "real-time" loop that keeps strategies fresh.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ai.agents.evaluator import EvalResult, evaluate_genome
from ai.agents.genome import StrategyGenome, mutate
from ai.agents.registry import StrategyRegistry

logger = logging.getLogger(__name__)


@dataclass
class RefinementConfig:
    top_n_to_refine: int = 10
    mutations_per_genome: int = 5
    mutation_strength: float = 0.15  # tighter than search — fine-tuning
    min_stability: float = 0.50
    min_trades: int = 5
    promotion_min_fitness: float = 0.10
    promotion_min_stability: float = 0.60
    promotion_min_folds: int = 3

    train_days: int = 30
    test_days: int = 7
    step_days: int = 7
    embargo_hours: int = 12
    fee_percent: float = 0.04
    slippage_percent: float = 0.02


@dataclass
class RefinementResult:
    incumbents_re_evaluated: int
    challengers_evaluated: int
    improvements_found: int
    new_promotions: int
    best_fitness: float
    best_genome_id: str
    timestamp: str


def refine_cycle(
    rows: list[dict],
    registry: StrategyRegistry,
    config: RefinementConfig | None = None,
    search_run_id: str = "",
) -> RefinementResult:
    """
    Run one refinement cycle:
    1. Load top genomes from registry
    2. Re-evaluate each with current data
    3. Generate focused mutations around the best
    4. Save results, promote qualifying genomes

    Call this periodically (e.g. after each data refresh) for continuous improvement.
    """
    cfg = config or RefinementConfig()
    now = datetime.now(timezone.utc).isoformat()

    # 1. Load incumbents
    top = registry.top_genomes(
        n=cfg.top_n_to_refine,
        min_stability=cfg.min_stability,
        min_trades=cfg.min_trades,
    )

    incumbents_evaluated = 0
    challengers_evaluated = 0
    improvements = 0
    promotions = 0
    best_fitness = -999.0
    best_genome_id = ""

    # 2. Re-evaluate incumbents on latest data
    re_evaluated: list[tuple[StrategyGenome, EvalResult, float]] = []
    for genome, old_metrics in top:
        old_fitness = old_metrics.get("fitness", -999)
        result = evaluate_genome(
            genome, rows,
            train_days=cfg.train_days,
            test_days=cfg.test_days,
            step_days=cfg.step_days,
            embargo_hours=cfg.embargo_hours,
            fee_percent=cfg.fee_percent,
            slippage_percent=cfg.slippage_percent,
        )
        if not result:
            continue
        incumbents_evaluated += 1
        registry.save(genome, result, search_run_id)
        re_evaluated.append((genome, result, old_fitness))

        if result.fitness > best_fitness:
            best_fitness = result.fitness
            best_genome_id = genome.genome_id

        if result.fitness > old_fitness + 0.01:
            improvements += 1

        logger.info(
            "re-eval %s: old=%.4f new=%.4f (delta=%.4f)",
            genome.genome_id, old_fitness, result.fitness, result.fitness - old_fitness,
        )

    # 3. Focused mutations around the best performers
    re_evaluated.sort(key=lambda x: x[1].fitness, reverse=True)
    parents = re_evaluated[:max(3, cfg.top_n_to_refine // 3)]

    for genome, parent_result, _ in parents:
        for _ in range(cfg.mutations_per_genome):
            child = mutate(genome, strength=cfg.mutation_strength)
            result = evaluate_genome(
                child, rows,
                train_days=cfg.train_days,
                test_days=cfg.test_days,
                step_days=cfg.step_days,
                embargo_hours=cfg.embargo_hours,
                fee_percent=cfg.fee_percent,
                slippage_percent=cfg.slippage_percent,
            )
            if not result:
                continue
            challengers_evaluated += 1
            registry.save(child, result, search_run_id)

            if result.fitness > parent_result.fitness:
                improvements += 1
                logger.info(
                    "improvement: %s (%.4f) > parent %s (%.4f)",
                    child.genome_id, result.fitness,
                    genome.genome_id, parent_result.fitness,
                )

            if result.fitness > best_fitness:
                best_fitness = result.fitness
                best_genome_id = child.genome_id

    # 4. Auto-promote qualifying genomes
    top_after = registry.top_genomes(n=cfg.top_n_to_refine, min_stability=cfg.promotion_min_stability)
    for genome, metrics in top_after:
        if (
            metrics.get("fitness", 0) >= cfg.promotion_min_fitness
            and metrics.get("stability", 0) >= cfg.promotion_min_stability
            and metrics.get("n_folds", 0) >= cfg.promotion_min_folds
        ):
            existing = registry.promoted_genomes()
            already_promoted = any(g.genome_id == genome.genome_id for g, _ in existing)
            if not already_promoted:
                registry.promote(
                    genome.genome_id,
                    notes=f"auto-promoted at {now}, fitness={metrics.get('fitness'):.4f}",
                )
                promotions += 1
                logger.info("promoted %s fitness=%.4f", genome.genome_id, metrics["fitness"])

    return RefinementResult(
        incumbents_re_evaluated=incumbents_evaluated,
        challengers_evaluated=challengers_evaluated,
        improvements_found=improvements,
        new_promotions=promotions,
        best_fitness=best_fitness,
        best_genome_id=best_genome_id,
        timestamp=now,
    )


def detect_regime_change(
    rows: list[dict],
    registry: StrategyRegistry,
    recent_window_days: int = 7,
    config: RefinementConfig | None = None,
) -> dict[str, Any]:
    """
    Compare promoted genomes' performance on recent data vs historical.
    Large drops indicate potential regime change requiring fresh search.
    """
    cfg = config or RefinementConfig()
    promoted = registry.promoted_genomes()
    if not promoted:
        return {"regime_change_detected": False, "reason": "no promoted genomes"}

    # Filter rows to recent window only
    from trading_lib.timeseries import _parse_event_time
    from datetime import timedelta
    if not rows:
        return {"regime_change_detected": False, "reason": "no data"}

    max_ts = max(_parse_event_time(r["event_time"]) for r in rows)
    cutoff = max_ts - timedelta(days=recent_window_days)
    recent_rows = [r for r in rows if _parse_event_time(r["event_time"]) >= cutoff]

    if len(recent_rows) < 20:
        return {"regime_change_detected": False, "reason": "insufficient recent data"}

    drops = []
    for genome, metrics in promoted:
        result = evaluate_genome(
            genome, recent_rows,
            train_days=cfg.train_days,
            test_days=cfg.test_days,
            step_days=cfg.step_days,
            embargo_hours=cfg.embargo_hours,
            fee_percent=cfg.fee_percent,
            slippage_percent=cfg.slippage_percent,
            min_folds=1,
        )
        if not result:
            continue
        old_fitness = metrics.get("fitness", 0)
        delta = result.fitness - old_fitness
        drops.append({
            "genome_id": genome.genome_id,
            "historical_fitness": old_fitness,
            "recent_fitness": result.fitness,
            "delta": delta,
        })

    if not drops:
        return {"regime_change_detected": False, "reason": "no evaluations"}

    avg_delta = sum(d["delta"] for d in drops) / len(drops)
    significant_drops = sum(1 for d in drops if d["delta"] < -0.15)

    detected = significant_drops >= len(drops) * 0.5 or avg_delta < -0.10
    return {
        "regime_change_detected": detected,
        "avg_fitness_delta": round(avg_delta, 4),
        "significant_drops": significant_drops,
        "total_evaluated": len(drops),
        "details": drops,
        "recommendation": "trigger fresh search" if detected else "continue refinement",
    }
