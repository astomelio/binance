# Timeframes y Frecuencia de Decisiones

## 📊 Timeframes Disponibles

El sistema soporta múltiples timeframes para diferentes estrategias:

### 1. **1h (Horario)**
- **Frecuencia de decisiones**: Cada 1 hora
- **Uso**: Trading activo, scalping, captura de movimientos intraday
- **Forward returns calculados**:
  - `fwd_return_1h`: Retorno 1 hora adelante
  - `fwd_return_4h`: Retorno 4 horas adelante (4 pasos de 1h)
  - `fwd_return_24h`: Retorno 24 horas adelante (24 pasos de 1h)
- **Datos históricos**: ~78,837 filas (3 años)

### 2. **4h (Cuatro Horas)**
- **Frecuencia de decisiones**: Cada 4 horas
- **Uso**: Trading de medio plazo, menos ruido, más robusto
- **Forward returns calculados**:
  - `fwd_return_1h`: No aplica (intervalo base es 4h)
  - `fwd_return_4h`: Retorno 4 horas adelante (1 paso de 4h)
  - `fwd_return_24h`: Retorno 24 horas adelante (6 pasos de 4h)
- **Datos históricos**: ~19,710 filas (3 años)

### 3. **1d (Diario)**
- **Frecuencia de decisiones**: Diaria
- **Uso**: Swing trading, análisis de tendencias de largo plazo
- **Forward returns calculados**:
  - `fwd_return_1h`: No aplica
  - `fwd_return_4h`: No aplica
  - `fwd_return_24h`: Retorno 24 horas adelante (1 paso de 1d)
- **Datos históricos**: ~3,285 filas (3 años)

## 🎯 Cómo el Modelo Usa los Timeframes

### Modelo Actual (1h)
El modelo está configurado para usar datos de **1h** como base:

1. **Entrada de datos**: Cada hora, cuando hay nuevo kline
2. **Cálculo de features**: 
   - Momentum 3h: usa 3 pasos atrás (3 horas)
   - Momentum 12h: usa 12 pasos atrás (12 horas)
   - Forward returns: calcula retornos 1h, 4h, 24h adelante

3. **Decisión de trading**:
   - Evalúa señales cada hora
   - Puede entrar/salir en cualquier momento
   - Forward return objetivo: típicamente 4h (`fwd_return_4h`)

### Modelos por Timeframe (Futuro)
Para usar diferentes timeframes, necesitas:

1. **Entrenar modelos separados** por timeframe:
   ```bash
   # Modelo 1h
   python examples/quant_champion_challenger.py --data-path .../decision_features_backfill_1h --horizon 4h
   
   # Modelo 4h  
   python examples/quant_champion_challenger.py --data-path .../decision_features_backfill_4h --horizon 24h
   
   # Modelo 1d
   python examples/quant_champion_challenger.py --data-path .../decision_features_backfill_1d --horizon 24h
   ```

2. **Usar el timeframe apropiado** según estrategia:
   - **Scalping/Activo**: 1h
   - **Medio plazo**: 4h
   - **Swing/Largo plazo**: 1d

## 📈 Datos Históricos

### Fuente
Todos los datos vienen de **APIs reales de Binance**:
- `https://api.binance.com/api/v3/klines` (Spot)
- `https://fapi.binance.com/fapi/v1/klines` (Futures)
- `https://fapi.binance.com/fapi/v1/fundingRate` (Funding rates)
- `https://fapi.binance.com/futures/data/openInterestHist` (Open interest)

**NO HAY DATOS SINTÉTICOS**

### Período Histórico
- **Rango**: 2023-02-11 a 2026-02-10
- **Duración**: 1,095 días = **3.0 años**
- **Símbolos**: BTCUSDT, ETHUSDT, BNBUSDT

### Backfill
Para obtener más datos históricos:
```bash
# Backfill todos los timeframes (3 años)
make backfill-all-timeframes

# O manualmente
python data_platform/backfill_all_timeframes.py --days 1095 --intervals 1h 4h 1d
```

## 🔄 Frecuencia de Decisiones

| Timeframe | Decisión cada | Trades/día (máx) | Uso recomendado |
|-----------|---------------|------------------|------------------|
| 1h        | 1 hora        | 24               | Trading activo, scalping |
| 4h        | 4 horas       | 6                | Medio plazo, menos ruido |
| 1d        | 1 día         | 1                | Swing trading, largo plazo |

## 💡 Recomendaciones

1. **Para empezar**: Usa **1h** con forward return de **4h**
   - Buen balance entre frecuencia y robustez
   - Suficientes datos para entrenar

2. **Para menos ruido**: Usa **4h** con forward return de **24h**
   - Menos señales falsas
   - Más robusto a corto plazo

3. **Para swing trading**: Usa **1d** con forward return de **24h**
   - Menos trades, más calidad
   - Mejor para capital grande
