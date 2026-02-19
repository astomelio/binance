output "service_url" {
  description = "URL of the deployed Cloud Run service"
  value       = google_cloud_run_v2_service.binance_api.uri
}

output "service_name" {
  description = "Name of the Cloud Run service"
  value       = google_cloud_run_v2_service.binance_api.name
}

output "artifact_registry" {
  description = "Artifact Registry repository URL"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker_repo.repository_id}"
}

output "secrets" {
  description = "Secret Manager secret IDs"
  value = {
    api_key    = google_secret_manager_secret.binance_api_key.secret_id
    secret_key = google_secret_manager_secret.binance_secret_key.secret_id
    testnet    = google_secret_manager_secret.binance_testnet.secret_id
  }
  sensitive = true
}

output "dagster_service_url" {
  description = "URL of Dagster Cloud Run service"
  value       = try(google_cloud_run_v2_service.dagster_orchestrator[0].uri, null)
}

output "dagster_service_name" {
  description = "Dagster Cloud Run service name"
  value       = try(google_cloud_run_v2_service.dagster_orchestrator[0].name, null)
}

output "dagster_sql_instance_connection_name" {
  description = "Cloud SQL connection name for Dagster metadata"
  value       = try(google_sql_database_instance.dagster[0].connection_name, null)
}
