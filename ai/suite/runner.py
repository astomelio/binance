"""
Orquestador de la suite de agentes: un ciclo Tuning → Decision → Report → Evolution.
Persiste estado entre ciclos para evolucionar el algoritmo en el tiempo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ai.suite.types import (
    DecisionResult,
    ResearchState,
    SuiteReport,
    SuiteState,
    TuningAgentProtocol,
    DecisionAgentProtocol,
    ReportAgentProtocol,
    EvolutionAgentProtocol,
)


DEFAULT_STATE_PATH = "artifacts/quant_model/suite_state.json"
DEFAULT_RESEARCH_STATE_PATH = "artifacts/quant_model/research_state.json"


def load_state(path: str | Path | None = None) -> SuiteState:
    path = Path(path or DEFAULT_STATE_PATH)
    if not path.exists():
        return SuiteState()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SuiteState(
        champion_id=raw.get("champion_id", ""),
        champion_config=raw.get("champion_config", {}),
        champion_metrics=raw.get("champion_metrics", {}),
        last_evolution_at=raw.get("last_evolution_at", ""),
        version=int(raw.get("version", 0)),
    )


def save_state(state: SuiteState, path: str | Path | None = None) -> None:
    path = Path(path or DEFAULT_STATE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "champion_id": state.champion_id,
                "champion_config": state.champion_config,
                "champion_metrics": state.champion_metrics,
                "last_evolution_at": state.last_evolution_at,
                "version": state.version,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def load_research_state(path: str | Path | None = None) -> ResearchState:
    path = Path(path or DEFAULT_RESEARCH_STATE_PATH)
    if not path.exists():
        return ResearchState()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ResearchState(
        cycles_without_improvement=int(raw.get("cycles_without_improvement", 0)),
        mode=raw.get("mode", "normal"),
        exploration_round=int(raw.get("exploration_round", 0)),
        last_best_net_return=raw.get("last_best_net_return"),
    )


def save_research_state(state: ResearchState, path: str | Path | None = None) -> None:
    path = Path(path or DEFAULT_RESEARCH_STATE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "cycles_without_improvement": state.cycles_without_improvement,
                "mode": state.mode,
                "exploration_round": state.exploration_round,
                "last_best_net_return": state.last_best_net_return,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def run_cycle(
    tuning_agent: TuningAgentProtocol,
    decision_agent: DecisionAgentProtocol,
    report_agent: ReportAgentProtocol,
    evolution_agent: EvolutionAgentProtocol,
    data: list[dict],
    state: SuiteState | None = None,
    state_path: str | Path | None = None,
    *,
    save_report_path: str | Path | None = None,
) -> tuple[SuiteState, SuiteReport, DecisionResult]:
    """
    Ejecuta un ciclo: Tuning → Decision → Report → Evolution.
    - state: estado actual (si None, se carga desde state_path).
    - state_path: donde persistir el nuevo estado (si None, no se guarda).
    - save_report_path: si se indica, se escribe el informe en JSON ahí.
    Devuelve (nuevo_estado, informe, resultado_decision).
    """
    state = state or load_state(state_path)
    # 1) Tuning
    candidates = tuning_agent.run(state, data)
    # 2) Decision
    decision_result = decision_agent.run(state, data, candidates)
    # 3) Report
    report = report_agent.run(candidates, decision_result, state)
    # 4) Evolution
    new_state = evolution_agent.run(report, state)

    if state_path is not None:
        save_state(new_state, state_path)

    if save_report_path:
        p = Path(save_report_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            _report_to_json(report),
            encoding="utf-8",
        )

    return new_state, report, decision_result


def _report_to_json(report: SuiteReport) -> str:
    return json.dumps(
        {
            "recommendation": report.recommendation,
            "recommendation_reason": report.recommendation_reason,
            "tuning_summary": report.tuning_summary,
            "decision_summary": report.decision_summary,
            "metrics": report.metrics,
            "best_candidate_id": report.best_candidate_id,
            "generated_at": report.generated_at,
        },
        indent=2,
    )


def run_research_loop(
    suite: "QuantAgentSuite",
    data: list[dict],
    *,
    max_cycles: int | None = 50,
    cycles_before_explore: int = 3,
    stop_on_promote: bool = False,
    on_explore: None | Callable[[Any, SuiteState, SuiteReport, ResearchState], None] = None,
    state_path: str | Path | None = None,
    research_state_path: str | Path | None = None,
) -> tuple[SuiteState, SuiteReport, ResearchState, int]:
    """
    Ejecuta ciclos de la suite hasta que pase una de:
    - Encontramos algo bueno (recommendation == "promote") y opcionalmente paramos (stop_on_promote).
    - No hay mejora durante `cycles_before_explore` ciclos: se llama a `on_explore(suite, state, report, research_state)`
      para ampliar la búsqueda (más trials, otras estrategias, etc.) y se sigue.
    - Se alcanza `max_cycles`.

    `on_explore` puede reemplazar `suite.tuning_agent` por un agente más agresivo (más trials, otros symbol_sets, etc.).

    Devuelve (último SuiteState, último SuiteReport, ResearchState actualizado, número de ciclos ejecutados).
    """
    state_path = Path(state_path or suite.state_path)
    research_state_path = Path(research_state_path or DEFAULT_RESEARCH_STATE_PATH)
    research_state = load_research_state(research_state_path)
    state = load_state(state_path)
    cycle = 0

    last_report: SuiteReport | None = None
    while True:
        if max_cycles is not None and cycle >= max_cycles:
            break
        state, report, _ = suite.run_cycle(
            data,
            state=state,
            persist_state=True,
            save_report=True,
        )
        last_report = report
        cycle += 1

        if report.recommendation == "promote":
            research_state = ResearchState(
                cycles_without_improvement=0,
                mode="normal",
                exploration_round=research_state.exploration_round,
                last_best_net_return=report.metrics.get("best_candidate_net_return"),
            )
            save_research_state(research_state, research_state_path)
            if stop_on_promote:
                return state, report, research_state, cycle
            continue

        best_net = report.metrics.get("best_candidate_net_return")
        research_state = ResearchState(
            cycles_without_improvement=research_state.cycles_without_improvement + 1,
            mode=research_state.mode,
            exploration_round=research_state.exploration_round,
            last_best_net_return=best_net if best_net is not None else research_state.last_best_net_return,
        )

        if research_state.cycles_without_improvement >= cycles_before_explore and on_explore:
            on_explore(suite, state, report, research_state)
            research_state = ResearchState(
                cycles_without_improvement=0,
                mode="exploration",
                exploration_round=research_state.exploration_round + 1,
                last_best_net_return=research_state.last_best_net_return,
            )

        save_research_state(research_state, research_state_path)

    return state, last_report or report, research_state, cycle


class QuantAgentSuite:
    """
    Suite configurada: agentes inyectados y paths por defecto.
    Uso: suite = QuantAgentSuite(...); suite.run_cycle(data)
    """

    def __init__(
        self,
        tuning_agent: TuningAgentProtocol,
        decision_agent: DecisionAgentProtocol,
        report_agent: ReportAgentProtocol,
        evolution_agent: EvolutionAgentProtocol,
        state_path: str | Path | None = None,
        report_dir: str | Path | None = None,
    ):
        self.tuning_agent = tuning_agent
        self.decision_agent = decision_agent
        self.report_agent = report_agent
        self.evolution_agent = evolution_agent
        self.state_path = state_path or DEFAULT_STATE_PATH
        self.report_dir = report_dir or Path("artifacts/quant_model")

    def run_cycle(
        self,
        data: list[dict],
        state: SuiteState | None = None,
        persist_state: bool = True,
        save_report: bool = True,
    ) -> tuple[SuiteState, SuiteReport, DecisionResult]:
        from datetime import datetime, timezone
        state_path = self.state_path if persist_state else None
        report_path = None
        if save_report and self.report_dir:
            report_path = Path(self.report_dir) / f"suite_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.json"
        return run_cycle(
            self.tuning_agent,
            self.decision_agent,
            self.report_agent,
            self.evolution_agent,
            data,
            state=state,
            state_path=state_path,
            save_report_path=str(report_path) if report_path else None,
        )
