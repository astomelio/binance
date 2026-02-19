from __future__ import annotations

from dagster import ScheduleDefinition

from .jobs import crypto_lake_full_job, crypto_lake_high_job, crypto_lake_low_job, crypto_lake_medium_job


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

