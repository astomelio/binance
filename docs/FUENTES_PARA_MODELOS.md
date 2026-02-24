# Fuentes de datos y aporte a los modelos

Evaluación de qué fuentes y variables **aportan señal real** a los modelos (entrenamiento, inferencia, riesgo) y cuáles son redundantes o aún no usadas.

---

## 1. Flujo de datos → modelo

```
Raw (bronze) → br_market_snapshot + br_macro_context → slv_decision_features
    → fct_decision_features (decision_features) → ML training / inference / backtest
```

- **Training**: `examples/quant_optuna_tuning.py`, `trading_lib/quant/labels.py` → lista fija de **feature_names**.
- **Inferencia**: `ai/inference/predictor.py` usa `alpha_score`, `regime_combo`, `alpha_signal` de `decision_features`.
- **Riesgo**: `fed_window` (derivado de FED calendar) bloquea trades en ventanas FOMC; `regime_combo` define políticas (blocked regimes).

---

## 2. Fuentes que SÍ aportan a los modelos

| Fuente | Variable(s) | Uso en el modelo |
|--------|-------------|-------------------|
| **Alternative.me** | `fear_greed_value` | Feature de entrenamiento (sentimiento; riesgo/aversion). |
| **FED Calendar** | `next_fed_decision_date` → `fed_window` | Control de riesgo: NO_TRADE en PRE_EVENT/POST_EVENT; cierre de posiciones en backtest. |
| **Binance Vision** | market_snapshot, derivatives, flow | Base: precios, basis_bps, funding, OI, long/short, momentum, alpha_signal heurístico. |
| **Bybit / OKX** | cross_exchange_* | Features: spread, mean_diff, bybit_okx_delta, cross_exchange_score. |
| **DexScreener** | dex_* | Features: dex_cex_basis_bps, liquidez, volumen, txn_imbalance, dex_alpha_score. |

**Conclusión**: Fear & Greed, FED calendar, Binance, cross-exchange y DEX están **conectados** al pipeline y aportan. Prioridad alta mantenerlas y tener histórico alineado (fechas).

---

## 3. Fuentes que aportan solo contexto (hoy no en el predictor)

| Fuente | Variable(s) | Estado | Recomendación |
|--------|-------------|--------|----------------|
| **CoinGecko** | `btc_dominance`, `total_market_cap_usd` | En `decision_features` pero **no** en la lista de features de entrenamiento. | Añadir a feature set como régimen mercado (risk-on/risk-off). |
| **FRED** | `fed_funds_rate` | En `decision_features` pero **no** en features de entrenamiento. | Añadir para régimen macro (liquidez/tightening). |

**Conclusión**: Son datos que **pueden** aportar; hoy solo están en la tabla. Incluirlos en `feature_names` y en el modelo para que la fuente “aporte” de verdad.

---

## 4. Fuentes añadidas (SP500, petróleo, horarios, mean reversion)

| Fuente | Variable(s) | Uso |
|--------|-------------|-----|
| **FRED macro_assets** | `sp500_close`, `oil_wti_usd` | S&P 500 y WTI oil diarios; join por fecha en br_macro_context. |
| **Horarios** | `session_us_open`, `session_china_open`, `session_us_or_china_open` | US 14-21 UTC, China 1-7 UTC; detección de sesiones. |
| **Earnings** | `earnings_window` | Dentro de 5 días de clusters de earnings (Jan/Apr/Jul/Oct). |
| **Mean reversion** | `price_zscore_24h`, `price_deviation_pct_24h` | Z-score y desviación % respecto a MA 24h. |

---

## 5. Fuentes opcionales / futuras

| Fuente | Datos | Aporte potencial |
|--------|--------|-------------------|
| **Glassnode** | MVRV, SOPR, btc_dominance on-chain | Señal de valoración (MVRV) y realización de beneficios (SOPR); régimen on-chain. Requiere API key. |
| **Oro** | Gold spot | FRED retiró GOLDPMGBD228NLBM en 2022; usar Yahoo/Alpha Vantage si se necesita. |
| **Más macro** | Inflación, crédito, etc. | Régimen macro más fino; depende de objetivos del modelo. |

---

## 6. Evaluación de modelos

`examples/quant_model_evaluation.py` compara:
- **LightGBM** vs **XGBoost** vs **mean reversion** (z-score)
- **1 moneda** vs **N monedas**
- Feature sets: full, mean_reversion, macro_only, session_only, microstructure

---

## 7. Resumen ejecutivo

- **Prioridad 1 (ya aportan)**: Fear & Greed, FED Calendar, Binance, Bybit, OKX, DexScreener. Asegurar backfill y fechas alineadas.
- **Prioridad 2 (aporten en el modelo)**: Incluir **btc_dominance**, **fed_funds_rate**, **sp500_close**, **oil_wti_usd**, **session_***, **price_zscore_24h** en el feature set.
- **Prioridad 3 (más datos)**: CoinGecko `/global`; Glassnode si hay key; oro desde otra fuente.
