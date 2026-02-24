"""
Suite de agentes quant: tuning, decisión, informes y evolución del algoritmo.
Véase docs/SUITE_AGENTES_QUANT.md.
"""

from ai.suite.types import (
    Candidate,
    DecisionResult,
    ResearchState,
    SuiteReport,
    SuiteState,
    TuningAgentProtocol,
    DecisionAgentProtocol,
    ReportAgentProtocol,
    EvolutionAgentProtocol,
)
from ai.suite.agents import (
    ExplorationTuningAgent,
    OptimizerTuningAgent,
    BacktestDecisionAgent,
    DefaultReportAgent,
    DefaultEvolutionAgent,
)
from ai.suite.runner import (
    load_state,
    save_state,
    load_research_state,
    save_research_state,
    run_cycle,
    run_research_loop,
    QuantAgentSuite,
    DEFAULT_STATE_PATH,
    DEFAULT_RESEARCH_STATE_PATH,
)

__all__ = [
    "Candidate",
    "DecisionResult",
    "ResearchState",
    "SuiteReport",
    "SuiteState",
    "TuningAgentProtocol",
    "DecisionAgentProtocol",
    "ReportAgentProtocol",
    "EvolutionAgentProtocol",
    "ExplorationTuningAgent",
    "OptimizerTuningAgent",
    "BacktestDecisionAgent",
    "DefaultReportAgent",
    "DefaultEvolutionAgent",
    "load_state",
    "save_state",
    "load_research_state",
    "save_research_state",
    "run_cycle",
    "run_research_loop",
    "QuantAgentSuite",
    "DEFAULT_STATE_PATH",
    "DEFAULT_RESEARCH_STATE_PATH",
]
