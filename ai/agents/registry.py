"""
DuckDB-backed strategy registry.

Persists every evaluated genome with its metrics so that:
1. We never re-evaluate the same genome twice
2. We can query historical performance across generations
3. We can load top performers to seed future searches
4. We can track lineage (parent genomes for mutations/crossovers)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import duckdb

from ai.agents.evaluator import EvalResult
from ai.agents.genome import StrategyGenome

_DEFAULT_DB = "artifacts/ai/strategy_registry.duckdb"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS strategy_registry (
    genome_id       VARCHAR PRIMARY KEY,
    genome_json     VARCHAR NOT NULL,
    generation      INTEGER NOT NULL DEFAULT 0,
    parent_ids      VARCHAR DEFAULT '[]',
    fitness         DOUBLE NOT NULL,
    mean_return     DOUBLE,
    std_return      DOUBLE,
    mean_sharpe     DOUBLE,
    mean_drawdown   DOUBLE,
    mean_win_rate   DOUBLE,
    total_trades    INTEGER,
    stability       DOUBLE,
    n_folds         INTEGER,
    horizon         VARCHAR,
    evaluated_at    TIMESTAMP NOT NULL,
    search_run_id   VARCHAR DEFAULT '',
    promoted        BOOLEAN DEFAULT FALSE,
    notes           VARCHAR DEFAULT ''
);
"""

_CREATE_LINEAGE = """
CREATE TABLE IF NOT EXISTS genome_lineage (
    child_id   VARCHAR NOT NULL,
    parent_id  VARCHAR NOT NULL,
    generation INTEGER NOT NULL,
    method     VARCHAR DEFAULT 'unknown',
    created_at TIMESTAMP NOT NULL
);
"""


class StrategyRegistry:
    """Persistent registry for evaluated strategy genomes."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.environ.get("STRATEGY_REGISTRY_PATH", _DEFAULT_DB)
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._conn = duckdb.connect(self.db_path)
        self._conn.execute(_CREATE_TABLE)
        self._conn.execute(_CREATE_LINEAGE)

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def save(
        self,
        genome: StrategyGenome,
        eval_result: EvalResult,
        search_run_id: str = "",
    ) -> None:
        """Persist a genome and its evaluation result."""
        now = datetime.now(timezone.utc)
        method = "crossover" if len(genome.parent_ids) > 1 else ("mutation" if genome.parent_ids else "random")

        self._conn.execute(
            """
            INSERT OR REPLACE INTO strategy_registry
            (genome_id, genome_json, generation, parent_ids, fitness,
             mean_return, std_return, mean_sharpe, mean_drawdown, mean_win_rate,
             total_trades, stability, n_folds, horizon, evaluated_at, search_run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                genome.genome_id,
                json.dumps(genome.to_dict()),
                genome.generation,
                json.dumps(genome.parent_ids),
                eval_result.fitness,
                eval_result.mean_return,
                eval_result.std_return,
                eval_result.mean_sharpe,
                eval_result.mean_drawdown,
                eval_result.mean_win_rate,
                eval_result.total_trades,
                eval_result.stability,
                len(eval_result.folds),
                genome.horizon,
                now,
                search_run_id,
            ],
        )

        for pid in genome.parent_ids:
            self._conn.execute(
                """
                INSERT INTO genome_lineage (child_id, parent_id, generation, method, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [genome.genome_id, pid, genome.generation, method, now],
            )

    def save_batch(
        self,
        population: list[tuple[StrategyGenome, EvalResult]],
        search_run_id: str = "",
    ) -> int:
        """Save an entire population. Returns count saved."""
        count = 0
        for genome, eval_result in population:
            self.save(genome, eval_result, search_run_id)
            count += 1
        return count

    def exists(self, genome_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM strategy_registry WHERE genome_id = ?", [genome_id]
        ).fetchone()
        return row is not None

    def get(self, genome_id: str) -> tuple[StrategyGenome, dict] | None:
        """Load a genome and its metrics by ID."""
        row = self._conn.execute(
            "SELECT genome_json, fitness, mean_return, mean_sharpe, mean_drawdown, stability "
            "FROM strategy_registry WHERE genome_id = ?",
            [genome_id],
        ).fetchone()
        if not row:
            return None
        genome = StrategyGenome.from_dict(json.loads(row[0]))
        metrics = {
            "fitness": row[1],
            "mean_return": row[2],
            "mean_sharpe": row[3],
            "mean_drawdown": row[4],
            "stability": row[5],
        }
        return genome, metrics

    def top_genomes(
        self,
        n: int = 10,
        min_stability: float = 0.0,
        min_trades: int = 0,
        horizon: str | None = None,
    ) -> list[tuple[StrategyGenome, dict]]:
        """Load top N genomes ranked by fitness."""
        conditions = ["1=1"]
        params: list = []
        if min_stability > 0:
            conditions.append("stability >= ?")
            params.append(min_stability)
        if min_trades > 0:
            conditions.append("total_trades >= ?")
            params.append(min_trades)
        if horizon:
            conditions.append("horizon = ?")
            params.append(horizon)

        where = " AND ".join(conditions)
        rows = self._conn.execute(
            f"""
            SELECT genome_json, fitness, mean_return, std_return, mean_sharpe,
                   mean_drawdown, mean_win_rate, total_trades, stability, n_folds
            FROM strategy_registry
            WHERE {where}
            ORDER BY fitness DESC
            LIMIT ?
            """,
            params + [n],
        ).fetchall()

        results = []
        for row in rows:
            genome = StrategyGenome.from_dict(json.loads(row[0]))
            metrics = {
                "fitness": row[1],
                "mean_return": row[2],
                "std_return": row[3],
                "mean_sharpe": row[4],
                "mean_drawdown": row[5],
                "mean_win_rate": row[6],
                "total_trades": row[7],
                "stability": row[8],
                "n_folds": row[9],
            }
            results.append((genome, metrics))
        return results

    def promote(self, genome_id: str, notes: str = "") -> None:
        """Mark a genome as promoted (candidate for live trading)."""
        self._conn.execute(
            "UPDATE strategy_registry SET promoted = TRUE, notes = ? WHERE genome_id = ?",
            [notes, genome_id],
        )

    def promoted_genomes(self) -> list[tuple[StrategyGenome, dict]]:
        """Load all promoted genomes."""
        rows = self._conn.execute(
            """
            SELECT genome_json, fitness, mean_return, mean_sharpe, mean_drawdown,
                   stability, notes
            FROM strategy_registry
            WHERE promoted = TRUE
            ORDER BY fitness DESC
            """,
        ).fetchall()
        results = []
        for row in rows:
            genome = StrategyGenome.from_dict(json.loads(row[0]))
            metrics = {
                "fitness": row[1],
                "mean_return": row[2],
                "mean_sharpe": row[3],
                "mean_drawdown": row[4],
                "stability": row[5],
                "notes": row[6],
            }
            results.append((genome, metrics))
        return results

    def stats(self) -> dict[str, Any]:
        """Summary statistics of the registry."""
        row = self._conn.execute(
            """
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN promoted THEN 1 END) as promoted,
                MAX(fitness) as best_fitness,
                AVG(fitness) as avg_fitness,
                MAX(generation) as max_generation,
                MAX(evaluated_at) as last_eval
            FROM strategy_registry
            """,
        ).fetchone()
        return {
            "total_genomes": row[0],
            "promoted": row[1],
            "best_fitness": row[2],
            "avg_fitness": row[3],
            "max_generation": row[4],
            "last_evaluation": str(row[5]) if row[5] else None,
        }

    def lineage(self, genome_id: str, max_depth: int = 5) -> list[dict]:
        """Trace lineage of a genome back through its ancestors."""
        visited = set()
        queue = [genome_id]
        edges = []
        depth = 0
        while queue and depth < max_depth:
            next_queue = []
            for gid in queue:
                if gid in visited:
                    continue
                visited.add(gid)
                rows = self._conn.execute(
                    "SELECT parent_id, method, generation FROM genome_lineage WHERE child_id = ?",
                    [gid],
                ).fetchall()
                for parent_id, method, gen in rows:
                    edges.append({
                        "child": gid,
                        "parent": parent_id,
                        "method": method,
                        "generation": gen,
                    })
                    next_queue.append(parent_id)
            queue = next_queue
            depth += 1
        return edges
