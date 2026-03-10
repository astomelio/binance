"""
Implementaciones concretas de los agentes de la suite.
Reutilizan ExplorationAgent, backtest y lógica existente.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
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
            key=lambda r: r.fitness,
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
                    "max_drawdown_percent": r.max_drawdown_percent,
                    "sharpe_ratio": r.sharpe_ratio,
                    "fitness": r.fitness,
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
                    "max_drawdown_percent": r.max_drawdown_percent,
                    "sharpe_ratio": r.sharpe_ratio,
                    "fitness": r.fitness,
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
                    "max_drawdown_percent": res.max_drawdown_percent,
                    "sharpe_ratio": res.sharpe_ratio,
                    "win_rate_percent": res.win_rate_percent,
                    "periods": res.periods,
                    "equity_curve": getattr(res, "equity_curve", []),
                }
            else:
                # Champion puede ser modelo MLflow; aquí fallback: backtest con estrategia por defecto
                res = run_allocation_backtest(data, horizon=self.horizon, fee_percent=self.fee_percent)
                champion_backtest = {
                    "net_return_percent": res.net_return_percent,
                    "trades_count": res.trades_count,
                    "total_fees_percent": res.total_fees_percent,
                    "max_drawdown_percent": res.max_drawdown_percent,
                    "sharpe_ratio": res.sharpe_ratio,
                    "win_rate_percent": res.win_rate_percent,
                    "periods": res.periods,
                    "equity_curve": getattr(res, "equity_curve", []),
                }
        else:
            # Sin champion: un backtest genérico para tener números
            res = run_allocation_backtest(data, horizon=self.horizon, fee_percent=self.fee_percent)
            champion_backtest = {
                "net_return_percent": res.net_return_percent,
                "trades_count": res.trades_count,
                "total_fees_percent": res.total_fees_percent,
                "max_drawdown_percent": res.max_drawdown_percent,
                "sharpe_ratio": res.sharpe_ratio,
                "win_rate_percent": res.win_rate_percent,
                "periods": res.periods,
                "equity_curve": getattr(res, "equity_curve", []),
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
                        "max_drawdown_percent": single.max_drawdown_percent,
                        "sharpe_ratio": single.sharpe_ratio,
                        "win_rate_percent": single.win_rate_percent,
                        "periods": single.periods,
                        "fitness": single.fitness,
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
    """ReportAgent: construye SuiteReport con recomendación, comparación de modelos y champion timeline."""

    def __init__(
        self,
        promote_min_net_return: float = 0.5,
        promote_min_trades: int = 5,
        report_dir: str | None = None,
    ):
        self.promote_min_net_return = promote_min_net_return
        self.promote_min_trades = promote_min_trades
        self.report_dir = report_dir

    def run(
        self,
        tuning_candidates: list[Candidate],
        decision_result: DecisionResult,
        state: SuiteState,
    ) -> SuiteReport:
        rec = "no_promote"
        reason = "No candidates or no improvement."
        
        # --- NUEVO: Comparación con Realidad (Paper/Testnet) ---
        real_pnl = 0.0
        real_trades = 0
        real_win_rate = 0.0
        try:
            from pathlib import Path
            import duckdb
            db_path = os.environ.get("DBT_DUCKDB_PATH", "artifacts/warehouse/crypto.duckdb")
            if Path(db_path).exists():
                conn = duckdb.connect(db_path, read_only=True)
                # Obtenemos pnl realizado del champion actual (o de todos si no hay champion_id)
                model_filter = f"WHERE model_id LIKE '%{state.champion_id}%'" if state.champion_id else ""
                row = conn.execute(f"SELECT COUNT(*), COALESCE(SUM(realized_pnl), 0), SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) FROM fct_order_history {model_filter}").fetchone()
                if row and row[0] > 0:
                    real_trades = row[0]
                    real_pnl = float(row[1])
                    real_win_rate = (row[2] / row[0]) * 100.0
                conn.close()
        except Exception as e:
            # Silencioso si falla, no queremos romper el reporte
            pass

        # Obtenemos métricas del champion actual (si existe)
        champion_metrics = decision_result.champion_backtest or {}
        champion_net = champion_metrics.get("net_return_percent")
        champion_mdd = champion_metrics.get("max_drawdown_percent", 99.0)
        champion_sharpe = champion_metrics.get("sharpe_ratio", 0.0)
        
        # Fitness del champion: Sharpe - penalización por DD
        champion_fitness = champion_sharpe - 0.2 * champion_mdd if champion_net is not None else -999.0

        # --- NUEVO: Penalización por Discrepancia con Realidad ---
        # Si el champion tiene trades reales y el PnL es negativo mientras el backtest es muy positivo,
        # bajamos artificialmente su fitness para que sea más fácil que un challenger lo supere.
        if real_trades > 5 and real_pnl < 0 and champion_net and champion_net > 0:
            discrepancy_penalty = abs(real_pnl) / 100.0 # Ajuste heurístico
            champion_fitness -= discrepancy_penalty
            reason = f"Champion penalized for poor real performance (PnL: {real_pnl:.2f}, Backtest: {champion_net:.2f}%)"

        best_candidate_id = ""
        best_candidate_config: dict[str, Any] = {}
        best_candidate_metrics = {}

        if tuning_candidates:
            # Seleccionamos al mejor candidato basándonos en FITNESS (riesgo/retorno)
            best = max(
                tuning_candidates,
                key=lambda c: c.metrics.get("fitness", -999) or -999,
            )
            cand_net = best.metrics.get("net_return_percent")
            cand_mdd = best.metrics.get("max_drawdown_percent", 99.0)
            cand_fitness = best.metrics.get("fitness", -999.0)
            cand_trades = best.metrics.get("trades_count", 0)
            
            best_candidate_id = best.id
            best_candidate_config = dict(best.config)
            best_candidate_metrics = best.metrics

            if cand_net is not None and cand_trades >= self.promote_min_trades:
                # Criterios de promoción: 
                # 1. Retorno mínimo
                # 2. Drawdown no excesivo (ej. < 20%)
                # 3. Fitness mejor que el champion actual
                if cand_net >= self.promote_min_net_return:
                    if cand_mdd > 20.0:
                        reason = f"Candidate {best.id} has excessive drawdown ({cand_mdd:.2f}%)"
                    elif champion_net is None or cand_fitness > champion_fitness:
                        rec = "promote"
                        reason = f"Candidate {best.id} fitness={cand_fitness:.2f} > champion={champion_fitness:.2f} (MDD: {cand_mdd:.2f}%)"
                    else:
                        reason = f"Candidate fitness {cand_fitness:.2f} <= champion {champion_fitness:.2f}"
                else:
                    reason = f"Candidate net {cand_net:.2f}% < min {self.promote_min_net_return}%"
            else:
                reason = f"Candidate trades {cand_trades} < min {self.promote_min_trades} or no net_return"

        # Comparación de modelos y champion timeline
        from ai.allocation.backtest_report import (
            build_champion_timeline,
            build_model_comparison,
            ChampionSnapshot,
            write_backtest_report,
        )

        comparison_inputs = []
        if state.champion_id and decision_result.champion_backtest:
            cb = decision_result.champion_backtest
            cb["fitness"] = cb.get("sharpe_ratio", 0) - 0.2 * cb.get("max_drawdown_percent", 0)
            comparison_inputs.append((state.champion_id, cb))
        for c in decision_result.candidates_backtest:
            cid = c.get("candidate_id", "unknown")
            comparison_inputs.append((cid, c))
        model_comparison = build_model_comparison(
            comparison_inputs,
            style_map={"alpha_score": "alpha_score", "mean_reversion": "mean_reversion", "heuristic": "heuristic"},
        )

        champion_snapshot = None
        if state.champion_id and decision_result.champion_backtest:
            cb = decision_result.champion_backtest
            champion_snapshot = ChampionSnapshot(
                champion_id=state.champion_id,
                version=state.version,
                timestamp=datetime.now(timezone.utc).isoformat(),
                net_return_percent=cb.get("net_return_percent", 0),
                max_drawdown_percent=cb.get("max_drawdown_percent", 0),
                sharpe_ratio=cb.get("sharpe_ratio", 0),
                win_rate_percent=cb.get("win_rate_percent", 0),
                trades_count=cb.get("trades_count", 0),
                periods=cb.get("periods", 0),
                equity_curve=cb.get("equity_curve", [])[:500],
                config=state.champion_config,
            )
        champion_timeline = {}
        timeline_path = Path(self.report_dir or "artifacts/quant_model") / "champion_timeline.json"
        try:
            snapshots = []
            if timeline_path.exists():
                data = json.loads(timeline_path.read_text(encoding="utf-8"))
                for s in data.get("snapshots", []):
                    if isinstance(s, dict):
                        snapshots.append(ChampionSnapshot(
                            champion_id=s.get("champion_id", ""),
                            version=s.get("version", 0),
                            timestamp=s.get("timestamp", ""),
                            net_return_percent=s.get("net_return_percent", 0),
                            max_drawdown_percent=s.get("max_drawdown_percent", 0),
                            sharpe_ratio=s.get("sharpe_ratio", 0),
                            win_rate_percent=s.get("win_rate_percent", 0),
                            trades_count=s.get("trades_count", 0),
                            periods=s.get("periods", 0),
                ))
            if champion_snapshot:
                snapshots.append(champion_snapshot)
                timeline_path.parent.mkdir(parents=True, exist_ok=True)
                timeline_path.write_text(
                    json.dumps({
                        "snapshots": [
                            {
                                "champion_id": s.champion_id,
                                "version": s.version,
                                "timestamp": s.timestamp,
                                "net_return_percent": s.net_return_percent,
                                "max_drawdown_percent": s.max_drawdown_percent,
                                "sharpe_ratio": s.sharpe_ratio,
                                "win_rate_percent": s.win_rate_percent,
                                "trades_count": s.trades_count,
                                "periods": s.periods,
                            }
                            for s in snapshots[-20:]
                        ],
                    }, indent=2),
                    encoding="utf-8",
                )
            champion_timeline = build_champion_timeline(snapshots[-10:])
        except Exception:
            pass

        if self.report_dir:
            try:
                write_backtest_report(
                    Path(self.report_dir) / "backtest_report.json",
                    champion_timeline=champion_timeline,
                    model_comparison=model_comparison,
                    key_stats={
                        "champion_net_return": champion_net,
                        "champion_mdd": champion_mdd,
                        "best_candidate_net_return": best_candidate_metrics.get("net_return_percent"),
                    },
                )
            except Exception:
                pass

        return SuiteReport(
            tuning_summary={
                "num_candidates": len(tuning_candidates),
                "best_candidate_net_return": best_candidate_metrics.get("net_return_percent"),
                "best_candidate_mdd": best_candidate_metrics.get("max_drawdown_percent"),
            },
            decision_summary={
                "champion_backtest": decision_result.champion_backtest,
                "candidates_backtest": decision_result.candidates_backtest,
                "model_comparison": model_comparison,
                "champion_timeline": champion_timeline,
                "real_performance": {
                    "pnl_usdt": real_pnl,
                    "trades": real_trades,
                    "win_rate_pct": real_win_rate,
                }
            },
            recommendation=rec,
            recommendation_reason=reason,
            metrics={
                "champion_net_return": champion_net,
                "champion_mdd": champion_mdd,
                "best_candidate_net_return": best_candidate_metrics.get("net_return_percent"),
                "best_candidate_mdd": best_candidate_metrics.get("max_drawdown_percent"),
                "best_candidate_fitness": best_candidate_metrics.get("fitness"),
                "model_comparison": model_comparison,
                "champion_timeline": champion_timeline,
                "real_pnl": real_pnl,
                "real_trades": real_trades,
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
