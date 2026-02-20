#!/bin/bash
# Solo sincroniza data_lake y/o DuckDB desde remoto (sin ejecutar nada).
# Uso: REMOTE_HOST=user@ip-pc-b ./scripts/remote_sync.sh [data_lake|warehouse|all]

REMOTE_HOST="${REMOTE_HOST:?Set REMOTE_HOST=user@ip-pc-b}"
REMOTE_PATH="${REMOTE_PATH:-~/binance}"
LOCAL_PATH="${LOCAL_PATH:-$(pwd)}"
MODE="${1:-all}"

case "$MODE" in
  data_lake)
    echo "Sincronizando data_lake..."
    rsync -avz "$REMOTE_HOST:$REMOTE_PATH/data_lake/" "$LOCAL_PATH/data_lake/"
    ;;
  warehouse)
    echo "Sincronizando DuckDB..."
    mkdir -p "$LOCAL_PATH/artifacts/warehouse"
    rsync -avz "$REMOTE_HOST:$REMOTE_PATH/artifacts/warehouse/crypto.duckdb" \
      "$LOCAL_PATH/artifacts/warehouse/"
    ;;
  all)
    echo "Sincronizando data_lake..."
    rsync -avz "$REMOTE_HOST:$REMOTE_PATH/data_lake/" "$LOCAL_PATH/data_lake/"
    echo "Sincronizando DuckDB..."
    mkdir -p "$LOCAL_PATH/artifacts/warehouse"
    rsync -avz "$REMOTE_HOST:$REMOTE_PATH/artifacts/warehouse/crypto.duckdb" \
      "$LOCAL_PATH/artifacts/warehouse/"
    ;;
  *)
    echo "Uso: $0 [data_lake|warehouse|all]"
    exit 1
    ;;
esac
echo "Listo."
