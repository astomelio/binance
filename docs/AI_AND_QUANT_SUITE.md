# AI models and quant agent suite

## Two different “models”

1. **ML model (LightGBM)** – predicts up/down per bar; output is a **score** written to column `alpha_score`. Trained by `scripts/auto_train_eval.py` or `examples/quant_optuna_tuning.py`. If you never fill `alpha_score` (e.g. via `--use-champion` or `enrich_rows_with_model()`), the **alpha_score strategy does nothing** (0 trades).

2. **Strategies** (rules, not neural nets) – turn table columns into an **allocation vector** (long/short per symbol): **alpha_score** (uses `alpha_score`), **heuristic** (uses `alpha_signal`), **mean_reversion** (uses momentum). The suite **does not train** the LightGBM; it searches over strategy × params × horizon × symbol sets and promotes a **champion** config.

**No temporal leakage:** strategies get only features at time t; `fwd_return` is used only to compute PnL in the backtest, not as strategy input.

---

## Suite flow (one cycle)

```
Data → TuningAgent (candidates) → DecisionAgent (backtest) → ReportAgent (recommendation) → EvolutionAgent (update champion)
```

- **State:** `artifacts/quant_model/suite_state.json`
- **One cycle:** `python scripts/run_suite_cycle.py` or `make suite-cycle`
- **With ML model:** `python scripts/run_suite_cycle.py --use-champion` so `alpha_score` is filled before evaluation.
- **Optimize (search):** `python scripts/run_suite_cycle.py --optimize --max-trials 500` (strategies × params × horizons × symbol sets).

---

## Research loop (run until good or stuck)

`python scripts/run_suite_research.py --optimize` runs cycles until (1) a promote, or (2) no progress for N cycles → then **exploration** (more trials, other horizons/sessions). State: `artifacts/quant_model/research_state.json`.

```bash
python scripts/run_suite_research.py --optimize --max-cycles 20 --cycles-before-explore 3
```

---

## Automation

- **Data + train + champion:** `python scripts/auto_data_then_train.py --set-champion`
- **Full pipeline (data + train + suite):** `python scripts/run_prender_full.py`
- **Train only:** `python scripts/auto_train_eval.py --set-champion`
- **Dagster:** schedules (e.g. `quant_suite_daily`) run the suite when the daemon is up; see `docker-compose.server.yml`.

---

## Alpha score checks

- Low coverage warning: `warn_alpha_score_if_low(rows)` if many rows have empty `alpha_score`.
- Strict: `--strict-alpha` in `run_suite_cycle.py` fails if coverage is too low.
- Use `--use-champion` so the suite evaluates with the real ML model (MLflow `models:/quant_alpha_entry_lgbm@champion`).
