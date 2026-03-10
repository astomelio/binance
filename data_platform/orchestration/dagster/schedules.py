from __future__ import annotations

from dagster import (
    DagsterRunStatus,
    DefaultScheduleStatus,
    RunsFilter,
    ScheduleDefinition,
)

from .jobs import (
    bronze_high_job,
    bronze_low_job,
    bronze_medium_job,
    data_pipeline_job,
    execution_only_job,
    full_pipeline_job,
    ml_train_suite_job,
    quant_suite_job,
    trading_execution_job,
)


def _skip_if_run_in_progress(job_name: str):
    """No encolar si ya hay un run running o queued (evita 72 runs en cola cuando uno tarda 18h)."""

    def _fn(context):
        records = context.instance.get_run_records(
            RunsFilter(
                job_name=job_name,
                statuses=[
                    DagsterRunStatus.QUEUED,
                    DagsterRunStatus.STARTED,
                    DagsterRunStatus.STARTING,
                    DagsterRunStatus.NOT_STARTED,
                ],
            )
        )
        return len(records) == 0

    return _fn


# High-frequency bronze: every 15 minutes (spot, futures, flow, cross-exchange)
    bronze_high_schedule = ScheduleDefinition(
        name="01_datos_cripto_cada_15min",
        cron_schedule="*/15 * * * *",
        job=bronze_high_job,
        description="Binance, Bybit, OKX → market_snapshot, derivatives, cross_exchange",
        tags={"origen": "schedule", "que_hace": "trae datos cripto frescos"},
        default_status=DefaultScheduleStatus.STOPPED,
        execution_timezone="UTC",
        should_execute=_skip_if_run_in_progress("01_datos_cripto_cada_15min"),
    )

# Medium-frequency bronze: every hour (CoinGecko, Fear&Greed, DEX)
bronze_medium_schedule = ScheduleDefinition(
    name="02_datos_medio_cada_hora",
    cron_schedule="5 * * * *",
    job=bronze_medium_job,
    description="CoinGecko, Fear&Greed, DexScreener → global_market, fear_greed, dex",
    tags={"origen": "schedule", "que_hace": "trae mcap, fear&greed, DEX"},
    default_status=DefaultScheduleStatus.RUNNING,
    execution_timezone="UTC",
    should_execute=_skip_if_run_in_progress("02_datos_medio_cada_hora"),
)

# Low-frequency bronze: every 6 hours (FRED, FED calendar, on-chain)
bronze_low_schedule = ScheduleDefinition(
    name="03_datos_macro_cada_6h",
    cron_schedule="0 */6 * * *",
    job=bronze_low_job,
    description="FRED, FED, on-chain → macro_rates, fed_calendar",
    tags={"origen": "schedule", "que_hace": "trae datos macro"},
    default_status=DefaultScheduleStatus.RUNNING,
    execution_timezone="UTC",
    should_execute=_skip_if_run_in_progress("03_datos_macro_cada_6h"),
)

# Full data pipeline (bronze + warehouse + dbt): every 15 minutes (mínimo frame = 15m)
data_pipeline_hourly_schedule = ScheduleDefinition(
    name="04_pipeline_completo_cada_15m",
    cron_schedule="*/15 * * * *",
    job=data_pipeline_job,
    description="Cada 15 min: cripto + acciones + noticias + X + dbt → decision_features (frame 15m)",
    tags={"origen": "schedule", "que_hace": "carga datos frescos y construye warehouse"},
    default_status=DefaultScheduleStatus.STOPPED,
    execution_timezone="UTC",
    should_execute=_skip_if_run_in_progress("04_pipeline_completo_cada_15m"),
)

# Full pipeline + training + suite: weekly Sunday 23:00
full_pipeline_weekly_schedule = ScheduleDefinition(
    name="05_pipeline_full_semanal",
    cron_schedule="0 23 * * 0",
    job=full_pipeline_job,
    description="Domingos 23h: todo de punta a punta incluyendo entrenar modelos",
    tags={"origen": "schedule", "que_hace": "pipeline completo + ML"},
    default_status=DefaultScheduleStatus.STOPPED,
    execution_timezone="UTC",
    should_execute=_skip_if_run_in_progress("05_pipeline_full_semanal"),
)

# Train model + suite + risk + execute: every 6 hours
ml_train_suite_schedule = ScheduleDefinition(
    name="06_entrenar_modelos_cada_6h",
    cron_schedule="0 */6 * * *",
    job=ml_train_suite_job,
    description="Cada 6h: entrena modelos, suite Optuna, risk engine y ejecución (actualiza champion)",
    tags={"origen": "schedule", "que_hace": "entrena modelos nuevos"},
    default_status=DefaultScheduleStatus.STOPPED,
    execution_timezone="UTC",
    should_execute=_skip_if_run_in_progress("06_entrenar_modelos_cada_6h"),
)

    # Agent suite only (quick eval, no retrain): every 15 minutes (alineado al frame 15m)
quant_suite_schedule = ScheduleDefinition(
    name="07_optimizar_suite_cada_15m",
    cron_schedule="5,20,35,50 * * * *",
    job=quant_suite_job,
    description="Cada 15 min (offset :05): solo Optuna suite (asume datos ya cargados por 04)",
    tags={"origen": "schedule", "que_hace": "optimiza estrategias"},
    default_status=DefaultScheduleStatus.RUNNING,
    execution_timezone="UTC",
    should_execute=_skip_if_run_in_progress("07_optimizar_suite_cada_15m"),
)

# Operación Testnet al frame mínimo (15m): pipeline completo + risk + ejecución
trading_execution_schedule = ScheduleDefinition(
    name="08_operacion_testnet_cada_15m",
    cron_schedule="7,22,37,52 * * * *",
    job=trading_execution_job,
    description="Cada 15 min (:07, :22, etc): refresco datos + warehouse + dbt → risk → ejecución Testnet",
    tags={"origen": "schedule", "que_hace": "opera en la testnet al menor frame (15m)"},
    default_status=DefaultScheduleStatus.RUNNING,
    execution_timezone="UTC",
    should_execute=_skip_if_run_in_progress("08_operacion_testnet_cada_15m"),
)

# Solo risk + ejecución
execution_only_schedule = ScheduleDefinition(
    name="09_ejecutar_solo_cada_15m",
    cron_schedule="10,25,40,55 * * * *",
    job=execution_only_job,
    description="Cada 15 min (:10, :25, etc): solo risk + ejecución",
    tags={"origen": "schedule", "que_hace": "solo ejecución testnet"},
    default_status=DefaultScheduleStatus.STOPPED,
    execution_timezone="UTC",
    should_execute=_skip_if_run_in_progress("09_ejecutar_solo_cada_15m"),
)
