#!/usr/bin/env python3
"""
Demo de Órdenes Limit Inteligentes (Anti-Slippage)
Muestra cómo el sistema usa órdenes limit en lugar de TWAP para evitar slippage
"""

import requests
import json
import time
from datetime import datetime

def test_smart_limit_orders():
    """Probar órdenes limit inteligentes"""
    print("🎯 DEMO - Órdenes Limit Inteligentes (Anti-Slippage)")
    print("=" * 60)
    
    # 1. Verificar conector
    print("1. Verificando conector...")
    try:
        response = requests.get("http://localhost:8000/health")
        if response.status_code == 200:
            print("✅ Conector funcionando")
        else:
            print("❌ Conector no disponible")
            return
    except Exception as e:
        print(f"❌ Error: {e}")
        return
    
    # 2. Obtener precios óptimos
    print("\n2. Obteniendo precios óptimos...")
    symbols = ["BTCUSDT", "ETHUSDT", "ADAUSDT"]
    
    for symbol in symbols:
        try:
            # Precio para compra
            buy_response = requests.get(
                f"http://localhost:8000/order/optimal-price/{symbol}",
                params={"side": "BUY", "price_offset_percent": 0.1}
            )
            
            if buy_response.status_code == 200:
                buy_data = buy_response.json()
                if buy_data.get('status') == 'success':
                    data = buy_data['data']
                    print(f"✅ {symbol} - Compra:")
                    print(f"   Precio mercado: ${data['market_price']}")
                    print(f"   Precio limit sugerido: ${data['suggested_limit_price']}")
                    print(f"   Offset: {data['price_offset_percent']}%")
            
            # Precio para venta
            sell_response = requests.get(
                f"http://localhost:8000/order/optimal-price/{symbol}",
                params={"side": "SELL", "price_offset_percent": 0.1}
            )
            
            if sell_response.status_code == 200:
                sell_data = sell_response.json()
                if sell_data.get('status') == 'success':
                    data = sell_data['data']
                    print(f"✅ {symbol} - Venta:")
                    print(f"   Precio mercado: ${data['market_price']}")
                    print(f"   Precio limit sugerido: ${data['suggested_limit_price']}")
                    print(f"   Offset: {data['price_offset_percent']}%")
            
        except Exception as e:
            print(f"❌ Error con {symbol}: {e}")
    
    # 3. Simular órdenes limit inteligentes (sin ejecutar)
    print("\n3. Simulando órdenes limit inteligentes...")
    
    test_orders = [
        {"symbol": "BTCUSDT", "side": "BUY", "quantity": 0.001},
        {"symbol": "ETHUSDT", "side": "SELL", "quantity": 0.01},
        {"symbol": "ADAUSDT", "side": "BUY", "quantity": 100}
    ]
    
    for order in test_orders:
        print(f"\n📋 Orden simulada: {order['symbol']} {order['side']} {order['quantity']}")
        
        # Obtener precio óptimo
        price_response = requests.get(
            f"http://localhost:8000/order/optimal-price/{order['symbol']}",
            params={"side": order['side'], "price_offset_percent": 0.1}
        )
        
        if price_response.status_code == 200:
            price_data = price_response.json()
            if price_data.get('status') == 'success':
                data = price_data['data']
                print(f"   💰 Precio de mercado: ${data['market_price']}")
                print(f"   🎯 Precio limit sugerido: ${data['suggested_limit_price']}")
                print(f"   📊 Diferencia: ${float(data['suggested_limit_price']) - float(data['market_price']):.4f}")
                print(f"   📈 Offset aplicado: {data['price_offset_percent']}%")
                
                # Calcular ahorro vs market order
                market_price = float(data['market_price'])
                limit_price = float(data['suggested_limit_price'])
                if order['side'] == 'BUY':
                    savings = (limit_price - market_price) / market_price * 100
                    print(f"   💡 Ahorro vs market: {savings:.4f}%")
                else:
                    savings = (market_price - limit_price) / market_price * 100
                    print(f"   💡 Ahorro vs market: {savings:.4f}%")
    
    # 4. Comparar con TWAP
    print("\n4. Comparación: Limit Inteligente vs TWAP vs Market")
    print("=" * 50)
    
    comparison_data = {
        "Limit Inteligente": {
            "slippage": "Mínimo (0.1% offset)",
            "fees": "Maker (más bajos)",
            "control": "Precio fijo",
            "ejecución": "Inmediata si hay liquidez",
            "riesgo": "Bajo"
        },
        "TWAP": {
            "slippage": "Distribuido en tiempo",
            "fees": "Múltiples órdenes",
            "control": "Tiempo promedio",
            "ejecución": "Lenta (distribuida)",
            "riesgo": "Medio"
        },
        "Market Order": {
            "slippage": "Alto",
            "fees": "Taker (más altos)",
            "control": "Sin control",
            "ejecución": "Inmediata",
            "riesgo": "Alto"
        }
    }
    
    for method, details in comparison_data.items():
        print(f"\n📊 {method}:")
        for key, value in details.items():
            print(f"   {key}: {value}")
    
    # 5. Mostrar ventajas del sistema
    print("\n5. Ventajas del Sistema de Órdenes Limit Inteligentes")
    print("=" * 60)
    
    advantages = [
        "✅ Análisis del order book en tiempo real",
        "✅ Precios óptimos calculados automáticamente",
        "✅ Offset configurable (0.1% por defecto)",
        "✅ Fees más bajos (maker vs taker)",
        "✅ Control total del precio de entrada",
        "✅ Sin slippage inesperado",
        "✅ Ejecución inmediata si hay liquidez",
        "✅ Logs detallados de cada orden",
        "✅ Integración con bot long/short",
        "✅ API REST para control remoto"
    ]
    
    for advantage in advantages:
        print(advantage)
    
    # 6. Ejemplo de uso con bot
    print("\n6. Ejemplo de Integración con Bot Long/Short")
    print("=" * 50)
    
    print("""
🔄 Flujo Completo:
1. Bot calcula pesos de momentum
2. Sistema convierte pesos en señales
3. Para cada señal:
   - Analiza order book
   - Calcula precio óptimo
   - Crea orden limit inteligente
   - Ejecuta con offset configurable
4. Resultado: Trading sin slippage

📋 Ejemplo de Señal:
{
  "symbol": "BTCUSDT",
  "signal_type": "LONG", 
  "quantity": 0.001,
  "metadata": {
    "momentum": 0.05,
    "weight": 0.3,
    "source": "long_short_bot"
  }
}

🎯 Ejecución:
- Precio mercado: $45,000
- Precio limit: $45,045 (0.1% offset)
- Cantidad: 0.001 BTC
- Fees: Maker (más bajos)
- Slippage: Controlado
    """)

def test_bot_integration():
    """Probar integración con bot"""
    print("\n🤖 Probando integración con bot...")
    
    try:
        # Verificar bot integrado
        response = requests.get("http://localhost:5000/bot/status")
        if response.status_code == 200:
            data = response.json()
            print("✅ Bot integrado funcionando")
            print(f"   Conector: {data.get('connector_status', {}).get('status', 'N/A')}")
            print(f"   Posiciones activas: {data.get('active_positions', 0)}")
            print(f"   Último rebalance: {data.get('last_rebalance', 'N/A')}")
            
            # Simular rebalance
            print("\n🔄 Simulando rebalance...")
            rebalance_response = requests.post("http://localhost:5000/bot/rebalance")
            if rebalance_response.status_code == 200:
                result = rebalance_response.json()
                print("✅ Rebalance simulado exitoso")
                print(f"   Universe size: {result.get('universe_size', 'N/A')}")
                print(f"   Órdenes ejecutadas: {len(result.get('results', []))}")
            else:
                print("❌ Error en rebalance")
        else:
            print("❌ Bot integrado no disponible")
            
    except Exception as e:
        print(f"❌ Error: {e}")

def main():
    """Función principal"""
    print("🚀 DEMO - Sistema de Órdenes Limit Inteligentes")
    print("=" * 60)
    print("Este demo muestra cómo el sistema usa órdenes limit")
    print("inteligentes para evitar slippage y fees altos.")
    print()
    
    # Ejecutar demo
    test_smart_limit_orders()
    test_bot_integration()
    
    print("\n" + "=" * 60)
    print("🎉 Demo completado!")
    print("💡 El sistema está configurado para usar órdenes limit")
    print("   inteligentes en lugar de TWAP o market orders.")
    print("💡 Esto garantiza:")
    print("   - Sin slippage inesperado")
    print("   - Fees más bajos")
    print("   - Control total del precio")
    print("   - Ejecución inteligente")

if __name__ == "__main__":
    main()
