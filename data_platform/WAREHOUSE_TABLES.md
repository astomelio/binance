# Tablas DuckDB (artifacts/warehouse/crypto.duckdb)

**Esquema único: `main`**

## Tabla principal (la que usas)

| Tabla | Descripción |
|-------|-------------|
| **decision_features** | Features + labels para ML/trading. Incluye alpha_score, fwd_return_1h/4h/24h, regime_combo. |

```sql
SELECT * FROM main.decision_features WHERE fwd_return_4h IS NOT NULL LIMIT 10;
```

## Tablas intermedias (pipeline interno)

| Tabla | Descripción |
|-------|-------------|
| slv_decision_features | Silver: features base antes de enriquecer |
| br_market_snapshot | Bronze: join market + derivatives + flow + cross_ex + dex |
| br_macro_context | Bronze: join global + fear_greed + macro + fed |

## Tablas raw (input del loader)

market_snapshot_raw, derivatives_snapshot_raw, derivatives_flow_raw, cross_exchange_snapshot_raw, dex_snapshot_raw, global_market_raw, fear_greed_raw, macro_rates_raw, fed_calendar_raw

---

**Reset limpio:** `make warehouse-reset` (cierra DBeaver antes)
