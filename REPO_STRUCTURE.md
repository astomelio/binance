# Repo Structure

Estructura propuesta para separar responsabilidades y permitir reutilización:

```
binance/
├── app.py                      # Wrapper compat (importa apps/api/main.py)
├── run.py                      # Wrapper compat (importa apps/api/run.py)
├── apps/
│   ├── api/
│   │   ├── main.py             # FastAPI principal (endpoints spot/futures/fees)
│   │   └── run.py              # Runner uvicorn para la API
│   ├── automation/
│   │   ├── fee_calculator.py   # Cálculo de fees y rentabilidad
│   │   ├── market_alert_engine.py
│   │   ├── automated_trading.py
│   │   └── trading_strategy_500usd.py
│   └── integrations/
│       ├── bot_integrator.py
│       ├── trading_signals.py
│       ├── example_integration.py
│       └── smart_orders_demo.py
├── trading_lib/                # Librería reusable (estrategias/backtest/live)
│   ├── api_client.py
│   ├── backtest.py
│   ├── fees.py
│   ├── indicators.py
│   ├── live.py
│   ├── models.py
│   ├── zones.py
│   └── strategies/
├── examples/
│   └── reusable_model_pipeline.py
├── infra/                      # Terraform para GCP
├── .github/workflows/          # CI/CD
└── legacy/chalice/             # Archivos heredados (chalice/backup)
```

## Reglas prácticas

- Código reusable de trading: `trading_lib/`
- Código de API HTTP: `apps/api/`
- Orquestadores/scripts operativos: `apps/automation/`
- Integraciones con bots externos: `apps/integrations/`
- Archivos antiguos: `legacy/`

## Compatibilidad

Se dejaron wrappers en raíz (`app.py`, `run.py`, `market_alert_engine.py`, etc.) para no romper:

- `uvicorn app:app ...`
- `python run.py`
- `make alerts`

