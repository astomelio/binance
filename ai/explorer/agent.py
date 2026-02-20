"""
Agente de exploración: selecciona estrategias, varía parámetros, ejecuta backtests.
Uso programático para pipelines automáticos.
"""

from __future__ import annotations

import random
from typing import Any

from ai.data.loader import load_decision_features

from ai.explorer.experiment import run_single, run_grid, run_all_strategies
from ai.explorer.registry import get_registry, list_strategies
from ai.explorer.types import ExperimentResult, ExplorationReport


class ExplorationAgent:
    """
    Agente que explora estrategias automáticamente.
    - run_quick: todas las estrategias con params default
    - run_grid: grid search por estrategia
    - run_full: explora todas las estrategias con variación de params
    """

    def __init__(
        self,
        horizon: str = "4h",
        fee_percent: float = 0.04,
        symbols: list[str] | None = None,
        db_path: str | None = None,
    ):
        self.horizon = horizon
        self.fee_percent = fee_percent
        self.symbols = symbols
        self.db_path = db_path

    def load_data(self) -> list[dict]:
        """Carga decision_features desde DuckDB."""
        return load_decision_features(
            horizon=self.horizon,
            symbols=self.symbols,
            label_not_null=True,
            db_path=self.db_path,
        )

    def run_quick(
        self,
        strategy_ids: list[str] | None = None,
    ) -> ExplorationReport:
        """Ejecuta todas las estrategias con params por defecto."""
        rows = self.load_data()
        if not rows:
            return ExplorationReport(
                results=[],
                best_overall=None,
                best_by_strategy={},
                data_summary={"error": "No data", "rows": 0},
            )
        results = run_all_strategies(
            rows,
            strategy_ids=strategy_ids,
            horizon=self.horizon,
            fee_percent=self.fee_percent,
            symbols=self.symbols,
        )
        return self._build_report(results, rows)

    def run_grid(
        self,
        strategy_id: str,
        param_overrides: dict[str, list] | None = None,
        max_combos: int = 50,
    ) -> ExplorationReport:
        """Grid search sobre una estrategia."""
        rows = self.load_data()
        if not rows:
            return ExplorationReport(
                results=[],
                best_overall=None,
                best_by_strategy={},
                data_summary={"error": "No data", "rows": 0},
            )
        results = run_grid(
            rows,
            strategy_id=strategy_id,
            horizon=self.horizon,
            fee_percent=self.fee_percent,
            symbols=self.symbols,
            param_overrides=param_overrides,
            max_combos=max_combos,
        )
        # Filter invalid mean_reversion: oversold < overbought
        if strategy_id == "mean_reversion":
            results = [r for r in results if r.params.get("oversold", 0) < r.params.get("overbought", 0)]
        return self._build_report(results, rows)

    def run_full(
        self,
        strategy_ids: list[str] | None = None,
        max_experiments_per_strategy: int = 30,
        horizons: list[str] | None = None,
    ) -> ExplorationReport:
        """
        Explora todas las estrategias con muestreo de params.
        Para cada estrategia: grid o random sample de param_ranges.
        """
        rows = self.load_data()
        if not rows:
            return ExplorationReport(
                results=[],
                best_overall=None,
                best_by_strategy={},
                data_summary={"error": "No data", "rows": 0},
            )
        registry = get_registry()
        ids = strategy_ids or list_strategies()
        horizons = horizons or [self.horizon]
        all_results: list[ExperimentResult] = []

        for sid in ids:
            strategy = registry.get(sid)
            if not strategy:
                continue
            # Sample params from ranges
            param_combos = self._sample_params(strategy, max_experiments_per_strategy)
            for params in param_combos:
                if sid == "mean_reversion" and params.get("oversold", 0) >= params.get("overbought", 0):
                    continue
                for h in horizons:
                    res = run_single(
                        rows,
                        sid,
                        params,
                        horizon=h,
                        fee_percent=self.fee_percent,
                        symbols=self.symbols,
                    )
                    if res:
                        all_results.append(res)

        return self._build_report(all_results, rows)

    def _sample_params(self, strategy, n: int) -> list[dict]:
        """Muestrea n combinaciones de params desde param_ranges."""
        import itertools
        ranges = strategy.param_ranges
        keys = list(ranges.keys())
        full = list(itertools.product(*[ranges[k] for k in keys]))
        if len(full) <= n:
            return [dict(zip(keys, c)) for c in full]
        indices = random.sample(range(len(full)), n)
        return [dict(zip(keys, full[i])) for i in indices]

    def _build_report(self, results: list[ExperimentResult], rows: list[dict]) -> ExplorationReport:
        times = sorted(set(r.get("event_time", "") for r in rows))
        symbols = sorted(set(r.get("symbol", "") for r in rows))
        best_overall = max(results, key=lambda r: r.net_return_percent) if results else None
        best_by_strategy: dict[str, ExperimentResult] = {}
        for r in results:
            if r.strategy_id not in best_by_strategy or r.net_return_percent > best_by_strategy[r.strategy_id].net_return_percent:
                best_by_strategy[r.strategy_id] = r
        return ExplorationReport(
            results=results,
            best_overall=best_overall,
            best_by_strategy=best_by_strategy,
            data_summary={
                "rows": len(rows),
                "symbols": len(symbols),
                "event_times": len(times),
                "range": f"{times[0][:10] if times else ''} ... {times[-1][:10] if times else ''}",
            },
        )
