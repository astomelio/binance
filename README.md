# Binance Connector API

Un conector completo para la API de Binance construido con Chalice, un framework serverless para AWS Lambda.

## Características

- ✅ **Información de cuenta**: Obtener información de la cuenta y balances
- ✅ **Datos de mercado**: Tickers y datos de velas (klines)
- ✅ **Gestión de órdenes**: Crear, consultar y cancelar órdenes
- ✅ **Trading de Futuros**: Soporte completo para futuros con leverage y posiciones
- ✅ **Validación de datos**: Usando Pydantic para validación de requests
- ✅ **Manejo de errores**: Manejo robusto de errores de Binance
- ✅ **Testnet support**: Soporte para entorno de pruebas
- ✅ **Serverless**: Despliegue automático en AWS Lambda

## Instalación

### 1. Clonar el repositorio
```bash
git clone <tu-repositorio>
cd binance
```

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 3. Configurar variables de entorno
```bash
cp env.example .env
```

Edita el archivo `.env` con tus credenciales de Binance:
```env
BINANCE_API_KEY=tu_api_key_aqui
BINANCE_SECRET_KEY=tu_secret_key_aqui
BINANCE_TESTNET=true  # true para pruebas, false para producción
```

### 4. Instalar Chalice CLI (si no está instalado)
```bash
pip install chalice
```

## Uso Local

### Ejecutar en modo desarrollo
```bash
chalice local
```

La API estará disponible en `http://localhost:8000`

## Despliegue

### Desplegar a AWS Lambda
```bash
# Configurar AWS credentials primero
aws configure

# Desplegar a desarrollo
chalice deploy --stage dev

# Desplegar a producción
chalice deploy --stage prod
```

## Endpoints de la API

### Health Check
```http
GET /health
```

### SPOT TRADING

#### Información de Cuenta
```http
GET /account/info
```

#### Balance de Cuenta
```http
GET /account/balance
```

#### Ticker de Mercado
```http
GET /market/ticker/{symbol}
```
Ejemplo: `GET /market/ticker/BTCUSDT`

#### Datos de Velas (Klines)
```http
GET /market/klines/{symbol}?interval=1d&limit=100
```
Parámetros:
- `interval`: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M
- `limit`: Número de velas (máximo 1000)

#### Crear Orden Spot
```http
POST /order/create
Content-Type: application/json

{
  "symbol": "BTCUSDT",
  "side": "BUY",
  "order_type": "MARKET",
  "quantity": 0.001
}
```

#### Crear Orden Limit Inteligente (Anti-Slippage)
```http
POST /order/smart-limit
Content-Type: application/json

{
  "symbol": "BTCUSDT",
  "side": "BUY",
  "quantity": 0.001,
  "price_offset_percent": 0.1
}
```

#### Obtener Precio Óptimo para Limit Orders
```http
GET /order/optimal-price/{symbol}?side=BUY&price_offset_percent=0.1
```

#### Consultar Órdenes Spot
```http
GET /order/{symbol}?limit=10
```

#### Cancelar Orden Spot
```http
DELETE /order/{symbol}/{order_id}
```

### FUTURES TRADING

#### Información de Cuenta de Futuros
```http
GET /futures/account/info
```

#### Balance de Cuenta de Futuros
```http
GET /futures/account/balance
```

#### Posiciones de Futuros
```http
GET /futures/positions
```

#### Ticker de Futuros
```http
GET /futures/market/ticker/{symbol}
```

#### Datos de Velas de Futuros
```http
GET /futures/market/klines/{symbol}?interval=1d&limit=100
```

#### Crear Orden de Futuros
```http
POST /futures/order/create
Content-Type: application/json

{
  "symbol": "BTCUSDT",
  "side": "BUY",
  "order_type": "MARKET",
  "quantity": 0.001,
  "position_side": "LONG",
  "reduce_only": false,
  "close_position": false
}
```

#### Crear Orden Limit de Futuros Inteligente (Anti-Slippage)
```http
POST /futures/order/smart-limit
Content-Type: application/json

{
  "symbol": "BTCUSDT",
  "side": "BUY",
  "quantity": 0.001,
  "position_side": "LONG",
  "price_offset_percent": 0.1
}
```

#### Obtener Precio Óptimo para Limit Orders de Futuros
```http
GET /futures/order/optimal-price/{symbol}?side=BUY&price_offset_percent=0.1
```

#### Consultar Órdenes de Futuros
```http
GET /futures/order/{symbol}?limit=10
```

#### Cancelar Orden de Futuros
```http
DELETE /futures/order/{symbol}/{order_id}
```

#### Establecer Leverage
```http
POST /futures/leverage
Content-Type: application/json

{
  "symbol": "BTCUSDT",
  "leverage": 10
}
```

#### Establecer Tipo de Margen
```http
POST /futures/margin_type
Content-Type: application/json

{
  "symbol": "BTCUSDT",
  "margin_type": "ISOLATED"
}
```

## Ejemplos de Uso

### Obtener precio de Bitcoin (Spot)
```bash
curl http://localhost:8000/market/ticker/BTCUSDT
```

### Obtener precio de Bitcoin (Futuros)
```bash
curl http://localhost:8000/futures/market/ticker/BTCUSDT
```

### Crear orden de compra (Spot)
```bash
curl -X POST http://localhost:8000/order/create \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTCUSDT",
    "side": "BUY",
    "order_type": "MARKET",
    "quantity": 0.001
  }'
```

### Crear orden limit inteligente (Anti-Slippage)
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

### Obtener precio óptimo para limit orders
```bash
curl "http://localhost:8000/order/optimal-price/BTCUSDT?side=BUY&price_offset_percent=0.1"
```

### Crear orden de compra (Futuros)
```bash
curl -X POST http://localhost:8000/futures/order/create \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTCUSDT",
    "side": "BUY",
    "order_type": "MARKET",
    "quantity": 0.001,
    "position_side": "LONG"
  }'
```

### Crear orden limit de futuros inteligente (Anti-Slippage)
```bash
curl -X POST http://localhost:8000/futures/order/smart-limit \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTCUSDT",
    "side": "BUY",
    "quantity": 0.001,
    "position_side": "LONG",
    "price_offset_percent": 0.1
  }'
```

### Obtener balance de cuenta (Spot)
```bash
curl http://localhost:8000/account/balance
```

### Obtener balance de cuenta (Futuros)
```bash
curl http://localhost:8000/futures/account/balance
```

### Obtener posiciones de futuros
```bash
curl http://localhost:8000/futures/positions
```

### Establecer leverage
```bash
curl -X POST http://localhost:8000/futures/leverage \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTCUSDT",
    "leverage": 10
  }'
```

## Configuración de Binance

### 1. Crear cuenta en Binance
Ve a [binance.com](https://binance.com) y crea una cuenta.

### 2. Generar API Keys
1. Ve a tu perfil → API Management
2. Crea una nueva API key
3. Guarda la API Key y Secret Key

### 3. Configurar permisos
Para el conector, necesitas los siguientes permisos:
- ✅ Spot & Margin Trading
- ✅ Futures (para trading de futuros)
- ✅ Reading
- ❌ Withdraw (no recomendado para seguridad)

### 4. Testnet (Recomendado para pruebas)
Para pruebas, usa el testnet de Binance:
1. Ve a [testnet.binance.vision](https://testnet.binance.vision/)
2. Crea una cuenta de prueba
3. Genera API keys de prueba
4. Configura `BINANCE_TESTNET=true` en tu `.env`

## Diferencias entre Spot y Futuros

### Spot Trading
- ✅ Compra y venta directa de activos
- ✅ Sin leverage (1:1)
- ✅ Menor riesgo
- ✅ Ideal para principiantes
- ❌ No puedes hacer short fácilmente
- ❌ No puedes usar leverage

### Futures Trading
- ✅ Puedes hacer long y short
- ✅ Leverage disponible (hasta 125x)
- ✅ Más oportunidades de trading
- ✅ Hedging y arbitraje
- ⚠️ **ALTO RIESGO** - Puedes perder más de tu inversión
- ⚠️ Solo para traders experimentados

## Órdenes Limit Inteligentes (Anti-Slippage)

### ¿Por qué usar órdenes limit en lugar de market?

#### Market Orders (NO RECOMENDADO)
- ❌ **Slippage alto** - Puedes pagar más del precio esperado
- ❌ **Fees más altos** - Taker fees son más caros
- ❌ **Sin control de precio** - No sabes el precio exacto de ejecución
- ❌ **Impacto en el mercado** - Pueden mover el precio

#### Limit Orders Inteligentes (RECOMENDADO)
- ✅ **Sin slippage** - Precio fijo y predecible
- ✅ **Fees más bajos** - Maker fees son más baratos
- ✅ **Control total** - Sabes exactamente el precio
- ✅ **Análisis del order book** - Precio óptimo calculado automáticamente
- ✅ **Configuración automática** - Offset configurable para mejor ejecución

### Cómo funcionan las órdenes limit inteligentes:

1. **Análisis del Order Book**: Consulta las mejores ofertas/compra en tiempo real
2. **Cálculo de Precio Óptimo**: 
   - Para compras: Precio ask + offset configurable
   - Para ventas: Precio bid - offset configurable
3. **Creación de Limit Order**: Orden con precio óptimo calculado
4. **Ejecución Inteligente**: Mejor probabilidad de ejecución sin slippage

### Parámetros configurables:
- `price_offset_percent`: Porcentaje de offset del precio de mercado (default: 0.1%)
- `side`: BUY o SELL
- `quantity`: Cantidad a comprar/vender
- `position_side`: LONG o SHORT (solo futuros)

## Estructura del Proyecto

```
binance/
├── app.py              # Aplicación principal de Chalice
├── chalice.json        # Configuración de Chalice
├── requirements.txt    # Dependencias de Python
├── env.example        # Ejemplo de variables de entorno
├── examples/          # Ejemplos de uso
│   └── basic_usage.py # Cliente de ejemplo
├── tests/             # Tests unitarios
│   └── test_app.py    # Tests de la aplicación
├── Dockerfile         # Configuración de Docker
├── docker-compose.yml # Docker Compose
├── Makefile           # Comandos útiles
├── setup.sh           # Script de configuración
└── README.md          # Este archivo
```

## Seguridad

### Variables de Entorno
- Nunca commits tus API keys al repositorio
- Usa `.env` para variables locales
- Usa AWS Systems Manager Parameter Store para producción

### Permisos de API
- Usa solo los permisos necesarios
- No habilites "Withdraw" a menos que sea absolutamente necesario
- Usa IP whitelist si es posible

### Testnet
- Siempre prueba en testnet primero
- El testnet usa fondos virtuales
- Perfecto para desarrollo y pruebas

### ⚠️ Advertencias sobre Futuros
- **FUTUROS SON DE ALTO RIESGO**
- Puedes perder más de tu inversión inicial
- Solo para traders experimentados
- Siempre usa stop-loss
- Nunca inviertas más de lo que puedes perder
- Prueba primero en testnet

## Troubleshooting

### Error: "BINANCE_API_KEY and BINANCE_SECRET_KEY must be set"
- Verifica que tu archivo `.env` esté configurado correctamente
- Asegúrate de que las variables estén en el formato correcto

### Error: "Invalid API key"
- Verifica que tu API key sea correcta
- Asegúrate de que la API key tenga los permisos necesarios
- Si usas testnet, asegúrate de usar las keys del testnet

### Error: "Insufficient balance"
- Verifica tu balance en Binance
- Para testnet, obtén fondos de prueba en testnet.binance.vision

### Error: "Futures trading not enabled"
- Asegúrate de que tu cuenta tenga habilitado el trading de futuros
- Verifica que tu API key tenga permisos de futuros

### Error: "Leverage not allowed"
- Algunos símbolos tienen límites de leverage
- Verifica los límites en la documentación de Binance

## Contribuir

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## Licencia

Este proyecto está bajo la Licencia MIT. Ver el archivo `LICENSE` para más detalles.

## Soporte

Si tienes problemas o preguntas:
1. Revisa la documentación de [Binance API](https://binance-docs.github.io/apidocs/spot/en/)
2. Revisa la documentación de [Binance Futures API](https://binance-docs.github.io/apidocs/futures/en/)
3. Revisa la documentación de [Chalice](https://aws.github.io/chalice/)
4. Abre un issue en este repositorio
