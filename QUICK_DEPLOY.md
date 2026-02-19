# 🚀 Quick Start - Despliegue en GCP

Guía rápida para desplegar en GCP en 5 minutos.

## ⚡ Setup Rápido

### 1. Configurar GCP (una vez)

```bash
# Login
gcloud auth login

# Crear proyecto
gcloud projects create your-project-id

# Configurar proyecto
gcloud config set project your-project-id

# Habilitar APIs necesarias
gcloud services enable run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    secretmanager.googleapis.com
```

### 2. Crear Service Account para GitHub Actions

```bash
# Crear SA
gcloud iam service-accounts create github-actions \
    --display-name="GitHub Actions"

# Asignar roles
PROJECT_ID=$(gcloud config get-value project)
SA_EMAIL="github-actions@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/run.admin"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.admin"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/storage.admin"

# Crear y descargar key
gcloud iam service-accounts keys create github-actions-key.json \
    --iam-account=${SA_EMAIL}
```

### 3. Crear Bucket para Terraform State

```bash
PROJECT_ID=$(gcloud config get-value project)
gsutil mb -p ${PROJECT_ID} -l us-central1 gs://${PROJECT_ID}-terraform-state
gsutil versioning set on gs://${PROJECT_ID}-terraform-state
```

### 4. Configurar Secrets en GitHub

Ve a: `Settings → Secrets and variables → Actions`

Agrega:
- `GCP_PROJECT_ID`: Tu project ID
- `GCP_SA_KEY`: Contenido completo de `github-actions-key.json`
- `TERRAFORM_STATE_BUCKET`: `${PROJECT_ID}-terraform-state`

### 5. Configurar Secrets de Binance

```bash
# Crear secrets
echo -n "your-binance-api-key" | gcloud secrets create binance-api-key --data-file=-
echo -n "your-binance-secret-key" | gcloud secrets create binance-secret-key --data-file=-
echo -n "true" | gcloud secrets create binance-testnet --data-file=-
```

### 6. Configurar Terraform

```bash
cd infra

# Backend
cat > backend.tf << EOF
terraform {
  backend "gcs" {
    bucket = "${PROJECT_ID}-terraform-state"
    prefix = "terraform/state"
  }
}
EOF

# Variables
cat > terraform.tfvars << EOF
project_id = "${PROJECT_ID}"
region     = "us-central1"
image_tag  = "latest"
EOF
```

### 7. Push a GitHub

```bash
git add .
git commit -m "Add GCP deployment configuration"
git push origin main
```

## ✅ Verificar Despliegue

Después del push, el workflow de GitHub Actions:

1. ✅ Ejecuta tests
2. ✅ Build Docker image
3. ✅ Push a Artifact Registry
4. ✅ Terraform plan
5. ✅ Terraform apply
6. ✅ Health check

### Ver URL del servicio

```bash
# Desde Terraform
cd infra
terraform output service_url

# O desde GCP Console
gcloud run services describe binance-connector-api --region=us-central1 --format="value(status.url)"
```

## 🔧 Comandos Útiles

```bash
# Ver logs
gcloud run services logs read binance-connector-api --region=us-central1

# Ver estado del servicio
gcloud run services describe binance-connector-api --region=us-central1

# Actualizar secrets
echo -n "new-value" | gcloud secrets versions add binance-api-key --data-file=-

# Destruir todo
cd infra
terraform destroy
```

## 📊 Monitoreo

- **Cloud Console**: https://console.cloud.google.com/run
- **Logs**: `gcloud run services logs read binance-connector-api`
- **Métricas**: Cloud Console → Cloud Run → Métricas

## 💰 Costos

- **Cloud Run**: ~$0.40/mes (sin tráfico)
- **Artifact Registry**: ~$0.10/mes
- **Total**: ~$0.50/mes

## 🐛 Troubleshooting

### Error: "Permission denied"
```bash
# Verificar permisos
gcloud projects get-iam-policy $(gcloud config get-value project) \
    --flatten="bindings[].members" \
    --filter="bindings.members:github-actions@*"
```

### Error: "Secret not found"
```bash
# Listar secrets
gcloud secrets list

# Verificar acceso
gcloud secrets get-iam-policy binance-api-key
```

### Ver logs del workflow
Ve a: GitHub → Actions → Ver logs del workflow fallido

## 📚 Documentación Completa

Ver [DEPLOYMENT.md](DEPLOYMENT.md) para documentación detallada.
