# Binance Data Platform + AI Strategies

Plataforma de datos y exploración de estrategias para trading cuantitativo con Binance Futures.

## Qué hace

- **Data platform**: Backfill histórico desde data.binance.vision (klines, funding rate, open interest)
- **Warehouse**: DuckDB + dbt para features de decisión (basis, momentum, funding, etc.)
- **AI explorer**: Librería para explorar estrategias (alpha_score, heurística, mean reversion)
- **Backtest**: Vectores de asignación, entrenamiento de modelos, inferencia

## Quick start

```bash
# 1. Instalar
pip install -r requirements.txt

# 2. Backfill (top ~20 símbolos, 1h, 36 meses)
make warehouse-backfill-vision

# 3. Cargar a DuckDB + dbt
make warehouse-load

# 4. Explorar estrategias
make ai-explorer-agent
```

## Estructura

```
├── data_platform/       # Pipeline bronze/silver/gold
│   ├── backfill_from_vision.py   # Backfill desde data.binance.vision
│   ├── loaders/                  # Bronze → DuckDB
│   ├── dbt/                      # Modelos dbt
│   └── transforms/               # Silver, gold
├── ai/                   # ML y estrategias
│   ├── explorer/         # Librería de exploración (agentes)
│   ├── allocation/       # Backtest, vectores de asignación
│   ├── training/         # Entrenamiento + calibration
│   └── inference/        # Predicción
├── trading_lib/          # Utilidades de trading
├── data_lake/            # Bronze/silver/gold (JSONL particionado)
└── artifacts/warehouse/  # DuckDB
```

## Comandos principales

| Comando | Descripción |
|---------|-------------|
| `make warehouse-backfill-vision` | Backfill 1h, top ~20 símbolos (funding + OI) |
| `make warehouse-backfill-vision-all` | Todas las monedas (~500, ~30-40 GB) |
| `make warehouse-load` | Cargar bronze → DuckDB + dbt |
| `make ai-explorer-agent` | Explorar estrategias (quick) |
| `make ai-backtest` | Backtest con vectores de asignación |
| `make ai-train` | Entrenar modelo + calibration |

## Variables de entorno

```bash
# Data lake (default: data_lake)
LAKE_ROOT=/path/to/data_lake

# Símbolos: default, top (~20), all (~500)
DP_SYMBOLS=BTCUSDT,ETHUSDT,BNBUSDT
DP_SYMBOLS=top
DP_SYMBOLS=all

# API Binance (para collectors live, opcional)
BINANCE_API_KEY=...
BINANCE_SECRET_KEY=...
```

Ver `env.example` para más opciones.

## Documentación

- [AI Backtest y parámetros](docs/AI_BACKTEST_PARAMS.md)
- [Data platform](data_platform/README.md)
- [AI explorer (agentes)](ai/explorer/README.md)
- [PC remoto como worker](docs/REMOTE_WORKER.md)

## Requisitos

- Python 3.10+
- DuckDB
- dbt (para modelos)
