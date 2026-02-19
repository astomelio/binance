# Guía de Despliegue en GCP con Terraform y CI/CD

Esta guía explica cómo desplegar en Google Cloud Platform usando Terraform y GitHub Actions para CI/CD:

- API de Binance (FastAPI)
- Orquestador Dagster (Cloud Run + Cloud SQL)

## 📋 Prerequisitos

1. **Cuenta de GCP** con facturación habilitada
2. **GitHub Repository** con el código
3. **Terraform** instalado localmente (opcional, para pruebas)
4. **gcloud CLI** instalado y configurado

## 🚀 Configuración Inicial

### 1. Configurar GCP Project

```bash
# Login a GCP
gcloud auth login

# Crear proyecto (o usar existente)
gcloud projects create your-project-id --name="Binance API"

# Configurar proyecto
gcloud config set project your-project-id

# Habilitar facturación
gcloud billing projects link your-project-id --billing-account=YOUR_BILLING_ACCOUNT
```

### 2. Crear Service Account para CI/CD

```bash
# Crear service account
gcloud iam service-accounts create github-actions \
    --display-name="GitHub Actions Service Account"

# Asignar roles necesarios
gcloud projects add-iam-policy-binding your-project-id \
    --member="serviceAccount:github-actions@your-project-id.iam.gserviceaccount.com" \
    --role="roles/run.admin"

gcloud projects add-iam-policy-binding your-project-id \
    --member="serviceAccount:github-actions@your-project-id.iam.gserviceaccount.com" \
    --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding your-project-id \
    --member="serviceAccount:github-actions@your-project-id.iam.gserviceaccount.com" \
    --role="roles/secretmanager.admin"

gcloud projects add-iam-policy-binding your-project-id \
    --member="serviceAccount:github-actions@your-project-id.iam.gserviceaccount.com" \
    --role="roles/storage.admin"

# Crear y descargar key
gcloud iam service-accounts keys create github-actions-key.json \
    --iam-account=github-actions@your-project-id.iam.gserviceaccount.com
```

### 3. Crear GCS Bucket para Terraform State

```bash
# Crear bucket
gsutil mb -p your-project-id -l us-central1 gs://your-terraform-state-bucket

# Habilitar versionado
gsutil versioning set on gs://your-terraform-state-bucket
```

### 4. Configurar GitHub Secrets

Ve a tu repositorio en GitHub → Settings → Secrets and variables → Actions

Agrega los siguientes secrets:

- `GCP_PROJECT_ID`: Tu project ID de GCP
- `GCP_SA_KEY`: Contenido del archivo `github-actions-key.json` (todo el JSON)
- `TERRAFORM_STATE_BUCKET`: Nombre del bucket de GCS (ej: `your-terraform-state-bucket`)

### 5. Configurar Secrets de Binance

```bash
# Crear secrets en Secret Manager
echo -n "your-binance-api-key" | gcloud secrets create binance-api-key \
    --data-file=- \
    --replication-policy="automatic"

echo -n "your-binance-secret-key" | gcloud secrets create binance-secret-key \
    --data-file=- \
    --replication-policy="automatic"

echo -n "true" | gcloud secrets create binance-testnet \
    --data-file=- \
    --replication-policy="automatic"
```

## 📁 Estructura del Proyecto

```
binance/
├── infra/
│   ├── main.tf              # Recursos principales
│   ├── variables.tf          # Variables
│   ├── outputs.tf           # Outputs
│   ├── terraform.tfvars     # Valores de variables (NO commitear)
│   └── backend.tf           # Configuración de backend (NO commitear)
├── .github/
│   └── workflows/
│       ├── deploy.yml       # CI/CD pipeline
│       └── terraform-validate.yml
├── Dockerfile
├── Dockerfile.dagster
└── ...
```

## 🔧 Configuración Local de Terraform

### 1. Configurar backend

```bash
cd infra
cp backend.tf.example backend.tf
# Editar backend.tf con tu bucket
```

### 2. Configurar variables

```bash
cp terraform.tfvars.example terraform.tfvars
# Editar terraform.tfvars con tus valores
```

### 3. Inicializar Terraform

```bash
terraform init
```

### 4. Plan y Apply

```bash
# Ver qué se va a crear
terraform plan

# Aplicar cambios
terraform apply
```

## 🔄 CI/CD Pipeline

El pipeline de GitHub Actions se ejecuta automáticamente:

1. **On Push to main/develop**: 
   - Ejecuta tests
   - Build Docker images (`binance-api` y `dagster-orchestrator`)
   - Push a Artifact Registry
   - Terraform plan
   - Terraform apply (solo en main)

2. **On Pull Request**:
   - Ejecuta tests
   - Terraform validate
   - Terraform plan (sin apply)

### Workflow Manual

También puedes ejecutar el workflow manualmente:

1. Ve a Actions en GitHub
2. Selecciona "Deploy to GCP Cloud Run"
3. Click en "Run workflow"
4. Selecciona el environment (staging/production)

## 🌍 Variables de Entorno

Las variables de entorno se configuran automáticamente desde Secret Manager:

- `BINANCE_API_KEY` - Desde Secret Manager
- `BINANCE_SECRET_KEY` - Desde Secret Manager
- `BINANCE_TESTNET` - Desde Secret Manager
- `API_HOST` - "0.0.0.0" (fijo)
- `API_PORT` - "8000" (fijo)

Para Dagster:

- `DAGSTER_HOME` - ruta de configuración Dagster
- `DAGSTER_PG_HOST`, `DAGSTER_PG_DB`, `DAGSTER_PG_USER` - metadatos Postgres
- `DAGSTER_PG_PASSWORD` - desde Secret Manager (`dagster-db-password`)

## 📊 Monitoreo

### Ver logs

```bash
# Logs de Cloud Run
gcloud run services logs read binance-connector-api --region=us-central1
```

### Métricas

- Ve a Cloud Console → Cloud Run → binance-connector-api
- Revisa métricas de:
  - Requests
  - Latency
  - Errors
  - CPU/Memory usage

## 🔒 Seguridad

### IAM

Por defecto, el servicio solo permite acceso autenticado. Para cambiar:

```hcl
# En variables.tf
allow_public_access = false  # Cambiar a true para acceso público
allow_authenticated_access = true
```

### Secrets

- Los secrets se almacenan en Secret Manager
- Solo el service account de Cloud Run tiene acceso
- Los secrets se rotan manualmente

## 💰 Costos Estimados

Con la configuración por defecto:

- **Cloud Run**: ~$0.40/mes (con 0 min instances)
- **Artifact Registry**: ~$0.10/mes
- **Secret Manager**: Gratis (primeros 6 secrets)
- **Terraform State (GCS)**: ~$0.01/mes

**Total estimado**: ~$0.50/mes (sin tráfico)

## 🐛 Troubleshooting

### Error: "Permission denied"

```bash
# Verificar permisos del service account
gcloud projects get-iam-policy your-project-id \
    --flatten="bindings[].members" \
    --filter="bindings.members:github-actions@*"
```

### Error: "Image not found"

```bash
# Verificar que la imagen existe
gcloud artifacts docker images list \
    us-central1-docker.pkg.dev/your-project-id/binance-api
```

### Error: "Secret not found"

```bash
# Listar secrets
gcloud secrets list

# Verificar acceso
gcloud secrets get-iam-policy binance-api-key
```

## 📝 Próximos Pasos

1. ✅ Configurar alertas en Cloud Monitoring
2. ✅ Configurar custom domain
3. ✅ Habilitar Cloud CDN para mejor performance
4. ✅ Configurar backup automático de Terraform state
5. ✅ Agregar staging environment

## 🔗 Enlaces Útiles

- [Cloud Run Documentation](https://cloud.google.com/run/docs)
- [Terraform GCP Provider](https://registry.terraform.io/providers/hashicorp/google/latest/docs)
- [GitHub Actions](https://docs.github.com/en/actions)
- [Secret Manager](https://cloud.google.com/secret-manager/docs)
