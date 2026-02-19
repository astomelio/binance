# Infraestructura con Terraform

Este directorio contiene la configuración de Terraform para desplegar en GCP:

- API FastAPI (`binance-connector-api`) en Cloud Run
- Dagster OSS (`dagster-orchestrator`) en Cloud Run
- Metadata de Dagster en Cloud SQL PostgreSQL

## 🚀 Inicio Rápido

### 1. Configurar Backend

```bash
cp backend.tf.example backend.tf
# Editar backend.tf con tu bucket de GCS
```

### 2. Configurar Variables

```bash
cp terraform.tfvars.example terraform.tfvars
# Editar terraform.tfvars con tus valores
```

### 3. Inicializar

```bash
terraform init
```

### 4. Plan

```bash
terraform plan
```

### 5. Apply

```bash
terraform apply
```

## 📋 Variables Requeridas

- `project_id`: GCP Project ID
- `region`: GCP Region (default: us-central1)
- `image_tag`: Docker image tag (default: latest)
- `dagster_image_tag`: Docker image tag para Dagster (default: latest)

## 📤 Outputs

Después de `terraform apply`, obtendrás:

- `service_url`: URL del servicio Cloud Run
- `service_name`: Nombre del servicio
- `artifact_registry`: URL del Artifact Registry
- `dagster_service_url`: URL de Dagster UI
- `dagster_sql_instance_connection_name`: instancia Cloud SQL usada por Dagster

## 🔒 Secrets

Los secrets se crean automáticamente pero necesitas poblar los valores:

```bash
echo -n "your-api-key" | gcloud secrets versions add binance-api-key --data-file=-
echo -n "your-secret-key" | gcloud secrets versions add binance-secret-key --data-file=-
echo -n "true" | gcloud secrets versions add binance-testnet --data-file=-
```

`dagster-db-password` se genera automáticamente desde Terraform.

## 🧹 Limpieza

Para destruir toda la infraestructura:

```bash
terraform destroy
```

**⚠️ Advertencia**: Esto eliminará TODO, incluyendo el servicio Cloud Run.
