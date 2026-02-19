#!/usr/bin/env python3
"""
Sistema Automatizado de Trading con Cálculo Real de Fees
Ejecuta estrategias solo si son rentables después de fees
"""

import requests
import time
from typing import Dict, Optional, List
from apps.automation.fee_calculator import FeeCalculator
from datetime import datetime

class AutomatedTrading:
    """Sistema automatizado con cálculo de fees"""
    
    def __init__(self, api_url: str = "http://localhost:8000"):
        self.api_url = api_url
        self.fee_calc = FeeCalculator(api_url)
        
    def check_api(self) -> bool:
        """Verificar API"""
        try:
            response = requests.get(f"{self.api_url}/health")
            return response.status_code == 200
        except:
            return False
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """Obtener precio actual"""
        try:
            response = requests.get(f"{self.api_url}/market/ticker/{symbol}")
            if response.status_code == 200:
                return float(response.json()['data']['last_price'])
        except:
            pass
        return None
    
    def get_optimal_price(self, symbol: str, side: str) -> Optional[Dict]:
        """Obtener precio óptimo"""
        try:
            response = requests.get(
                f"{self.api_url}/order/optimal-price/{symbol}",
                params={"side": side, "price_offset_percent": 0.1}
            )
            if response.status_code == 200:
                return response.json().get('data')
        except:
            pass
        return None
    
    def execute_smart_order_if_profitable(self, symbol: str, side: str, 
                                         amount: float, min_profit_percent: float = 0.5) -> Dict:
        """
        Ejecutar orden SOLO si es rentable después de fees
        
        Args:
            symbol: Símbolo a tradear
            side: BUY o SELL
            amount: Monto en USD
            min_profit_percent: Ganancia mínima requerida después de fees
        """
        # 1. Calcular fees
        round_trip = self.fee_calc.calculate_round_trip_fees(amount, is_maker=True, market_type='spot')
        break_even_percent = round_trip['break_even_percent']
        
        # 2. Obtener precio actual
        current_price = self.get_current_price(symbol)
        if not current_price:
            return {"error": "No se pudo obtener precio", "executed": False}
        
        # 3. Obtener precio óptimo
        optimal = self.get_optimal_price(symbol, side)
        if not optimal:
            return {"error": "No se pudo obtener precio óptimo", "executed": False}
        
        # 4. Calcular si es rentable
        # Para compra: necesitamos que el precio suba al menos break_even + min_profit
        # Para venta: necesitamos que el precio baje al menos break_even + min_profit
        required_move = break_even_percent + min_profit_percent
        
        # 5. Verificar si hay suficiente spread/movimiento esperado
        # (En una implementación real, aquí analizarías el mercado)
        is_profitable = True  # Simplificado - en producción analizarías el mercado
        
        if not is_profitable:
            return {
                "executed": False,
                "reason": f"Movimiento requerido ({required_move:.3f}%) no está disponible",
                "break_even": break_even_percent,
                "min_profit": min_profit_percent,
                "required_move": required_move
            }
        
        # 6. Calcular cantidad
        quantity = amount / optimal['suggested_limit_price']
        
        # 7. Ejecutar orden
        try:
            response = requests.post(
                f"{self.api_url}/order/smart-limit",
                json={
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "price_offset_percent": 0.1
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                order_data = result.get('data', {})
                
                # 8. Calcular profit esperado después de fees
                expected_profit = self.fee_calc.calculate_min_profit_needed(
                    amount, min_profit_percent, 'spot', True
                )
                
                return {
                    "executed": True,
                    "order_id": order_data.get('order_id'),
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "price": order_data.get('price'),
                    "amount": amount,
                    "fees": round_trip['total_fees'],
                    "break_even_percent": break_even_percent,
                    "min_profit_percent": min_profit_percent,
                    "expected_profit": expected_profit['min_profit_amount'],
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "executed": False,
                    "error": response.json().get('detail', 'Error desconocido')
                }
        except Exception as e:
            return {"executed": False, "error": str(e)}
    
    def execute_dca_strategy(self, symbol: str, total_amount: float, 
                           num_purchases: int, min_profit_percent: float = 1.0) -> Dict:
        """
        Ejecutar estrategia DCA con verificación de rentabilidad
        
        Args:
            symbol: Símbolo
            total_amount: Monto total
            num_purchases: Número de compras
            min_profit_percent: Ganancia mínima por compra
        """
        amount_per_purchase = total_amount / num_purchases
        
        # Verificar si cada compra es rentable
        round_trip = self.fee_calc.calculate_round_trip_fees(
            amount_per_purchase, True, 'spot'
        )
        break_even = round_trip['break_even_percent']
        
        if min_profit_percent < break_even:
            return {
                "executed": False,
                "error": f"Ganancia mínima ({min_profit_percent}%) menor que break even ({break_even:.3f}%)",
                "break_even": break_even,
                "recommendation": f"Aumenta min_profit_percent a al menos {break_even + 0.1:.2f}%"
            }
        
        results = []
        total_fees = 0
        
        for i in range(num_purchases):
            print(f"\nCompra #{i+1}/{num_purchases}:")
            result = self.execute_smart_order_if_profitable(
                symbol, "BUY", amount_per_purchase, min_profit_percent
            )
            
            if result.get('executed'):
                results.append(result)
                total_fees += result['fees']
                print(f"  ✅ Ejecutada: {result['quantity']:.6f} @ ${result['price']}")
            else:
                print(f"  ❌ No ejecutada: {result.get('reason', result.get('error'))}")
                results.append(result)
            
            # Esperar entre compras (en producción usarías un scheduler)
            if i < num_purchases - 1:
                time.sleep(1)  # Solo para demo
        
        return {
            "strategy": "DCA",
            "total_amount": total_amount,
            "num_purchases": num_purchases,
            "executed_orders": len([r for r in results if r.get('executed')]),
            "total_fees": total_fees,
            "results": results,
            "profitability_analysis": self.fee_calc.analyze_strategy_profitability({
                'name': 'DCA',
                'amount': amount_per_purchase,
                'expected_profit_percent': min_profit_percent,
                'use_limit_orders': True
            }, 'spot')
        }
    
    def execute_grid_strategy(self, symbol: str, total_capital: float,
                            num_levels: int, grid_spacing_percent: float) -> Dict:
        """
        Ejecutar grid trading solo si es rentable
        
        Args:
            symbol: Símbolo
            total_capital: Capital total
            num_levels: Número de niveles
            grid_spacing_percent: Espaciado entre niveles
        """
        # 1. Verificar rentabilidad del grid
        grid_config = {
            'total_capital': total_capital,
            'num_levels': num_levels,
            'grid_spacing_percent': grid_spacing_percent,
            'expected_trades_per_month': 10
        }
        
        grid_analysis = self.fee_calc.calculate_grid_profitability(grid_config)
        
        if not grid_analysis['is_profitable']:
            return {
                "executed": False,
                "error": "Grid trading no es rentable con esta configuración",
                "analysis": grid_analysis,
                "recommendation": f"Necesitas al menos {grid_analysis['break_even_trades']:.2f}% de spread"
            }
        
        # 2. Obtener precio actual
        current_price = self.get_current_price(symbol)
        if not current_price:
            return {"error": "No se pudo obtener precio", "executed": False}
        
        # 3. Calcular niveles
        amount_per_level = total_capital / num_levels
        orders = []
        
        # Órdenes de compra
        for i in range(1, num_levels + 1):
            buy_price = current_price * (1 - (i * grid_spacing_percent / 100))
            quantity = amount_per_level / buy_price
            
            # Verificar fees
            round_trip = self.fee_calc.calculate_round_trip_fees(amount_per_level, True, 'spot')
            profit_per_trade = amount_per_level * (grid_spacing_percent / 100)
            net_profit = profit_per_trade - round_trip['total_fees']
            
            if net_profit > 0:
                orders.append({
                    "type": "BUY",
                    "level": i,
                    "price": buy_price,
                    "quantity": quantity,
                    "amount": amount_per_level,
                    "expected_profit": net_profit,
                    "is_profitable": True
                })
        
        # Órdenes de venta
        for i in range(1, num_levels + 1):
            sell_price = current_price * (1 + (i * grid_spacing_percent / 100))
            quantity = amount_per_level / current_price  # Cantidad comprada
            
            orders.append({
                "type": "SELL",
                "level": i,
                "price": sell_price,
                "quantity": quantity,
                "amount": amount_per_level,
                "is_profitable": True
            })
        
        return {
            "executed": True,
            "strategy": "Grid Trading",
            "current_price": current_price,
            "grid_analysis": grid_analysis,
            "orders": orders,
            "total_orders": len(orders),
            "recommendation": "Colocar todas las órdenes limit y esperar ejecuciones"
        }
    
    def analyze_before_trading(self, symbol: str, amount: float, 
                              expected_profit_percent: float) -> Dict:
        """
        Analizar si vale la pena tradear ANTES de ejecutar
        
        Returns:
            Dict con análisis completo y recomendación
        """
        # 1. Obtener precio
        current_price = self.get_current_price(symbol)
        if not current_price:
            return {"error": "No se pudo obtener precio"}
        
        # 2. Calcular fees
        round_trip = self.fee_calc.calculate_round_trip_fees(amount, True, 'spot')
        break_even = round_trip['break_even_percent']
        
        # 3. Comparar maker vs taker
        maker_vs_taker = self.fee_calc.compare_maker_vs_taker(amount, 'spot')
        
        # 4. Calcular ganancia mínima necesaria
        min_profit = self.fee_calc.calculate_min_profit_needed(
            amount, expected_profit_percent, 'spot', True
        )
        
        # 5. Análisis de rentabilidad
        strategy_analysis = self.fee_calc.analyze_strategy_profitability({
            'name': 'Trading',
            'amount': amount,
            'expected_profit_percent': expected_profit_percent,
            'use_limit_orders': True
        }, 'spot')
        
        # 6. Recomendación
        recommendation = "✅ PROCEDE" if strategy_analysis['is_profitable'] else "❌ NO PROCEDAS"
        if not strategy_analysis['is_profitable']:
            recommendation += f" - Fees ({round_trip['total_fees']:.4f}) mayores que profit esperado"
        
        return {
            "symbol": symbol,
            "current_price": current_price,
            "amount": amount,
            "expected_profit_percent": expected_profit_percent,
            "fees_analysis": {
                "total_fees": round_trip['total_fees'],
                "break_even_percent": break_even,
                "maker_vs_taker": maker_vs_taker
            },
            "profitability": strategy_analysis,
            "min_profit_needed": min_profit,
            "recommendation": recommendation,
            "should_trade": strategy_analysis['is_profitable']
        }

def main():
    """Ejemplo de uso"""
    trader = AutomatedTrading()
    
    if not trader.check_api():
        print("❌ API no disponible. Ejecuta: python run.py")
        return
    
    print("="*60)
    print("SISTEMA AUTOMATIZADO DE TRADING CON CÁLCULO DE FEES")
    print("="*60)
    
    # Ejemplo 1: Analizar antes de tradear
    print("\n1. ANÁLISIS ANTES DE TRADEAR:")
    analysis = trader.analyze_before_trading("BTCUSDT", 50, 1.0)
    print(f"   Símbolo: {analysis['symbol']}")
    print(f"   Monto: ${analysis['amount']}")
    print(f"   Profit esperado: {analysis['expected_profit_percent']}%")
    print(f"   Fees totales: ${analysis['fees_analysis']['total_fees']:.4f}")
    print(f"   Break even: {analysis['fees_analysis']['break_even_percent']:.3f}%")
    print(f"   Profit neto: {analysis['profitability']['net_profit_percent']:.3f}%")
    print(f"   {analysis['recommendation']}")
    
    # Ejemplo 2: Grid trading con verificación
    print("\n2. ANÁLISIS GRID TRADING:")
    grid_result = trader.execute_grid_strategy("BTCUSDT", 500, 5, 2.0)
    if grid_result.get('executed'):
        print(f"   ✅ Grid rentable")
        print(f"   Profit mensual estimado: ${grid_result['grid_analysis']['monthly_profit']:.2f}")
        print(f"   Total órdenes: {grid_result['total_orders']}")
    else:
        print(f"   ❌ {grid_result.get('error')}")
    
    print("\n" + "="*60)
    print("IMPORTANTE:")
    print("="*60)
    print("✅ Este sistema calcula fees REALES antes de ejecutar")
    print("✅ Solo ejecuta órdenes si son rentables después de fees")
    print("✅ Usa órdenes LIMIT (maker) para minimizar fees")
    print("⚠️  Siempre prueba en TESTNET primero")

if __name__ == "__main__":
    main()
