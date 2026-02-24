from __future__ import annotations

from dagster import ScheduleDefinition

from .jobs import (
    crypto_lake_full_job,
    crypto_lake_full_plus_train_job,
    crypto_lake_high_job,
    crypto_lake_low_job,
    crypto_lake_medium_job,
    quant_suite_job,
)


crypto_lake_high_schedule = ScheduleDefinition(
    name="crypto_lake_high_every_5_min",
    cron_schedule="*/5 * * * *",
    job=crypto_lake_high_job,
)

crypto_lake_medium_schedule = ScheduleDefinition(
    name="crypto_lake_medium_every_30_min",
    cron_schedule="*/30 * * * *",
    job=crypto_lake_medium_job,
)

crypto_lake_low_schedule = ScheduleDefinition(
    name="crypto_lake_low_every_4_hours",
    cron_schedule="0 */4 * * *",
    job=crypto_lake_low_job,
)

crypto_lake_full_schedule = ScheduleDefinition(
    name="crypto_lake_full_every_4_hours",
    cron_schedule="15 */4 * * *",
    job=crypto_lake_full_job,
)

# Más frecuente: cada hora, todas las tablas con misma temporalidad
crypto_lake_full_hourly_schedule = ScheduleDefinition(
    name="crypto_lake_full_every_hour",
    cron_schedule="30 * * * *",
    job=crypto_lake_full_job,
)

# Datos + training: cada semana (domingo 23:00), para tener modelo nuevo con datos frescos
crypto_lake_full_plus_train_weekly_schedule = ScheduleDefinition(
    name="crypto_lake_full_plus_train_weekly",
    cron_schedule="0 23 * * 0",
    job=crypto_lake_full_plus_train_job,
)

# Suite de agentes quant: cada día a las 04:00 (datos + un ciclo tuning→decisión→informe→evolución)
quant_suite_daily_schedule = ScheduleDefinition(
    name="quant_suite_daily",
    cron_schedule="0 4 * * *",
    job=quant_suite_job,
)

