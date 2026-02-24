"""
Evolutionary strategy search.

Implements a population-based search that discovers trading strategies by:
1. Random initialization (generation 0)
2. Tournament selection of the fittest
3. Mutation and crossover to create offspring
4. Elitism to preserve top performers

The search can run as a one-shot batch or continuously refine across cycles.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any

from ai.agents.evaluator import EvalResult, evaluate_genome
from ai.agents.genome import StrategyGenome, crossover, mutate, random_genome

logger = logging.getLogger(__name__)


@dataclass
class SearchConfig:
    """Configuration for evolutionary search."""

    population_size: int = 40
    elite_count: int = 4
    mutation_rate: float = 0.60
    crossover_rate: float = 0.30
    random_rate: float = 0.10
    mutation_strength: float = 0.25
    tournament_size: int = 4
    max_generations: int = 20
    min_fitness_improvement: float = 0.01
    stale_generations_limit: int = 5

    # Walk-forward params
    train_days: int = 30
    test_days: int = 7
    step_days: int = 7
    embargo_hours: int = 12
    fee_percent: float = 0.04
    slippage_percent: float = 0.02


@dataclass
class GenerationResult:
    generation: int
    evaluated: int
    best_fitness: float
    best_genome_id: str
    mean_fitness: float
    diversity: float  # unique genome count / population


@dataclass
class SearchResult:
    """Full result of an evolutionary search run."""

    generations: list[GenerationResult]
    population: list[tuple[StrategyGenome, EvalResult]]
    best_genome: StrategyGenome
    best_eval: EvalResult
    total_evaluations: int

    def top_n(self, n: int = 5) -> list[tuple[StrategyGenome, EvalResult]]:
        return sorted(self.population, key=lambda x: x[1].fitness, reverse=True)[:n]


def _tournament_select(
    pop: list[tuple[StrategyGenome, EvalResult]],
    k: int = 4,
) -> StrategyGenome:
    """Select the best genome from a random tournament of size k."""
    contestants = random.sample(pop, min(k, len(pop)))
    winner = max(contestants, key=lambda x: x[1].fitness)
    return winner[0]


def _compute_diversity(pop: list[tuple[StrategyGenome, EvalResult]]) -> float:
    unique_ids = set(g.genome_id for g, _ in pop)
    return len(unique_ids) / max(len(pop), 1)


def run_search(
    rows: list[dict],
    config: SearchConfig | None = None,
    seed_genomes: list[StrategyGenome] | None = None,
    on_generation: Any = None,
) -> SearchResult:
    """
    Run evolutionary search over strategy genomes.

    Args:
        rows: decision_features data (list of dicts)
        config: search hyperparameters
        seed_genomes: optional starting population (e.g. from previous search)
        on_generation: optional callback(GenerationResult, population) for live monitoring

    Returns:
        SearchResult with final population ranked by fitness
    """
    cfg = config or SearchConfig()

    # Initialize population
    population: list[tuple[StrategyGenome, EvalResult]] = []

    if seed_genomes:
        for g in seed_genomes[:cfg.population_size]:
            result = evaluate_genome(
                g, rows,
                train_days=cfg.train_days,
                test_days=cfg.test_days,
                step_days=cfg.step_days,
                embargo_hours=cfg.embargo_hours,
                fee_percent=cfg.fee_percent,
                slippage_percent=cfg.slippage_percent,
            )
            if result:
                population.append((g, result))

    remaining = cfg.population_size - len(population)
    for _ in range(remaining):
        g = random_genome(generation=0)
        result = evaluate_genome(
            g, rows,
            train_days=cfg.train_days,
            test_days=cfg.test_days,
            step_days=cfg.step_days,
            embargo_hours=cfg.embargo_hours,
            fee_percent=cfg.fee_percent,
            slippage_percent=cfg.slippage_percent,
        )
        if result:
            population.append((g, result))

    if not population:
        raise ValueError("No genomes could be evaluated - check data")

    total_evals = len(population)
    generation_results: list[GenerationResult] = []
    best_fitness_ever = max(e.fitness for _, e in population)
    stale_count = 0

    for gen in range(1, cfg.max_generations + 1):
        population.sort(key=lambda x: x[1].fitness, reverse=True)

        # Elitism: keep top performers
        next_gen: list[tuple[StrategyGenome, EvalResult]] = []
        next_gen.extend(population[:cfg.elite_count])

        target_size = cfg.population_size - cfg.elite_count
        n_mutations = int(target_size * cfg.mutation_rate)
        n_crossovers = int(target_size * cfg.crossover_rate)
        n_random = target_size - n_mutations - n_crossovers

        # Mutations from tournament winners
        for _ in range(n_mutations):
            parent = _tournament_select(population, cfg.tournament_size)
            child = mutate(parent, strength=cfg.mutation_strength)
            child.generation = gen
            result = evaluate_genome(
                child, rows,
                train_days=cfg.train_days,
                test_days=cfg.test_days,
                step_days=cfg.step_days,
                embargo_hours=cfg.embargo_hours,
                fee_percent=cfg.fee_percent,
                slippage_percent=cfg.slippage_percent,
            )
            if result:
                next_gen.append((child, result))
                total_evals += 1

        # Crossovers
        for _ in range(n_crossovers):
            p1 = _tournament_select(population, cfg.tournament_size)
            p2 = _tournament_select(population, cfg.tournament_size)
            child = crossover(p1, p2)
            child.generation = gen
            result = evaluate_genome(
                child, rows,
                train_days=cfg.train_days,
                test_days=cfg.test_days,
                step_days=cfg.step_days,
                embargo_hours=cfg.embargo_hours,
                fee_percent=cfg.fee_percent,
                slippage_percent=cfg.slippage_percent,
            )
            if result:
                next_gen.append((child, result))
                total_evals += 1

        # Fresh random genomes for diversity
        for _ in range(n_random):
            g = random_genome(generation=gen)
            result = evaluate_genome(
                g, rows,
                train_days=cfg.train_days,
                test_days=cfg.test_days,
                step_days=cfg.step_days,
                embargo_hours=cfg.embargo_hours,
                fee_percent=cfg.fee_percent,
                slippage_percent=cfg.slippage_percent,
            )
            if result:
                next_gen.append((g, result))
                total_evals += 1

        population = next_gen
        population.sort(key=lambda x: x[1].fitness, reverse=True)

        gen_best = population[0][1].fitness if population else 0
        gen_mean = sum(e.fitness for _, e in population) / len(population) if population else 0

        gen_result = GenerationResult(
            generation=gen,
            evaluated=total_evals,
            best_fitness=gen_best,
            best_genome_id=population[0][0].genome_id if population else "",
            mean_fitness=round(gen_mean, 4),
            diversity=round(_compute_diversity(population), 2),
        )
        generation_results.append(gen_result)

        if on_generation:
            on_generation(gen_result, population)

        logger.info(
            "gen=%d best=%.4f mean=%.4f diversity=%.2f evals=%d",
            gen, gen_best, gen_mean, gen_result.diversity, total_evals,
        )

        # Early stopping
        if gen_best > best_fitness_ever + cfg.min_fitness_improvement:
            best_fitness_ever = gen_best
            stale_count = 0
        else:
            stale_count += 1

        if stale_count >= cfg.stale_generations_limit:
            logger.info("Early stopping: no improvement for %d generations", stale_count)
            break

    population.sort(key=lambda x: x[1].fitness, reverse=True)
    best_genome, best_eval = population[0]

    return SearchResult(
        generations=generation_results,
        population=population,
        best_genome=best_genome,
        best_eval=best_eval,
        total_evaluations=total_evals,
    )
