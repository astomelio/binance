# Esquema: AI → vectores → estrategias y compras

Resumen de la AI que hay ahora y cómo se conecta. **Regla: los outputs que deciden compras son siempre vectores de asignación** (un número por moneda: cuánto long/short).

---

## 1. Resumen de la AI actual

| Componente | Qué hace | Input | Output |
|------------|----------|--------|--------|
| **Datos** | Barras por símbolo y tiempo (precios, volumen, features) | — | `decision_features`: filas (event_time, symbol, features..., fwd_return_1h/4h/24h) |
| **Modelo de entrada (LightGBM/etc.)** | Predice “sube o baja” por fila | Vector de features (por símbolo/barra) | **Score** en [0,1] o [-1,1] → se guarda como `alpha_score` en la fila |
| **Relleno de alpha_score** | Pone el score del modelo en cada fila | Filas + modelo cargado | Filas con `alpha_score`, `model_score`, `entry_probability` |
| **Estrategia (score → vector)** | Convierte scores en “cuánto asignar a cada moneda” | Filas con `alpha_score` (por barra, por símbolo) | **AllocationVector** = `{ "BTCUSDT": 0.2, "ETHUSDT": -0.1, ... }` |
| **Simulación / Backtest** | Ejecuta entradas y salidas con ese vector | Filas (barras) + **AllocationVector por barra** | Retorno neto %, trades, fees |
| **Órdenes (paper/live)** | Convierte vector en órdenes concretas | AllocationVector (o lista de AllocationDecision) | Órdenes (OPEN/CLOSE/REBALANCE) → execution_log |

La **traducción a “qué comprar”** es: modelo da **score por símbolo** → estrategia lo convierte en **vector de asignación** (AllocationVector) → ese vector es lo que se ejecuta (backtest o órdenes).

---

## 2. Contrato: outputs siempre vectores

Para que todo sea replicable y claro:

- **El output de “qué hacer” en cada barra es un vector:**  
  `AllocationVector = dict[symbol, float]`  
  Ejemplo: `{"BTCUSDT": 0.2, "ETHUSDT": -0.1, "BNBUSDT": 0.0}` = 20% long BTC, 10% short ETH, 0% BNB.
- **Tus modelos de AI no tienen por qué devolver directamente ese vector.** Pueden devolver:
  - un **score por símbolo** (o probabilidad), y
  - una **estrategia** que transforme scores → AllocationVector.
- **Toda ejecución (backtest o paper) recibe ese vector** (por barra o por timestamp). Así “lo que dice la AI” = “vector de asignación”; “compras” = aplicar ese vector.

---

## 3. Esquema: inputs y outputs que conectan todo

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  DATOS                                                                       │
│  DuckDB decision_features                                                    │
│  Input:  (ninguno desde tu código)                                          │
│  Output: rows = [{ event_time, symbol, feature_1, ..., fwd_return_1h }, ...] │
└───────────────────────────────────────────┬─────────────────────────────────┘
                                            │
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  MODELO DE AI (entrada / alpha)                                             │
│  LightGBM, XGBoost, etc. (MLflow) o regla fija (DBT alpha_score)            │
│  Input:  features por fila (vector de números)                              │
│  Output: score por fila → se escribe en cada fila como alpha_score [-1,1]   │
│  Código: ai.inference.model_scorer.enrich_rows_with_model(rows, model)       │
└───────────────────────────────────────────┬─────────────────────────────────┘
                                            │ rows con alpha_score
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ESTRATEGIA (score → vector de asignación)                                  │
│  compute_allocations(features_by_symbol) o tu propia función                 │
│  Input:  por cada event_time: { symbol: { alpha_score, fed_window, ... } }   │
│  Output: AllocationVector (cumple I1, I2)                                   │
│  Código: ai.allocation.strategies.compute_allocations                        │
└───────────────────────────────────────────┬─────────────────────────────────┘
                                            │ AllocationVector por barra
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  OPCIONAL: Exit rules (cuándo cerrar)                                       │
│  build_exit_rule(max_bars_held, target_pct, stop_pct)(alloc, context)        │
│  Input:  alloc + context (bars_held, unrealized_pnl)                          │
│  Output: alloc con algunos símbolos forzados a 0                             │
│  Código: ai.allocation.exit_rules                                           │
└───────────────────────────────────────────┬─────────────────────────────────┘
                                            │
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  RISK OVERLAY                                                               │
│  apply_risk_overlay(alloc, max_exposure, max_per_symbol, …)                 │
│  Input:  AllocationVector (propuesta)                                       │
│  Output: AllocationVector que cumple invariantes + límites de riesgo         │
│  Código: ai.allocation.risk                                                 │
└───────────────────────────────────────────┬─────────────────────────────────┘
                                            │ AllocationVector final
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  EJECUCIÓN                                                                   │
│  • Backtest: run_backtest_from_orders(rows, allocations_by_ts)               │
│  • Órdenes: build_orders / rebalance a partir del vector                     │
│  Input:  rows + allocations_by_ts = { event_time: AllocationVector }        │
│  Output: retorno neto %, trades, (opcional) órdenes / execution_log           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Flujo en código (siempre vectores en la ejecución)

1. **Cargar datos**  
   `rows = load_decision_features(horizon="1h", symbols=[...], start=..., end=...)`

2. **Obtener scores de la AI** (modelo o regla)  
   - Con modelo: `rows = enrich_rows_with_model(rows, model)` → cada fila tiene `alpha_score`.  
   - O usar `alpha_score` que ya venga en las filas (p. ej. de DBT).

3. **Score → vector (estrategia)**  
   Por cada barra, construir el vector:
   - Opción A: `alloc = compute_allocations(features_by_symbol, score_key="alpha_score")`  
     → `alloc` es un **AllocationVector**.
   - Opción B: tú mismo mapeas `alpha_score` por símbolo a un número en [-1, 1] y armas  
     `alloc = { symbol: tu_allocation }`.

4. **Ejecutar con ese vector**  
   - Simulación:  
     `allocations_by_ts[event_time] = alloc`  
     `result = run_backtest_from_orders(rows, allocations_by_ts, horizon="1h", symbols=[...])`  
   - Órdenes: usar el mismo `AllocationVector` (o la lista de AllocationDecision que generes a partir de él) para construir órdenes y mandarlas a paper/live.

---

## 5. Invariantes formales del vector

Cualquier `AllocationVector` que salga de la estrategia o entre a ejecución debe cumplir:

| Invariante | Definición |
|------------|------------|
| **I1 (rango)** | ∀s, `a[s] ∈ [-1, 1]` |
| **I2 (exposición total)** | `Σ_s \|a[s]\| ≤ max_exposure` (típicamente 1.0) |
| **I3 (tipo)** | Claves = símbolos (str), valores = float |

- **Validación:** `ai.allocation.invariants.check_invariants(alloc, max_exposure)` → `(ok, violaciones)`.
- **Clamp por símbolo:** `invariants.clamp_vector(alloc)` fuerza I1.

---

## 6. Normalización de exposición total

**Dónde:** `ai.allocation.constraints.normalize_exposure(alloc, max_exposure=1.0)`.

**Regla:**  
Si `total = Σ_s |a_s| > max_exposure`, se devuelve el vector escalado:  
`a_s' = a_s * (max_exposure / total)`.  
Si `total ≤ max_exposure`, el vector no se modifica.  
Se mantienen signos y proporciones relativas entre símbolos.

Toda estrategia que quiera cumplir I2 debe terminar con esta normalización (p. ej. `compute_allocations` ya la aplica).

---

## 7. Capa explícita de risk management

**Dónde:** `ai.allocation.risk.apply_risk_overlay(alloc, ...)`.

Se aplica **después** de la estrategia y **antes** de ejecución/backtest. Parámetros típicos:

| Parámetro | Efecto |
|-----------|--------|
| `max_exposure` | Límite exposición bruta (sum \|a\|); se normaliza con `normalize_exposure`. |
| `max_per_symbol` | Tope por símbolo: \|a[s]\| ≤ este valor. |
| `max_net_exposure` | Límite exposición neta (long - short); si se excede, se escala el vector. |
| `zero_on_drawdown_above` | Kill switch: si drawdown ≥ umbral, devuelve vector cero (cierra todo). Requiere `current_equity` y `peak_equity`. |

Uso en pipeline:  
`alloc_raw = compute_allocations(...); alloc = apply_risk_overlay(alloc_raw, max_per_symbol=0.4, max_exposure=1.0)`.

---

## 8. Momento de cerrar una posición

**Cierre implícito (ya ocurre):** En la siguiente barra, si el vector asigna **0** a ese símbolo, la ejecución/backtest cierra la posición (cambio de posición → fee/slippage). No hace falta lógica extra.

**Cierre explícito (reglas de salida):** Para forzar cierre bajo condiciones (tiempo, PnL), usa `ai.allocation.exit_rules`:

| Regla | Descripción |
|-------|-------------|
| Por tiempo | `close_after_n_bars`: cerrar si la posición lleva más de N barras abierta. |
| Target / stop | `close_on_stop_or_target`: cerrar si PnL no realizado ≥ target_pct o ≤ stop_pct. |
| Combinada | `build_exit_rule(max_bars_held=..., target_pct=..., stop_pct=...)` devuelve una función `(alloc, context) -> alloc` que fuerza 0 en símbolos que cumplan las condiciones. |

El **contexto** (`ExitContext`) puede traer `bars_held_by_symbol`, `unrealized_pnl_by_symbol`, etc.; lo alimentas tú en cada barra desde el estado del backtest o del ejecutor.

---

## 9. Tipos clave (referencia)

| Nombre | Significado |
|--------|-------------|
| **AllocationVector** | `dict[str, float]`: por símbolo, asignación en [-1, 1]. Es el output estándar de “qué hacer” y el input de ejecución. |
| **AllocationsByTime** | `dict[str, AllocationVector]`: por `event_time`, el vector de esa barra. |
| **alpha_score** | Score por fila (símbolo + barra), típicamente en [-1, 1]. Lo produce el modelo o la regla; la estrategia lo convierte en AllocationVector. |

---

## 10. Dónde está cada pieza en el repo

| Qué | Dónde |
|-----|--------|
| Cargar datos | `ai.data.loader.load_decision_features` |
| Modelo → alpha_score en filas | `ai.inference.model_scorer.enrich_rows_with_model` |
| Score → AllocationVector | `ai.allocation.strategies.compute_allocations` |
| Invariantes (I1, I2) | `ai.allocation.invariants.check_invariants`, `clamp_vector` |
| Normalización exposición | `ai.allocation.constraints.normalize_exposure` |
| Cierre de posición (reglas) | `ai.allocation.exit_rules` (`build_exit_rule`, `close_after_n_bars`, `close_on_stop_or_target`) |
| Risk overlay | `ai.allocation.risk.apply_risk_overlay`, `risk_overlay_from_config` |
| Ejecutar con vectores (simulación) | `ai.allocation.backtest.run_backtest_from_orders` |
| Script: JSON de vectores → resultado | `scripts.run_sim_from_orders` |

Tus modelos de AI te dirán “qué comprar” en cuanto su **output (score por símbolo) se traduzca en un AllocationVector** y ese vector sea el que uses en estrategias y compras (backtest u órdenes). Todo lo que ejecuta recibe siempre vectores.

---

## 11. Escalar a multi-horizon / multi-model ensemble (nota de diseño)

- **Multi-horizon:** Varios horizontes (1h, 4h, 24h) pueden producir cada uno un AllocationVector. Contrato: combinar por ponderación (ej. `a_final[s] = w1*a_1h[s] + w2*a_4h[s]`) y luego aplicar risk overlay y normalización. Los vectores siguen siendo el contrato; la combinación es una estrategia más.
- **Multi-model ensemble:** Varios modelos dan scores por símbolo; se pueden promediar o votar antes de score→vector, o producir un vector por modelo y promediar vectores (con clamp y normalize después). Misma idea: el output que llega a ejecución es siempre un único AllocationVector por barra que cumple invariantes y risk.
