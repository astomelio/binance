"""
Strategy search orchestrator.

Coordinates the full lifecycle:
1. DISCOVER: evolutionary search for new strategies
2. EVALUATE: walk-forward validation with realistic costs
3. REFINE: focused mutation around top performers
4. MONITOR: detect regime changes and trigger fresh searches
5. PROMOTE: auto-promote stable, profitable genomes

Supports both batch mode (one-shot) and continuous mode (periodic cycles).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ai.agents.evaluator import EvalResult
from ai.agents.genome import StrategyGenome
from ai.agents.refiner import (
    RefinementConfig,
    RefinementResult,
    detect_regime_change,
    refine_cycle,
)
from ai.agents.registry import StrategyRegistry
from ai.agents.search import SearchConfig, SearchResult, run_search
from ai.data.loader import load_decision_features

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorConfig:
    search: SearchConfig = field(default_factory=SearchConfig)
    refine: RefinementConfig = field(default_factory=RefinementConfig)
    regime_check_every_n_cycles: int = 3
    regime_recent_window_days: int = 7
    db_path: str | None = None
    data_db_path: str | None = None
    horizons: list[str] = field(default_factory=lambda: ["4h"])
    symbols: list[str] | None = None


@dataclass
class CycleResult:
    cycle_id: str
    run_id: str
    mode: str  # "search" | "refine" | "regime_check"
    timestamp: str
    search_result: SearchResult | None = None
    refine_result: RefinementResult | None = None
    regime_result: dict[str, Any] | None = None
    error: str | None = None


class StrategyOrchestrator:
    """Coordinates strategy discovery, refinement, and monitoring."""

    def __init__(self, config: OrchestratorConfig | None = None):
        self.config = config or OrchestratorConfig()
        self.registry = StrategyRegistry(db_path=self.config.db_path)
        self.run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self._cycle_count = 0

    def close(self):
        self.registry.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _load_data(self, horizon: str = "4h") -> list[dict]:
        return load_decision_features(
            horizon=horizon,
            symbols=self.config.symbols,
            label_not_null=True,
            db_path=self.config.data_db_path,
        )

    def discover(self, rows: list[dict] | None = None) -> CycleResult:
        """Run evolutionary search to discover new strategies.

        Use when:
        - First run (no genomes in registry)
        - After a regime change
        - Periodically to inject diversity
        """
        self._cycle_count += 1
        cycle_id = f"{self.run_id}_discover_{self._cycle_count}"
        now = datetime.now(timezone.utc).isoformat()

        try:
            if rows is None:
                rows = self._load_data(self.config.horizons[0])

            if not rows:
                return CycleResult(
                    cycle_id=cycle_id, run_id=self.run_id,
                    mode="search", timestamp=now,
                    error="No data available",
                )

            # Seed with top performers from registry if any exist
            seeds: list[StrategyGenome] = []
            top = self.registry.top_genomes(n=self.config.search.elite_count)
            for genome, _ in top:
                seeds.append(genome)

            def on_gen(gen_result, pop):
                logger.info(
                    "[%s] gen=%d best=%.4f mean=%.4f",
                    cycle_id, gen_result.generation,
                    gen_result.best_fitness, gen_result.mean_fitness,
                )

            result = run_search(
                rows,
                config=self.config.search,
                seed_genomes=seeds or None,
                on_generation=on_gen,
            )

            # Persist all evaluated genomes
            self.registry.save_batch(result.population, search_run_id=cycle_id)
            logger.info(
                "discover complete: %d evals, best fitness=%.4f (%s)",
                result.total_evaluations,
                result.best_eval.fitness,
                result.best_genome.genome_id,
            )

            return CycleResult(
                cycle_id=cycle_id, run_id=self.run_id,
                mode="search", timestamp=now,
                search_result=result,
            )

        except Exception as e:
            logger.exception("discover failed")
            return CycleResult(
                cycle_id=cycle_id, run_id=self.run_id,
                mode="search", timestamp=now,
                error=str(e),
            )

    def refine(self, rows: list[dict] | None = None) -> CycleResult:
        """Run refinement cycle on top strategies.

        Use when:
        - New data arrives
        - After a search cycle
        - On a schedule (e.g. every hour)
        """
        self._cycle_count += 1
        cycle_id = f"{self.run_id}_refine_{self._cycle_count}"
        now = datetime.now(timezone.utc).isoformat()

        try:
            if rows is None:
                rows = self._load_data(self.config.horizons[0])
            if not rows:
                return CycleResult(
                    cycle_id=cycle_id, run_id=self.run_id,
                    mode="refine", timestamp=now,
                    error="No data available",
                )

            result = refine_cycle(
                rows, self.registry,
                config=self.config.refine,
                search_run_id=cycle_id,
            )

            logger.info(
                "refine complete: re-eval=%d challengers=%d improvements=%d promotions=%d best=%.4f",
                result.incumbents_re_evaluated,
                result.challengers_evaluated,
                result.improvements_found,
                result.new_promotions,
                result.best_fitness,
            )

            return CycleResult(
                cycle_id=cycle_id, run_id=self.run_id,
                mode="refine", timestamp=now,
                refine_result=result,
            )

        except Exception as e:
            logger.exception("refine failed")
            return CycleResult(
                cycle_id=cycle_id, run_id=self.run_id,
                mode="refine", timestamp=now,
                error=str(e),
            )

    def check_regime(self, rows: list[dict] | None = None) -> CycleResult:
        """Check if market regime has changed.

        If a regime change is detected, triggers a fresh search.
        """
        self._cycle_count += 1
        cycle_id = f"{self.run_id}_regime_{self._cycle_count}"
        now = datetime.now(timezone.utc).isoformat()

        try:
            if rows is None:
                rows = self._load_data(self.config.horizons[0])
            if not rows:
                return CycleResult(
                    cycle_id=cycle_id, run_id=self.run_id,
                    mode="regime_check", timestamp=now,
                    error="No data available",
                )

            result = detect_regime_change(
                rows, self.registry,
                recent_window_days=self.config.regime_recent_window_days,
                config=self.config.refine,
            )

            logger.info(
                "regime check: detected=%s avg_delta=%.4f",
                result.get("regime_change_detected"),
                result.get("avg_fitness_delta", 0),
            )

            return CycleResult(
                cycle_id=cycle_id, run_id=self.run_id,
                mode="regime_check", timestamp=now,
                regime_result=result,
            )

        except Exception as e:
            logger.exception("regime check failed")
            return CycleResult(
                cycle_id=cycle_id, run_id=self.run_id,
                mode="regime_check", timestamp=now,
                error=str(e),
            )

    def run_continuous(
        self,
        max_cycles: int = 50,
        data_refresh_fn=None,
    ) -> list[CycleResult]:
        """Run continuous discover → refine → monitor loop.

        Args:
            max_cycles: maximum number of cycles before stopping
            data_refresh_fn: optional callable() -> list[dict] to reload data each cycle.
                            If None, loads from DuckDB once and reuses.

        Returns:
            List of all cycle results
        """
        results: list[CycleResult] = []
        rows = None

        stats = self.registry.stats()
        needs_initial_search = stats["total_genomes"] < self.config.search.population_size

        for cycle in range(max_cycles):
            if data_refresh_fn:
                rows = data_refresh_fn()
            elif rows is None:
                rows = self._load_data(self.config.horizons[0])

            if not rows:
                logger.warning("No data available, stopping")
                break

            # Decide what to do this cycle
            if needs_initial_search or cycle == 0:
                logger.info("=== CYCLE %d: DISCOVER ===", cycle)
                result = self.discover(rows)
                results.append(result)
                needs_initial_search = False
                continue

            # Periodic regime check
            if cycle % self.config.regime_check_every_n_cycles == 0:
                logger.info("=== CYCLE %d: REGIME CHECK ===", cycle)
                regime_result = self.check_regime(rows)
                results.append(regime_result)

                if (
                    regime_result.regime_result
                    and regime_result.regime_result.get("regime_change_detected")
                ):
                    logger.warning("Regime change detected, triggering fresh search")
                    search_result = self.discover(rows)
                    results.append(search_result)
                    continue

            # Default: refine
            logger.info("=== CYCLE %d: REFINE ===", cycle)
            refine_result = self.refine(rows)
            results.append(refine_result)

        return results

    def status(self) -> dict[str, Any]:
        """Current status of the orchestrator and registry."""
        stats = self.registry.stats()
        promoted = self.registry.promoted_genomes()
        top = self.registry.top_genomes(n=5)

        return {
            "run_id": self.run_id,
            "cycle_count": self._cycle_count,
            "registry": stats,
            "promoted_count": len(promoted),
            "top_5": [
                {
                    "genome_id": g.genome_id,
                    "fitness": m["fitness"],
                    "mean_return": m["mean_return"],
                    "mean_sharpe": m["mean_sharpe"],
                    "stability": m["stability"],
                }
                for g, m in top
            ],
        }
