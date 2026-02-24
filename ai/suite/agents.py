"""
Implementaciones concretas de los agentes de la suite.
Reutilizan ExplorationAgent, backtest y lógica existente.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ai.suite.types import (
    Candidate,
    DecisionResult,
    SuiteReport,
    SuiteState,
)


class ExplorationTuningAgent:
    """
    TuningAgent que usa ExplorationAgent: explora estrategias/params y devuelve candidatos.
    """

    def __init__(
        self,
        horizon: str = "4h",
        fee_percent: float = 0.04,
        strategy_ids: list[str] | None = None,
        db_path: str | None = None,
        max_candidates: int = 10,
    ):
        self.horizon = horizon
        self.fee_percent = fee_percent
        self.strategy_ids = strategy_ids
        self.db_path = db_path
        self.max_candidates = max_candidates

    def run(self, state: SuiteState, data: list[dict]) -> list[Candidate]:
        from ai.explorer.experiment import run_all_strategies
        from ai.explorer.types import ExperimentResult

        if not data:
            return []
        results: list[ExperimentResult] = run_all_strategies(
            data,
            strategy_ids=self.strategy_ids,
            horizon=self.horizon,
            fee_percent=self.fee_percent,
        )
        if not results:
            return []
        sorted_results = sorted(
            results,
            key=lambda r: r.net_return_percent,
            reverse=True,
        )[: self.max_candidates]
        return [
            Candidate(
                id=r.strategy_id,
                config={"params": r.params, "horizon": r.horizon},
                metrics={
                    "net_return_percent": r.net_return_percent,
                    "trades_count": r.trades_count,
                    "total_return_percent": r.total_return_percent,
                    "fees_percent": r.fees_percent,
                },
            )
            for r in sorted_results
        ]


class OptimizerTuningAgent:
    """
    TuningAgent que optimiza: explora estrategias × params × horizontes × activos × sesión.
    Usa run_optimization para probar mean reversion, alpha_score, heuristic con distintas
    horas de entrada, conjuntos de activos (top20, top50, all) y parámetros de entrada/salida.
    """

    def __init__(
        self,
        strategy_ids: list[str] | None = None,
        horizons: list[str] | None = None,
        symbol_sets: list[str] | None = None,
        session_hours: tuple[int, int] | None = None,
        max_combos_per_strategy: int = 40,
        max_total_trials: int = 400,
        max_candidates: int = 15,
        fee_percent: float = 0.04,
    ):
        self.strategy_ids = strategy_ids
        self.horizons = horizons or ["1h", "4h"]
        self.symbol_sets = symbol_sets or ["top20", "top50", "all"]
        self.session_hours = session_hours
        self.max_combos_per_strategy = max_combos_per_strategy
        self.max_total_trials = max_total_trials
        self.max_candidates = max_candidates
        self.fee_percent = fee_percent

    def run(self, state: SuiteState, data: list[dict]) -> list[Candidate]:
        from ai.explorer.optimizer import run_optimization
        from ai.explorer.types import ExperimentResult

        if not data:
            return []
        results: list[ExperimentResult] = run_optimization(
            data,
            strategy_ids=self.strategy_ids,
            horizons=self.horizons,
            symbol_sets=self.symbol_sets,
            session_hours=self.session_hours,
            max_combos_per_strategy=self.max_combos_per_strategy,
            max_total_trials=self.max_total_trials,
            fee_percent=self.fee_percent,
        )
        if not results:
            return []
        top = results[: self.max_candidates]
        return [
            Candidate(
                id=r.strategy_id,
                config={
                    "params": r.params,
                    "horizon": r.horizon,
                    "symbol_set": r.meta.get("symbol_set", "all"),
                },
                metrics={
                    "net_return_percent": r.net_return_percent,
                    "trades_count": r.trades_count,
                    "total_return_percent": r.total_return_percent,
                    "fees_percent": r.fees_percent,
                },
            )
            for r in top
        ]


class BacktestDecisionAgent:
    """
    DecisionAgent: evalúa champion (estrategia/config) sobre data y opcionalmente candidatos.
    """

    def __init__(
        self,
        horizon: str = "4h",
        fee_percent: float = 0.04,
        db_path: str | None = None,
    ):
        self.horizon = horizon
        self.fee_percent = fee_percent
        self.db_path = db_path

    def run(
        self,
        state: SuiteState,
        data: list[dict],
        candidates: list[Candidate] | None = None,
    ) -> DecisionResult:
        from ai.allocation.backtest import run_allocation_backtest
        from ai.explorer.experiment import run_single
        from ai.explorer.registry import get_registry

        if not data:
            return DecisionResult(
                data_summary={"error": "no_data", "rows": 0},
            )

        champion_backtest: dict[str, Any] = {}
        if state.champion_id:
            from ai.explorer.data_filters import get_symbol_set
            reg = get_registry()
            strat = reg.get(state.champion_id) if reg else None
            if strat:
                params = state.champion_config.get("params", state.champion_config)
                champion_horizon = state.champion_config.get("horizon", self.horizon)
                champion_symbols = get_symbol_set(data, state.champion_config.get("symbol_set", "all"))
                compute_fn = strat.build_compute_fn(data, params)
                res = run_allocation_backtest(
                    data,
                    horizon=champion_horizon,
                    fee_percent=self.fee_percent,
                    compute_fn=compute_fn,
                    symbols=champion_symbols,
                )
                champion_backtest = {
                    "net_return_percent": res.net_return_percent,
                    "trades_count": res.trades_count,
                    "total_fees_percent": res.total_fees_percent,
                }
            else:
                # Champion puede ser modelo MLflow; aquí fallback: backtest con estrategia por defecto
                res = run_allocation_backtest(data, horizon=self.horizon, fee_percent=self.fee_percent)
                champion_backtest = {
                    "net_return_percent": res.net_return_percent,
                    "trades_count": res.trades_count,
                    "total_fees_percent": res.total_fees_percent,
                }
        else:
            # Sin champion: un backtest genérico para tener números
            res = run_allocation_backtest(data, horizon=self.horizon, fee_percent=self.fee_percent)
            champion_backtest = {
                "net_return_percent": res.net_return_percent,
                "trades_count": res.trades_count,
                "total_fees_percent": res.total_fees_percent,
            }

        candidates_backtest: list[dict[str, Any]] = []
        if candidates:
            from ai.explorer.data_filters import get_symbol_set
            reg = get_registry()
            for c in candidates[:5]:  # límite para no disparar muchos backtests
                strat = reg.get(c.id) if reg else None
                if not strat:
                    continue
                params = c.config.get("params", c.config)
                sym_set = c.config.get("symbol_set", "all")
                symbols = get_symbol_set(data, sym_set)
                cand_horizon = c.config.get("horizon", self.horizon)
                single = run_single(
                    data,
                    c.id,
                    params,
                    horizon=cand_horizon,
                    fee_percent=self.fee_percent,
                    symbols=symbols,
                )
                if single:
                    candidates_backtest.append({
                        "candidate_id": c.id,
                        "net_return_percent": single.net_return_percent,
                        "trades_count": single.trades_count,
                    })

        times = sorted(set(r.get("event_time", "") for r in data if r.get("event_time")))
        return DecisionResult(
            champion_backtest=champion_backtest,
            candidates_backtest=candidates_backtest,
            data_summary={
                "rows": len(data),
                "range": f"{times[0][:10] if times else ''} .. {times[-1][:10] if times else ''}",
            },
        )


class DefaultReportAgent:
    """ReportAgent: construye SuiteReport con recomendación simple."""

    def __init__(
        self,
        promote_min_net_return: float = 0.5,
        promote_min_trades: int = 5,
    ):
        self.promote_min_net_return = promote_min_net_return
        self.promote_min_trades = promote_min_trades

    def run(
        self,
        tuning_candidates: list[Candidate],
        decision_result: DecisionResult,
        state: SuiteState,
    ) -> SuiteReport:
        rec = "no_promote"
        reason = "No candidates or no improvement."
        best_candidate_net = None
        champion_net = (decision_result.champion_backtest or {}).get("net_return_percent")
        champion_trades = (decision_result.champion_backtest or {}).get("trades_count", 0)

        best_candidate_id = ""
        best_candidate_config: dict[str, Any] = {}
        if tuning_candidates:
            best = max(
                tuning_candidates,
                key=lambda c: c.metrics.get("net_return_percent", -999) or -999,
            )
            best_candidate_net = best.metrics.get("net_return_percent")
            best_trades = best.metrics.get("trades_count", 0)
            best_candidate_id = best.id
            best_candidate_config = dict(best.config)
            if best_candidate_net is not None and best_trades >= self.promote_min_trades:
                if best_candidate_net >= self.promote_min_net_return:
                    if champion_net is None or best_candidate_net > champion_net:
                        rec = "promote"
                        reason = f"Candidate {best.id} net_return={best_candidate_net:.2f}% > champion {champion_net}"
                    else:
                        reason = f"Candidate net {best_candidate_net:.2f}% <= champion {champion_net}"
                else:
                    reason = f"Candidate net {best_candidate_net:.2f}% < min {self.promote_min_net_return}%"
            else:
                reason = f"Candidate trades {best_trades} < min {self.promote_min_trades} or no net_return"

        return SuiteReport(
            tuning_summary={
                "num_candidates": len(tuning_candidates),
                "best_candidate_net_return": best_candidate_net,
            },
            decision_summary={
                "champion_backtest": decision_result.champion_backtest,
                "candidates_backtest": decision_result.candidates_backtest,
            },
            recommendation=rec,
            recommendation_reason=reason,
            metrics={
                "champion_net_return": champion_net,
                "champion_trades": champion_trades,
                "best_candidate_net_return": best_candidate_net,
            },
            generated_at=datetime.now(timezone.utc).isoformat(),
            best_candidate_id=best_candidate_id,
            best_candidate_config=best_candidate_config,
        )


class DefaultEvolutionAgent:
    """EvolutionAgent: promueve candidato a champion si el report lo recomienda."""

    def run(self, report: SuiteReport, state: SuiteState) -> SuiteState:
        if report.recommendation != "promote":
            return state
        best_id = report.best_candidate_id or "best_from_tuning"
        best_config = dict(report.best_candidate_config)
        best_net = report.metrics.get("best_candidate_net_return")
        if not best_id and report.tuning_summary.get("num_candidates", 0) > 0:
            best_id = "best_from_tuning"
            best_net = report.metrics.get("best_candidate_net_return")
        if best_id:
            return SuiteState(
                champion_id=best_id,
                champion_config=best_config,
                champion_metrics={"net_return_percent": best_net, **report.metrics},
                last_evolution_at=report.generated_at,
                version=state.version + 1,
            )
        return state
