#!/bin/bash
# Ejecuta backfill en PC remoto y sincroniza DuckDB aquí.
# Uso: REMOTE_HOST=user@ip-pc-b ./scripts/remote_backfill.sh
#      REMOTE_HOST=user@ip-pc-b REMOTE_PATH=~/binance ./scripts/remote_backfill.sh

set -e
REMOTE_HOST="${REMOTE_HOST:?Set REMOTE_HOST=user@ip-pc-b}"
REMOTE_PATH="${REMOTE_PATH:-~/binance}"
LOCAL_PATH="${LOCAL_PATH:-$(pwd)}"

echo "=== 1. Ejecutando backfill en $REMOTE_HOST ==="
ssh "$REMOTE_HOST" "cd $REMOTE_PATH && make warehouse-backfill-vision-all"

echo "=== 2. Ejecutando warehouse-load en remoto ==="
ssh "$REMOTE_HOST" "cd $REMOTE_PATH && make warehouse-load"

echo "=== 3. Sincronizando DuckDB a local ==="
mkdir -p "$LOCAL_PATH/artifacts/warehouse"
rsync -avz "$REMOTE_HOST:$REMOTE_PATH/artifacts/warehouse/crypto.duckdb" \
  "$LOCAL_PATH/artifacts/warehouse/"

echo "=== Listo. DuckDB en $LOCAL_PATH/artifacts/warehouse/crypto.duckdb ==="
