# Pipeline Testnet Binance

- **Requisitos:** `.env` con `BINANCE_TESTNET=true` y API keys de [testnet.binance.vision](https://testnet.binance.vision/)
- **Levantar:** `docker compose -f docker-compose.run.yml up -d --build`
- **Monitor:** http://localhost:8000/monitor
- **Dagster:** http://localhost:3000 → Jobs: `08_operacion_testnet_15m`, `09_ejecutar_testnet_solo`
- **Schedule:** `08_operacion_testnet_cada_15m` cada 15 min
