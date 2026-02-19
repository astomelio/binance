#!/usr/bin/env python3
"""
Ejemplo básico de uso del Conector de Binance
Este script muestra cómo usar la API del conector para operaciones básicas
"""

import requests
import json
import time
from typing import Dict, Any

class BinanceConnectorClient:
    """Cliente para interactuar con el Conector de Binance"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
    
    def _make_request(self, method: str, endpoint: str, data: Dict = None) -> Dict[str, Any]:
        """Realizar una petición HTTP al conector"""
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url)
            elif method.upper() == 'POST':
                response = requests.post(url, json=data)
            elif method.upper() == 'DELETE':
                response = requests.delete(url)
            else:
                raise ValueError(f"Método HTTP no soportado: {method}")
            
            response.raise_for_status()
            return response.json()
        
        except requests.exceptions.RequestException as e:
            print(f"Error en la petición HTTP: {e}")
            return {"error": str(e)}
    
    # ============================================================================
    # SPOT TRADING METHODS
    # ============================================================================
    
    def health_check(self) -> Dict[str, Any]:
        """Verificar el estado del servicio"""
        return self._make_request('GET', '/health')
    
    def get_account_info(self) -> Dict[str, Any]:
        """Obtener información de la cuenta"""
        return self._make_request('GET', '/account/info')
    
    def get_account_balance(self) -> Dict[str, Any]:
        """Obtener balance de la cuenta"""
        return self._make_request('GET', '/account/balance')
    
    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """Obtener ticker de un símbolo"""
        return self._make_request('GET', f'/market/ticker/{symbol}')
    
    def get_klines(self, symbol: str, interval: str = '1d', limit: int = 100) -> Dict[str, Any]:
        """Obtener datos de velas (klines)"""
        endpoint = f'/market/klines/{symbol}?interval={interval}&limit={limit}'
        return self._make_request('GET', endpoint)
    
    def create_order(self, symbol: str, side: str, order_type: str, 
                    quantity: float = None, price: float = None) -> Dict[str, Any]:
        """Crear una orden spot"""
        data = {
            'symbol': symbol,
            'side': side,
            'order_type': order_type
        }
        
        if quantity:
            data['quantity'] = quantity
        if price:
            data['price'] = price
        
        return self._make_request('POST', '/order/create', data)
    
    def get_orders(self, symbol: str, limit: int = 10) -> Dict[str, Any]:
        """Obtener órdenes spot de un símbolo"""
        endpoint = f'/order/{symbol}?limit={limit}'
        return self._make_request('GET', endpoint)
    
    def cancel_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        """Cancelar una orden spot"""
        return self._make_request('DELETE', f'/order/{symbol}/{order_id}')
    
    # ============================================================================
    # FUTURES TRADING METHODS
    # ============================================================================
    
    def get_futures_account_info(self) -> Dict[str, Any]:
        """Obtener información de la cuenta de futuros"""
        return self._make_request('GET', '/futures/account/info')
    
    def get_futures_account_balance(self) -> Dict[str, Any]:
        """Obtener balance de la cuenta de futuros"""
        return self._make_request('GET', '/futures/account/balance')
    
    def get_futures_positions(self) -> Dict[str, Any]:
        """Obtener posiciones de futuros"""
        return self._make_request('GET', '/futures/positions')
    
    def get_futures_ticker(self, symbol: str) -> Dict[str, Any]:
        """Obtener ticker de futuros de un símbolo"""
        return self._make_request('GET', f'/futures/market/ticker/{symbol}')
    
    def get_futures_klines(self, symbol: str, interval: str = '1d', limit: int = 100) -> Dict[str, Any]:
        """Obtener datos de velas de futuros (klines)"""
        endpoint = f'/futures/market/klines/{symbol}?interval={interval}&limit={limit}'
        return self._make_request('GET', endpoint)
    
    def create_futures_order(self, symbol: str, side: str, order_type: str, 
                           quantity: float = None, price: float = None,
                           position_side: str = None, reduce_only: bool = False,
                           close_position: bool = False) -> Dict[str, Any]:
        """Crear una orden de futuros"""
        data = {
            'symbol': symbol,
            'side': side,
            'order_type': order_type
        }
        
        if quantity:
            data['quantity'] = quantity
        if price:
            data['price'] = price
        if position_side:
            data['position_side'] = position_side
        if reduce_only is not None:
            data['reduce_only'] = reduce_only
        if close_position is not None:
            data['close_position'] = close_position
        
        return self._make_request('POST', '/futures/order/create', data)
    
    def get_futures_orders(self, symbol: str, limit: int = 10) -> Dict[str, Any]:
        """Obtener órdenes de futuros de un símbolo"""
        endpoint = f'/futures/order/{symbol}?limit={limit}'
        return self._make_request('GET', endpoint)
    
    def cancel_futures_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        """Cancelar una orden de futuros"""
        return self._make_request('DELETE', f'/futures/order/{symbol}/{order_id}')
    
    def set_futures_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        """Establecer leverage para un símbolo de futuros"""
        data = {
            'symbol': symbol,
            'leverage': leverage
        }
        return self._make_request('POST', '/futures/leverage', data)
    
    def set_futures_margin_type(self, symbol: str, margin_type: str) -> Dict[str, Any]:
        """Establecer tipo de margen para un símbolo de futuros"""
        data = {
            'symbol': symbol,
            'margin_type': margin_type  # ISOLATED or CROSSED
        }
        return self._make_request('POST', '/futures/margin_type', data)
    
    # ============================================================================
    # SMART LIMIT ORDERS (Anti-Slippage)
    # ============================================================================
    
    def create_smart_limit_order(self, symbol: str, side: str, quantity: float, 
                               price_offset_percent: float = 0.1) -> Dict[str, Any]:
        """Crear una orden limit inteligente que evita slippage"""
        data = {
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'price_offset_percent': price_offset_percent
        }
        return self._make_request('POST', '/order/smart-limit', data)
    
    def create_smart_futures_limit_order(self, symbol: str, side: str, quantity: float,
                                       position_side: str = None, 
                                       price_offset_percent: float = 0.1) -> Dict[str, Any]:
        """Crear una orden limit de futuros inteligente que evita slippage"""
        data = {
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'price_offset_percent': price_offset_percent
        }
        if position_side:
            data['position_side'] = position_side
        
        return self._make_request('POST', '/futures/order/smart-limit', data)
    
    def get_optimal_price(self, symbol: str, side: str = 'BUY', 
                         price_offset_percent: float = 0.1) -> Dict[str, Any]:
        """Obtener precio óptimo para órdenes limit (spot)"""
        endpoint = f'/order/optimal-price/{symbol}?side={side}&price_offset_percent={price_offset_percent}'
        return self._make_request('GET', endpoint)
    
    def get_futures_optimal_price(self, symbol: str, side: str = 'BUY',
                                 price_offset_percent: float = 0.1) -> Dict[str, Any]:
        """Obtener precio óptimo para órdenes limit de futuros"""
        endpoint = f'/futures/order/optimal-price/{symbol}?side={side}&price_offset_percent={price_offset_percent}'
        return self._make_request('GET', endpoint)

def print_response(title: str, response: Dict[str, Any]):
    """Imprimir una respuesta de forma formateada"""
    print(f"\n{'='*50}")
    print(f"{title}")
    print(f"{'='*50}")
    print(json.dumps(response, indent=2, ensure_ascii=False))

def main():
    """Función principal con ejemplos de uso"""
    print("🚀 Conector de Binance - Ejemplos de Uso")
    print("Asegúrate de que el servidor esté ejecutándose con: chalice local")
    
    # Crear cliente
    client = BinanceConnectorClient()
    
    # 1. Health Check
    print_response("1. Health Check", client.health_check())
    
    # 2. Información de cuenta spot
    print_response("2. Información de Cuenta Spot", client.get_account_info())
    
    # 3. Balance de cuenta spot
    print_response("3. Balance de Cuenta Spot", client.get_account_balance())
    
    # 4. Ticker de Bitcoin spot
    print_response("4. Ticker de Bitcoin Spot (BTCUSDT)", client.get_ticker("BTCUSDT"))
    
    # 5. Datos de velas de Bitcoin spot (últimas 5 velas diarias)
    print_response("5. Datos de Velas de Bitcoin Spot (5 días)", 
                  client.get_klines("BTCUSDT", interval="1d", limit=5))
    
    # 6. Información de cuenta de futuros
    print_response("6. Información de Cuenta de Futuros", client.get_futures_account_info())
    
    # 7. Balance de cuenta de futuros
    print_response("7. Balance de Cuenta de Futuros", client.get_futures_account_balance())
    
    # 8. Posiciones de futuros
    print_response("8. Posiciones de Futuros", client.get_futures_positions())
    
    # 9. Ticker de Bitcoin futuros
    print_response("9. Ticker de Bitcoin Futuros (BTCUSDT)", client.get_futures_ticker("BTCUSDT"))
    
    # 10. Datos de velas de Bitcoin futuros
    print_response("10. Datos de Velas de Bitcoin Futuros (5 días)", 
                  client.get_futures_klines("BTCUSDT", interval="1d", limit=5))
    
    # 11. Órdenes recientes spot (si existen)
    print_response("11. Órdenes Recientes Spot de BTCUSDT", client.get_orders("BTCUSDT", limit=5))
    
    # 12. Órdenes recientes futuros (si existen)
    print_response("12. Órdenes Recientes Futuros de BTCUSDT", client.get_futures_orders("BTCUSDT", limit=5))
    
    # 13. Precio óptimo para órdenes limit (spot)
    print_response("13. Precio Óptimo para Compra BTCUSDT (Spot)", 
                  client.get_optimal_price("BTCUSDT", side="BUY", price_offset_percent=0.1))
    
    # 14. Precio óptimo para órdenes limit (futuros)
    print_response("14. Precio Óptimo para Compra BTCUSDT (Futuros)", 
                  client.get_futures_optimal_price("BTCUSDT", side="BUY", price_offset_percent=0.1))
    
    print("\n" + "="*50)
    print("✅ Ejemplos completados!")
    print("💡 Para crear órdenes reales, asegúrate de:")
    print("   - Tener fondos en tu cuenta")
    print("   - Usar el testnet para pruebas")
    print("   - Verificar los precios antes de operar")
    print("   - Entender los riesgos de futuros antes de operar")
    print("   - Usar órdenes limit para evitar slippage y fees altos")

def example_smart_limit_orders():
    """Ejemplo de órdenes limit inteligentes para evitar slippage"""
    print("\n🎯 Ejemplo de Órdenes Limit Inteligentes")
    print("💡 Estas órdenes evitan slippage y fees altos de market orders")
    
    client = BinanceConnectorClient()
    
    # 1. Obtener precio óptimo para compra
    optimal_buy = client.get_optimal_price("BTCUSDT", side="BUY", price_offset_percent=0.1)
    if optimal_buy.get('status') == 'success':
        data = optimal_buy['data']
        print(f"💰 Precio de mercado: ${data['market_price']}")
        print(f"🎯 Precio sugerido para limit: ${data['suggested_limit_price']}")
        print(f"📊 Offset aplicado: {data['price_offset_percent']}%")
    
    # 2. Obtener precio óptimo para venta
    optimal_sell = client.get_optimal_price("BTCUSDT", side="SELL", price_offset_percent=0.1)
    if optimal_sell.get('status') == 'success':
        data = optimal_sell['data']
        print(f"💰 Precio de mercado: ${data['market_price']}")
        print(f"🎯 Precio sugerido para limit: ${data['suggested_limit_price']}")
        print(f"📊 Offset aplicado: {data['price_offset_percent']}%")
    
    # 3. Simular creación de orden limit inteligente (comentado por seguridad)
    """
    # Solo descomenta si quieres probar órdenes reales
    smart_order = client.create_smart_limit_order(
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.001,
        price_offset_percent=0.1  # 0.1% por encima del ask
    )
    print_response("Orden Limit Inteligente Creada", smart_order)
    """
    
    # 4. Simular creación de orden limit de futuros inteligente (comentado por seguridad)
    """
    # Solo descomenta si quieres probar órdenes reales
    # ⚠️ MUY PELIGROSO - Solo para traders experimentados
    smart_futures_order = client.create_smart_futures_limit_order(
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.001,
        position_side="LONG",
        price_offset_percent=0.1
    )
    print_response("Orden Limit de Futuros Inteligente Creada", smart_futures_order)
    """
    
    print("\n💡 Ventajas de las órdenes limit inteligentes:")
    print("   ✅ Evitan slippage (deslizamiento de precio)")
    print("   ✅ Fees más bajos que market orders")
    print("   ✅ Mejor control del precio de entrada")
    print("   ✅ Análisis del order book en tiempo real")
    print("   ✅ Configuración automática del precio óptimo")

def example_spot_vs_futures_comparison():
    """Comparar datos de spot vs futuros"""
    print("\n📊 Comparación Spot vs Futuros")
    
    client = BinanceConnectorClient()
    
    # Comparar precios
    spot_ticker = client.get_ticker("BTCUSDT")
    futures_ticker = client.get_futures_ticker("BTCUSDT")
    
    if spot_ticker.get('status') == 'success' and futures_ticker.get('status') == 'success':
        spot_price = float(spot_ticker['data']['last_price'])
        futures_price = float(futures_ticker['data']['last_price'])
        
        print(f"💰 Precio Spot: ${spot_price}")
        print(f"📈 Precio Futuros: ${futures_price}")
        print(f"📊 Diferencia: ${futures_price - spot_price:.2f}")
        print(f"📊 Spread: {((futures_price - spot_price) / spot_price * 100):.4f}%")

if __name__ == "__main__":
    try:
        main()
        example_smart_limit_orders()
        example_spot_vs_futures_comparison()
    except KeyboardInterrupt:
        print("\n👋 ¡Hasta luego!")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("💡 Asegúrate de que el servidor esté ejecutándose con: chalice local")
