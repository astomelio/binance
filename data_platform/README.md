# Data Platform (MVP)

Pipeline medallion inicial para trading:

- **Bronze**: ingesta cruda (API local de mercado, CoinGecko global, FRED, calendario FED, on-chain provider opcional)
- **Silver**: normalización de métricas clave
- **Gold**: features de decisión en tiempo real (basis, dominance, macro rate, próxima fecha FED)

## Estructura

```
data_platform/
├── config.py
├── pipeline.py
├── config/
│   └── fed_decision_dates.json
├── ingestion/
│   ├── base.py
│   └── collectors.py
├── storage/
│   └── lake_writer.py
└── transforms/
    ├── silver.py
    └── gold.py
```

## Variables de entorno

- `LAKE_ROOT` (default: `data_lake`)
- `API_BASE_URL` (default: `http://localhost:8000`)
- `FRED_API_KEY` (opcional, para macro real)
- `ONCHAIN_PROVIDER_URL` (opcional, endpoint JSON de provider on-chain)
- `DP_SYMBOLS` (default: `BTCUSDT,ETHUSDT,BNBUSDT`)

## Ejecutar

```bash
# todo el pipeline
python -m data_platform.pipeline --mode all

# por capa
python -m data_platform.pipeline --mode bronze
python -m data_platform.pipeline --mode silver
python -m data_platform.pipeline --mode gold
```

## Orquestación (Dagster + dbt)

Se agregó starter en `orchestration/dagster/`:

```bash
pip install -r requirements-dagster.txt
dagster dev -w data_platform/orchestration/dagster/workspace.yaml
```

Esto te permite materializar assets `bronze_ingestion -> silver_transform -> gold_features`
con lineage visual y schedule.

## Siguiente nivel recomendado

1. Cambiar `gold/decision_features` a tablas BigQuery gestionadas (si aún estás en JSONL local).
2. Agregar Dataflow/PubSub para streaming real.
3. Incluir providers on-chain premium (Glassnode/CryptoQuant/CoinMetrics).
4. Versionar features para backtest reproducible.

