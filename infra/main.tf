terraform {
  required_version = ">= 1.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  backend "gcs" {
    bucket = "binance-api-terraform-state"
    prefix = "terraform/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Enable required APIs
resource "google_project_service" "required_apis" {
  for_each = toset([
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "sqladmin.googleapis.com"
  ])

  project = var.project_id
  service = each.value

  disable_on_destroy = false
}

# Artifact Registry for Docker images
resource "google_artifact_registry_repository" "docker_repo" {
  location      = var.region
  repository_id = "binance-api"
  description   = "Docker repository for Binance API"
  format        = "DOCKER"

  depends_on = [google_project_service.required_apis]
}

# Secret Manager for sensitive data
resource "google_secret_manager_secret" "binance_api_key" {
  secret_id = "binance-api-key"

  replication {
    automatic = true
  }

  depends_on = [google_project_service.required_apis]
}

resource "google_secret_manager_secret" "binance_secret_key" {
  secret_id = "binance-secret-key"

  replication {
    automatic = true
  }

  depends_on = [google_project_service.required_apis]
}

resource "google_secret_manager_secret" "binance_testnet" {
  secret_id = "binance-testnet"

  replication {
    automatic = true
  }

  depends_on = [google_project_service.required_apis]
}

# Cloud Run Service
resource "google_cloud_run_v2_service" "binance_api" {
  name     = "binance-connector-api"
  location = var.region

  template {
    service_account = google_service_account.cloud_run.email

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker_repo.repository_id}/binance-api:${var.image_tag}"

      ports {
        container_port = 8000
      }

      env {
        name = "BINANCE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.binance_api_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "BINANCE_SECRET_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.binance_secret_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "BINANCE_TESTNET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.binance_testnet.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "API_HOST"
        value = "0.0.0.0"
      }

      env {
        name  = "API_PORT"
        value = "8000"
      }

      resources {
        limits = {
          cpu    = var.cpu_limit
          memory = var.memory_limit
        }
        cpu_idle = true
      }

      startup_probe {
        http_get {
          path = "/health"
          port = 8000
        }
        initial_delay_seconds = 10
        timeout_seconds       = 3
        period_seconds        = 10
        failure_threshold     = 3
      }

      liveness_probe {
        http_get {
          path = "/health"
          port = 8000
        }
        initial_delay_seconds = 30
        timeout_seconds       = 3
        period_seconds        = 10
        failure_threshold     = 3
      }
    }

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    timeout = "300s"
  }

  traffic {
    percent = 100
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
  }

  depends_on = [
    google_project_service.required_apis,
    google_service_account.cloud_run
  ]
}

# Service Account for Cloud Run
resource "google_service_account" "cloud_run" {
  account_id   = "binance-api-cloud-run"
  display_name = "Service Account for Binance API Cloud Run"
}

# Grant Secret Manager access
resource "google_secret_manager_secret_iam_member" "cloud_run_secret_access" {
  for_each = {
    api_key    = google_secret_manager_secret.binance_api_key.secret_id
    secret_key = google_secret_manager_secret.binance_secret_key.secret_id
    testnet    = google_secret_manager_secret.binance_testnet.secret_id
  }

  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run.email}"
}

# Allow unauthenticated access (or configure IAM for authenticated access)
resource "google_cloud_run_service_iam_member" "public_access" {
  count = var.allow_public_access ? 1 : 0

  service  = google_cloud_run_v2_service.binance_api.name
  location = google_cloud_run_v2_service.binance_api.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# IAM for authenticated access (recommended)
resource "google_cloud_run_service_iam_member" "authenticated_access" {
  count = var.allow_authenticated_access ? 1 : 0

  service  = google_cloud_run_v2_service.binance_api.name
  location = google_cloud_run_v2_service.binance_api.location
  role     = "roles/run.invoker"
  member   = "allAuthenticatedUsers"
}

# -----------------------------------------------------------------------------
# Dagster Orchestrator (Cloud Run + Cloud SQL)
# -----------------------------------------------------------------------------

resource "google_secret_manager_secret" "dagster_db_password" {
  count     = var.enable_dagster ? 1 : 0
  secret_id = "dagster-db-password"

  replication {
    automatic = true
  }

  depends_on = [google_project_service.required_apis]
}

resource "random_password" "dagster_db_password" {
  count   = var.enable_dagster ? 1 : 0
  length  = 24
  special = true
}

resource "google_secret_manager_secret_version" "dagster_db_password" {
  count       = var.enable_dagster ? 1 : 0
  secret      = google_secret_manager_secret.dagster_db_password[0].id
  secret_data = random_password.dagster_db_password[0].result
}

resource "google_sql_database_instance" "dagster" {
  count            = var.enable_dagster ? 1 : 0
  name             = "dagster-metadata"
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier = var.dagster_sql_tier

    backup_configuration {
      enabled = true
    }

    ip_configuration {
      ipv4_enabled = true
    }
  }

  deletion_protection = false
  depends_on          = [google_project_service.required_apis]
}

resource "google_sql_database" "dagster" {
  count    = var.enable_dagster ? 1 : 0
  name     = "dagster"
  instance = google_sql_database_instance.dagster[0].name
}

resource "google_sql_user" "dagster" {
  count    = var.enable_dagster ? 1 : 0
  name     = "dagster"
  instance = google_sql_database_instance.dagster[0].name
  password = random_password.dagster_db_password[0].result
}

resource "google_service_account" "dagster_cloud_run" {
  count        = var.enable_dagster ? 1 : 0
  account_id   = "dagster-orchestrator-run"
  display_name = "Dagster Orchestrator Cloud Run"
}

resource "google_project_iam_member" "dagster_cloudsql_client" {
  count   = var.enable_dagster ? 1 : 0
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.dagster_cloud_run[0].email}"
}

resource "google_secret_manager_secret_iam_member" "dagster_secret_access" {
  count     = var.enable_dagster ? 1 : 0
  secret_id = google_secret_manager_secret.dagster_db_password[0].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.dagster_cloud_run[0].email}"
}

resource "google_cloud_run_v2_service" "dagster_orchestrator" {
  count    = var.enable_dagster ? 1 : 0
  name     = "dagster-orchestrator"
  location = var.region

  template {
    service_account = google_service_account.dagster_cloud_run[0].email

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker_repo.repository_id}/dagster-orchestrator:${var.dagster_image_tag}"

      ports {
        container_port = 3000
      }

      env {
        name  = "DAGSTER_HOME"
        value = "/app/data_platform/orchestration/dagster/dagster_home"
      }

      env {
        name  = "DAGSTER_PG_HOST"
        value = "/cloudsql/${google_sql_database_instance.dagster[0].connection_name}"
      }

      env {
        name  = "DAGSTER_PG_DB"
        value = google_sql_database.dagster[0].name
      }

      env {
        name  = "DAGSTER_PG_USER"
        value = google_sql_user.dagster[0].name
      }

      env {
        name = "DAGSTER_PG_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.dagster_db_password[0].secret_id
            version = "latest"
          }
        }
      }

      resources {
        limits = {
          cpu    = var.dagster_cpu_limit
          memory = var.dagster_memory_limit
        }
      }

      startup_probe {
        http_get {
          path = "/server_info"
          port = 3000
        }
        initial_delay_seconds = 20
        timeout_seconds       = 5
        period_seconds        = 10
        failure_threshold     = 6
      }

      liveness_probe {
        http_get {
          path = "/server_info"
          port = 3000
        }
        initial_delay_seconds = 30
        timeout_seconds       = 5
        period_seconds        = 20
        failure_threshold     = 3
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.dagster[0].connection_name]
      }
    }

    scaling {
      min_instance_count = var.dagster_min_instances
      max_instance_count = var.dagster_max_instances
    }
  }

  traffic {
    percent = 100
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
  }

  depends_on = [
    google_project_service.required_apis,
    google_sql_database_instance.dagster,
    google_sql_database.dagster,
    google_sql_user.dagster,
    google_secret_manager_secret_version.dagster_db_password,
  ]
}

resource "google_cloud_run_service_iam_member" "dagster_public_access" {
  count = var.enable_dagster && var.dagster_allow_public_access ? 1 : 0

  service  = google_cloud_run_v2_service.dagster_orchestrator[0].name
  location = google_cloud_run_v2_service.dagster_orchestrator[0].location
  role     = "roles/run.invoker"
  member   = "allUsers"
}
