# 🚀 Guía Rápida - Conector de Binance

## Configuración Rápida para Pruebas Locales

### 1. Configuración Automática (RECOMENDADO)

```bash
# Ejecutar el script de configuración automática
python setup_local.py
```

El script te guiará paso a paso para:
- ✅ Instalar dependencias
- ✅ Configurar API keys
- ✅ Probar conexión
- ✅ Ejecutar servidor local

### 2. Configuración Manual

#### Paso 1: Crear archivo .env
```bash
cp env.example .env
```

#### Paso 2: Editar .env con tus API keys
```env
BINANCE_API_KEY=tu_api_key_aqui
BINANCE_SECRET_KEY=tu_secret_key_aqui
BINANCE_TESTNET=true  # true para pruebas, false para producción
```

#### Paso 3: Instalar dependencias
```bash
pip install -r requirements.txt
```

#### Paso 4: Ejecutar servidor
```bash
chalice local
```

## 🔑 Obtener API Keys

### Para Pruebas (RECOMENDADO)
1. Ve a [testnet.binance.vision](https://testnet.binance.vision/)
2. Crea una cuenta de prueba
3. Genera API keys de prueba
4. Configura `BINANCE_TESTNET=true` en tu `.env`

### Para Producción
1. Ve a [binance.com](https://binance.com)
2. Ve a Profile → API Management
3. Crea una nueva API key
4. Configura permisos:
   - ✅ Spot & Margin Trading
   - ✅ Futures (para futuros)
   - ✅ Reading
   - ❌ Withdraw (no recomendado)

## 🧪 Probar la API

### Health Check
```bash
curl http://localhost:8000/health
```

### Obtener Precio de Bitcoin
```bash
curl http://localhost:8000/market/ticker/BTCUSDT
```

### Obtener Precio Óptimo (Anti-Slippage)
```bash
curl "http://localhost:8000/order/optimal-price/BTCUSDT?side=BUY&price_offset_percent=0.1"
```

### Crear Orden Limit Inteligente
```bash
curl -X POST http://localhost:8000/order/smart-limit \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTCUSDT",
    "side": "BUY",
    "quantity": 0.001,
    "price_offset_percent": 0.1
  }'
```

## 📋 Comandos Útiles

```bash
# Ejecutar servidor
chalice local

# Ejecutar tests
make test

# Ver todos los comandos
make help

# Limpiar archivos temporales
make clean
```

## 🔧 Troubleshooting

### Error: "BINANCE_API_KEY and BINANCE_SECRET_KEY must be set"
- Verifica que tu archivo `.env` esté configurado
- Asegúrate de que las variables estén en el formato correcto

### Error: "Invalid API key"
- Verifica que tu API key sea correcta
- Asegúrate de que tenga los permisos necesarios
- Si usas testnet, verifica que las keys sean del testnet

### Error: "Futures trading not enabled"
- Asegúrate de que tu cuenta tenga habilitado el trading de futuros
- Verifica que tu API key tenga permisos de futuros

## 📚 Documentación Completa

Para más detalles, consulta el [README.md](README.md) completo.

## 🎯 Endpoints Principales

### Spot Trading
- `GET /health` - Health check
- `GET /account/balance` - Balance de cuenta
- `GET /market/ticker/{symbol}` - Precio de mercado
- `POST /order/smart-limit` - Orden limit inteligente (anti-slippage)
- `GET /order/optimal-price/{symbol}` - Precio óptimo para limit orders

### Futures Trading
- `GET /futures/account/balance` - Balance de futuros
- `GET /futures/positions` - Posiciones activas
- `POST /futures/order/smart-limit` - Orden limit de futuros inteligente
- `GET /futures/order/optimal-price/{symbol}` - Precio óptimo de futuros

## ⚠️ Advertencias

- **Siempre prueba primero en testnet**
- **Futuros son de alto riesgo**
- **Usa órdenes limit para evitar slippage**
- **Nunca inviertas más de lo que puedes perder**
