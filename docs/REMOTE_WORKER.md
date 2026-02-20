# PC remoto como worker (más memoria)

Usar el PC con más RAM para backfill y cargar datos, trabajar desde este PC.

## Setup en PC B (el de más memoria)

```bash
# 1. Clonar repo
git clone <repo> ~/binance
cd ~/binance

# 2. Instalar
pip install -r requirements.txt

# 3. Crear directorios
mkdir -p data_lake artifacts/warehouse
```

## Desde PC A (este)

### 1. Configurar SSH sin clave

```bash
# Generar clave si no tienes
ssh-keygen -t ed25519

# Copiar a PC B
ssh-copy-id usuario@ip-pc-b
```

### 2. Ejecutar backfill en remoto y traer DuckDB

```bash
# Backfill completo + warehouse-load en remoto, luego sincroniza DuckDB aquí
REMOTE_HOST=usuario@ip-pc-b make warehouse-remote-backfill
```

### 3. Solo sincronizar (sin ejecutar nada)

```bash
# Traer data_lake + DuckDB
REMOTE_HOST=usuario@ip-pc-b make warehouse-remote-sync

# O solo DuckDB
REMOTE_HOST=usuario@ip-pc-b bash scripts/remote_sync.sh warehouse
```

### 4. Comandos manuales

```bash
# Ejecutar backfill en remoto
ssh usuario@ip-pc-b "cd ~/binance && make warehouse-backfill-vision-all"

# Ejecutar warehouse-load en remoto
ssh usuario@ip-pc-b "cd ~/binance && make warehouse-load"

# Traer DuckDB
rsync -avz usuario@ip-pc-b:~/binance/artifacts/warehouse/crypto.duckdb ./artifacts/warehouse/
```

## Terraform

Si usas Terraform para infra (ej. VM en cloud):

- Terraform en PC B o en un repo separado
- Provisiona VM con más RAM
- El script `remote_backfill.sh` usaría `REMOTE_HOST=user@ip-vm`

## Variables

| Variable | Default | Descripción |
|----------|---------|-------------|
| REMOTE_HOST | (requerido) | user@ip o user@hostname |
| REMOTE_PATH | ~/binance | Ruta del repo en remoto |
| LOCAL_PATH | $(pwd) | Donde sincronizar |
