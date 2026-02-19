variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-central1"
}

variable "image_tag" {
  description = "Docker image tag (usually git commit SHA or version)"
  type        = string
  default     = "latest"
}

variable "cpu_limit" {
  description = "CPU limit for Cloud Run service"
  type        = string
  default     = "2"
}

variable "memory_limit" {
  description = "Memory limit for Cloud Run service"
  type        = string
  default     = "512Mi"
}

variable "min_instances" {
  description = "Minimum number of Cloud Run instances"
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Maximum number of Cloud Run instances"
  type        = number
  default     = 10
}

variable "allow_public_access" {
  description = "Allow public unauthenticated access to the API"
  type        = bool
  default     = false
}

variable "allow_authenticated_access" {
  description = "Allow authenticated access to the API"
  type        = bool
  default     = true
}

variable "enable_dagster" {
  description = "Deploy Dagster orchestrator in Cloud Run"
  type        = bool
  default     = true
}

variable "dagster_image_tag" {
  description = "Docker image tag for Dagster service"
  type        = string
  default     = "latest"
}

variable "dagster_cpu_limit" {
  description = "CPU limit for Dagster Cloud Run service"
  type        = string
  default     = "1"
}

variable "dagster_memory_limit" {
  description = "Memory limit for Dagster Cloud Run service"
  type        = string
  default     = "1Gi"
}

variable "dagster_min_instances" {
  description = "Minimum instances for Dagster Cloud Run service"
  type        = number
  default     = 1
}

variable "dagster_max_instances" {
  description = "Maximum instances for Dagster Cloud Run service"
  type        = number
  default     = 1
}

variable "dagster_allow_public_access" {
  description = "Allow public unauthenticated access to Dagster UI"
  type        = bool
  default     = false
}

variable "dagster_sql_tier" {
  description = "Cloud SQL tier for Dagster metadata DB"
  type        = string
  default     = "db-g1-small"
}
