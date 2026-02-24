"""
Tipos y contratos para la suite de agentes quant.
Véase docs/SUITE_AGENTES_QUANT.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class SuiteState:
    """Estado persistido de la suite (champion, config, última evolución)."""

    champion_id: str = ""  # ej. strategy_id o "model"
    champion_config: dict[str, Any] = field(default_factory=dict)  # params o model version
    champion_metrics: dict[str, Any] = field(default_factory=dict)  # net_return, trades, etc.
    last_evolution_at: str = ""
    version: int = 0


@dataclass
class ResearchState:
    """
    Estado del bucle de investigación: cuántos ciclos sin mejora y modo actual.
    Usado para correr hasta encontrar algo bueno o detectar estancamiento y explorar.
    """

    cycles_without_improvement: int = 0
    mode: str = "normal"  # "normal" | "exploration"
    exploration_round: int = 0
    last_best_net_return: float | None = None  # para detectar meseta


@dataclass
class Candidate:
    """Un candidato propuesto por Tuning (modelo o config de estrategia)."""

    id: str  # ej. strategy_id o run_id
    config: dict[str, Any]
    metrics: dict[str, Any]  # net_return_percent, trades_count, etc.


@dataclass
class DecisionResult:
    """Resultado de evaluar champion/candidatos: backtest, comparación con paper."""

    champion_backtest: dict[str, Any] = field(default_factory=dict)  # net_return_percent, trades_count, period
    candidates_backtest: list[dict[str, Any]] = field(default_factory=list)
    backtest_vs_paper: dict[str, Any] = field(default_factory=dict)  # opcional
    data_summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class SuiteReport:
    """Informe generado por ReportAgent para humanos y Evolution."""

    tuning_summary: dict[str, Any] = field(default_factory=dict)
    decision_summary: dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""  # "promote", "no_promote", "retrain", etc.
    recommendation_reason: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""
    # Para Evolution: mejor candidato a promover (id + config)
    best_candidate_id: str = ""
    best_candidate_config: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class TuningAgentProtocol(Protocol):
    """Contrato: proponer candidatos (params/modelos)."""

    def run(self, state: SuiteState, data: list[dict]) -> list[Candidate]:
        ...


@runtime_checkable
class DecisionAgentProtocol(Protocol):
    """Contrato: evaluar champion y opcionalmente candidatos; backtest y vs paper."""

    def run(
        self,
        state: SuiteState,
        data: list[dict],
        candidates: list[Candidate] | None = None,
    ) -> DecisionResult:
        ...


@runtime_checkable
class ReportAgentProtocol(Protocol):
    """Contrato: construir informe desde tuning + decision + state."""

    def run(
        self,
        tuning_candidates: list[Candidate],
        decision_result: DecisionResult,
        state: SuiteState,
    ) -> SuiteReport:
        ...


@runtime_checkable
class EvolutionAgentProtocol(Protocol):
    """Contrato: decidir si promover challenger y devolver nuevo estado."""

    def run(self, report: SuiteReport, state: SuiteState) -> SuiteState:
        ...
