# Trading Library Reusable

Este paquete separa la logica en capas para evitar scripts sueltos:

- `models.py`: contratos de datos (`Candle`, `FeatureSet`, `SignalDecision`)
- `zones.py`: clasificador de regimen (bearish/sideways/bullish)
- `fees.py`: modelo de fees para edge neto y break-even
- `strategies/`: algoritmos enchufables (ej. `RegimeFuturesStrategy`)
- `backtest.py`: backtester usando exactamente la misma estrategia
- `live.py`: executor live contra la API de futuros
- `api_client.py`: cliente HTTP a tu API local

## Flujo recomendado

1. Diseñas/ajustas estrategia en `strategies/`.
2. La corres en `Backtester`.
3. Si cumple tus metricas, la pasas a `FuturesLiveExecutor`.

## Ejecutar ejemplo unificado

```bash
python examples/reusable_model_pipeline.py
```

O con make:

```bash
make model-pipeline
```

