#!/usr/bin/env python3
"""
Estrategia de Trading con $500 USD usando la API de Binance
Estrategias conservadoras y responsables para generar ganancias

⚠️ ADVERTENCIAS:
- Trading de criptomonedas es de ALTO RIESGO
- Puedes perder todo tu capital
- Solo invierte lo que puedes permitirte perder
- Siempre prueba primero en TESTNET
- Estas estrategias son educativas, no garantizan ganancias
"""

import requests
import time
import json
from typing import Dict, List, Optional
from datetime import datetime

API_URL = "http://localhost:8000"

class TradingStrategy500USD:
    """Estrategias de trading con $500 USD"""
    
    def __init__(self, api_url: str = API_URL):
        self.api_url = api_url
        self.capital = 500.0  # $500 USD
        self.max_risk_per_trade = 0.02  # 2% máximo por trade (conservador)
        self.max_position_size = 0.10  # 10% del capital por posición
        
    def check_api_health(self) -> bool:
        """Verificar que la API esté funcionando"""
        try:
            response = requests.get(f"{self.api_url}/health")
            return response.status_code == 200
        except:
            return False
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """Obtener precio actual de un símbolo"""
        try:
            response = requests.get(f"{self.api_url}/market/ticker/{symbol}")
            if response.status_code == 200:
                data = response.json()
                return float(data['data']['last_price'])
        except Exception as e:
            print(f"Error obteniendo precio: {e}")
        return None
    
    def get_optimal_price(self, symbol: str, side: str) -> Optional[Dict]:
        """Obtener precio óptimo para limit order"""
        try:
            response = requests.get(
                f"{self.api_url}/order/optimal-price/{symbol}",
                params={"side": side, "price_offset_percent": 0.1}
            )
            if response.status_code == 200:
                return response.json().get('data')
        except Exception as e:
            print(f"Error obteniendo precio óptimo: {e}")
        return None
    
    # ============================================================================
    # ESTRATEGIA 1: DCA (Dollar Cost Averaging) - MÁS CONSERVADORA
    # ============================================================================
    
    def strategy_dca(self, symbol: str = "BTCUSDT", intervals_days: int = 7) -> Dict:
        """
        Dollar Cost Averaging: Comprar pequeñas cantidades periódicamente
        
        Ventajas:
        - Reduce el riesgo de timing
        - Promedia el precio de compra
        - Menos estrés emocional
        
        Ejemplo con $500:
        - Dividir en 10 compras de $50 cada una
        - Comprar cada semana durante 10 semanas
        """
        print(f"\n{'='*60}")
        print("ESTRATEGIA 1: Dollar Cost Averaging (DCA)")
        print(f"{'='*60}")
        
        total_investment = self.capital
        num_purchases = 10
        amount_per_purchase = total_investment / num_purchases
        
        print(f"Capital total: ${total_investment:.2f}")
        print(f"Número de compras: {num_purchases}")
        print(f"Monto por compra: ${amount_per_purchase:.2f}")
        print(f"Símbolo: {symbol}")
        print(f"\nPlan de ejecución:")
        
        orders = []
        for i in range(1, num_purchases + 1):
            print(f"\n  Compra #{i}:")
            print(f"    - Monto: ${amount_per_purchase:.2f}")
            
            # Obtener precio actual
            price = self.get_current_price(symbol)
            if price:
                quantity = amount_per_purchase / price
                print(f"    - Precio estimado: ${price:.2f}")
                print(f"    - Cantidad: {quantity:.6f} {symbol.replace('USDT', '')}")
                
                # Obtener precio óptimo
                optimal = self.get_optimal_price(symbol, "BUY")
                if optimal:
                    print(f"    - Precio óptimo sugerido: ${optimal['suggested_limit_price']:.2f}")
                    print(f"    - Ahorro vs market: ~0.1% (maker fee)")
                
                orders.append({
                    "purchase_number": i,
                    "amount": amount_per_purchase,
                    "estimated_price": price,
                    "quantity": quantity,
                    "optimal_price": optimal['suggested_limit_price'] if optimal else None
                })
        
        return {
            "strategy": "DCA",
            "total_investment": total_investment,
            "num_purchases": num_purchases,
            "orders": orders,
            "recommendation": "Ejecutar una compra cada semana durante 10 semanas"
        }
    
    # ============================================================================
    # ESTRATEGIA 2: Grid Trading - CONSERVADORA
    # ============================================================================
    
    def strategy_grid_trading(self, symbol: str = "BTCUSDT", grid_levels: int = 5) -> Dict:
        """
        Grid Trading: Colocar órdenes de compra y venta en diferentes niveles
        
        Ventajas:
        - Genera ganancias en mercados laterales
        - Automatiza compra/venta
        - Reduce riesgo emocional
        
        Ejemplo con $500:
        - Dividir en 5 niveles de $100 cada uno
        - Comprar en soportes, vender en resistencias
        """
        print(f"\n{'='*60}")
        print("ESTRATEGIA 2: Grid Trading")
        print(f"{'='*60}")
        
        price = self.get_current_price(symbol)
        if not price:
            return {"error": "No se pudo obtener precio"}
        
        grid_spacing_percent = 2.0  # 2% entre niveles
        amount_per_level = self.capital / grid_levels
        
        print(f"Precio actual: ${price:.2f}")
        print(f"Niveles de grid: {grid_levels}")
        print(f"Espaciado: {grid_spacing_percent}%")
        print(f"Monto por nivel: ${amount_per_level:.2f}")
        
        grid_orders = []
        
        # Órdenes de compra (por debajo del precio actual)
        print(f"\n  Órdenes de COMPRA (soportes):")
        for i in range(1, grid_levels + 1):
            buy_price = price * (1 - (i * grid_spacing_percent / 100))
            quantity = amount_per_level / buy_price
            
            print(f"    Nivel {i}: ${buy_price:.2f} - Cantidad: {quantity:.6f}")
            
            grid_orders.append({
                "type": "BUY",
                "level": i,
                "price": buy_price,
                "quantity": quantity,
                "amount": amount_per_level
            })
        
        # Órdenes de venta (por encima del precio actual)
        print(f"\n  Órdenes de VENTA (resistencias):")
        for i in range(1, grid_levels + 1):
            sell_price = price * (1 + (i * grid_spacing_percent / 100))
            # Asumimos que vendemos lo que compramos
            quantity = amount_per_level / price  # Cantidad comprada
            
            print(f"    Nivel {i}: ${sell_price:.2f} - Cantidad: {quantity:.6f}")
            
            grid_orders.append({
                "type": "SELL",
                "level": i,
                "price": sell_price,
                "quantity": quantity,
                "amount": amount_per_level
            })
        
        return {
            "strategy": "Grid Trading",
            "current_price": price,
            "grid_levels": grid_levels,
            "grid_spacing": grid_spacing_percent,
            "orders": grid_orders,
            "recommendation": "Colocar todas las órdenes limit y esperar ejecuciones"
        }
    
    # ============================================================================
    # ESTRATEGIA 3: Swing Trading Conservador
    # ============================================================================
    
    def strategy_swing_trading(self, symbol: str = "BTCUSDT") -> Dict:
        """
        Swing Trading: Mantener posiciones por días/semanas
        
        Ventajas:
        - Menos tiempo requerido
        - Captura movimientos mayores
        - Menos fees que day trading
        
        Ejemplo con $500:
        - Usar $400 para posición principal
        - Guardar $100 para oportunidades
        """
        print(f"\n{'='*60}")
        print("ESTRATEGIA 3: Swing Trading Conservador")
        print(f"{'='*60}")
        
        price = self.get_current_price(symbol)
        if not price:
            return {"error": "No se pudo obtener precio"}
        
        main_position = self.capital * 0.80  # 80% en posición principal
        reserve = self.capital * 0.20  # 20% en reserva
        
        quantity = main_position / price
        
        print(f"Precio actual: ${price:.2f}")
        print(f"Posición principal: ${main_position:.2f} (80%)")
        print(f"Reserva: ${reserve:.2f} (20%)")
        print(f"Cantidad a comprar: {quantity:.6f} {symbol.replace('USDT', '')}")
        
        # Calcular stop loss y take profit
        stop_loss_percent = 5.0  # 5% stop loss
        take_profit_percent = 10.0  # 10% take profit
        
        stop_loss_price = price * (1 - stop_loss_percent / 100)
        take_profit_price = price * (1 + take_profit_percent / 100)
        
        print(f"\n  Gestión de riesgo:")
        print(f"    Stop Loss: ${stop_loss_price:.2f} (-{stop_loss_percent}%)")
        print(f"    Take Profit: ${take_profit_price:.2f} (+{take_profit_percent}%)")
        print(f"    Riesgo máximo: ${main_position * stop_loss_percent / 100:.2f}")
        
        return {
            "strategy": "Swing Trading",
            "current_price": price,
            "main_position": main_position,
            "reserve": reserve,
            "quantity": quantity,
            "stop_loss": stop_loss_price,
            "take_profit": take_profit_price,
            "max_risk": main_position * stop_loss_percent / 100,
            "recommendation": "Comprar y mantener, revisar semanalmente"
        }
    
    # ============================================================================
    # ESTRATEGIA 4: Arbitraje de Spread (Futuros vs Spot)
    # ============================================================================
    
    def strategy_arbitrage(self, symbol: str = "BTCUSDT") -> Dict:
        """
        Arbitraje: Aprovechar diferencias de precio entre Spot y Futuros
        
        Ventajas:
        - Bajo riesgo (si se ejecuta rápido)
        - Ganancias pequeñas pero consistentes
        
        Ejemplo con $500:
        - Detectar spread > 0.5%
        - Comprar en el mercado más barato
        - Vender en el mercado más caro
        """
        print(f"\n{'='*60}")
        print("ESTRATEGIA 4: Arbitraje Spot vs Futuros")
        print(f"{'='*60}")
        
        # Obtener precios de spot y futuros
        spot_price = self.get_current_price(symbol)
        
        try:
            response = requests.get(f"{self.api_url}/futures/market/ticker/{symbol}")
            if response.status_code == 200:
                futures_data = response.json()
                futures_price = float(futures_data['data']['last_price'])
            else:
                futures_price = None
        except:
            futures_price = None
        
        if not spot_price or not futures_price:
            return {"error": "No se pudieron obtener precios"}
        
        spread = ((futures_price - spot_price) / spot_price) * 100
        
        print(f"Precio Spot: ${spot_price:.2f}")
        print(f"Precio Futuros: ${futures_price:.2f}")
        print(f"Spread: {spread:.3f}%")
        
        min_spread_for_arbitrage = 0.5  # 0.5% mínimo
        
        if abs(spread) > min_spread_for_arbitrage:
            if spread > 0:
                # Futuros más caro: comprar spot, vender futuros
                print(f"\n  Oportunidad detectada: Spread positivo {spread:.3f}%")
                print(f"  Acción: Comprar SPOT, Vender FUTUROS")
                
                quantity = self.capital / spot_price
                profit_potential = self.capital * (spread / 100)
                
                print(f"  Cantidad: {quantity:.6f}")
                print(f"  Ganancia potencial: ${profit_potential:.2f}")
            else:
                # Spot más caro: comprar futuros, vender spot
                print(f"\n  Oportunidad detectada: Spread negativo {spread:.3f}%")
                print(f"  Acción: Comprar FUTUROS, Vender SPOT")
                
                quantity = self.capital / futures_price
                profit_potential = self.capital * (abs(spread) / 100)
                
                print(f"  Cantidad: {quantity:.6f}")
                print(f"  Ganancia potencial: ${profit_potential:.2f}")
        else:
            print(f"\n  No hay oportunidad de arbitraje (spread < {min_spread_for_arbitrage}%)")
        
        return {
            "strategy": "Arbitraje",
            "spot_price": spot_price,
            "futures_price": futures_price,
            "spread": spread,
            "opportunity": abs(spread) > min_spread_for_arbitrage
        }
    
    # ============================================================================
    # ESTRATEGIA 5: Staking/DeFi (Más Seguro)
    # ============================================================================
    
    def strategy_staking(self) -> Dict:
        """
        Staking: Bloquear criptos para obtener rendimientos
        
        Ventajas:
        - Bajo riesgo
        - Rendimientos predecibles
        - No requiere trading activo
        
        Ejemplo con $500:
        - Staking de stablecoins: ~5-10% APY
        - Staking de altcoins: ~10-20% APY (más riesgo)
        """
        print(f"\n{'='*60}")
        print("ESTRATEGIA 5: Staking (Más Seguro)")
        print(f"{'='*60}")
        
        capital = self.capital
        
        # Opción 1: Stablecoins (menor riesgo)
        stablecoin_apy = 8.0  # ~8% APY promedio
        stablecoin_monthly = capital * (stablecoin_apy / 100 / 12)
        stablecoin_yearly = capital * (stablecoin_apy / 100)
        
        print(f"Opción 1: Staking de Stablecoins (USDT/USDC)")
        print(f"  Capital: ${capital:.2f}")
        print(f"  APY estimado: {stablecoin_apy}%")
        print(f"  Ganancia mensual: ${stablecoin_monthly:.2f}")
        print(f"  Ganancia anual: ${stablecoin_yearly:.2f}")
        
        # Opción 2: Altcoins (más riesgo, más rendimiento)
        altcoin_apy = 15.0  # ~15% APY promedio
        altcoin_monthly = capital * (altcoin_apy / 100 / 12)
        altcoin_yearly = capital * (altcoin_apy / 100)
        
        print(f"\nOpción 2: Staking de Altcoins (ETH, BNB, etc.)")
        print(f"  Capital: ${capital:.2f}")
        print(f"  APY estimado: {altcoin_apy}%")
        print(f"  Ganancia mensual: ${altcoin_monthly:.2f}")
        print(f"  Ganancia anual: ${altcoin_yearly:.2f}")
        print(f"  ⚠️ Mayor riesgo de volatilidad")
        
        return {
            "strategy": "Staking",
            "capital": capital,
            "stablecoin_apy": stablecoin_apy,
            "stablecoin_monthly": stablecoin_monthly,
            "stablecoin_yearly": stablecoin_yearly,
            "altcoin_apy": altcoin_apy,
            "altcoin_monthly": altcoin_monthly,
            "altcoin_yearly": altcoin_yearly,
            "recommendation": "Más seguro, pero requiere investigación de plataformas"
        }
    
    # ============================================================================
    # RECOMENDACIÓN GENERAL
    # ============================================================================
    
    def get_recommendations(self) -> Dict:
        """Recomendaciones generales para $500 USD"""
        print(f"\n{'='*60}")
        print("RECOMENDACIONES GENERALES PARA $500 USD")
        print(f"{'='*60}")
        
        recommendations = {
            "para_principiantes": {
                "estrategia": "DCA + Staking",
                "distribucion": {
                    "dca": "70% ($350) - Compras periódicas",
                    "staking": "30% ($150) - Rendimientos pasivos"
                },
                "riesgo": "Bajo",
                "tiempo_requerido": "Bajo (1-2 horas/semana)"
            },
            "para_intermedios": {
                "estrategia": "Swing Trading + Grid",
                "distribucion": {
                    "swing": "60% ($300) - Posición principal",
                    "grid": "30% ($150) - Trading lateral",
                    "reserva": "10% ($50) - Oportunidades"
                },
                "riesgo": "Medio",
                "tiempo_requerido": "Medio (1 hora/día)"
            },
            "para_avanzados": {
                "estrategia": "Combinación + Arbitraje",
                "distribucion": {
                    "swing": "50% ($250)",
                    "grid": "30% ($150)",
                    "arbitrage": "15% ($75)",
                    "reserva": "5% ($25)"
                },
                "riesgo": "Alto",
                "tiempo_requerido": "Alto (monitoreo constante)"
            }
        }
        
        print("\n📊 Distribución Recomendada por Nivel:")
        for nivel, info in recommendations.items():
            print(f"\n  {nivel.upper().replace('_', ' ')}:")
            print(f"    Estrategia: {info['estrategia']}")
            print(f"    Distribución:")
            for key, value in info['distribucion'].items():
                print(f"      - {key}: {value}")
            print(f"    Riesgo: {info['riesgo']}")
            print(f"    Tiempo: {info['tiempo_requerido']}")
        
        return recommendations

def main():
    """Ejecutar análisis de estrategias"""
    print("\n" + "="*60)
    print("ANÁLISIS DE ESTRATEGIAS DE TRADING CON $500 USD")
    print("="*60)
    print("\n⚠️  ADVERTENCIAS:")
    print("  - Trading de criptomonedas es de ALTO RIESGO")
    print("  - Puedes perder todo tu capital")
    print("  - Solo invierte lo que puedes permitirte perder")
    print("  - Siempre prueba primero en TESTNET")
    print("  - Estas estrategias son educativas, no garantizan ganancias")
    
    strategy = TradingStrategy500USD()
    
    # Verificar API
    if not strategy.check_api_health():
        print("\n❌ Error: La API no está disponible")
        print("   Ejecuta: python run.py")
        return
    
    print("\n✅ API conectada correctamente")
    
    # Ejecutar todas las estrategias
    strategies = {
        "dca": strategy.strategy_dca(),
        "grid": strategy.strategy_grid_trading(),
        "swing": strategy.strategy_swing_trading(),
        "arbitrage": strategy.strategy_arbitrage(),
        "staking": strategy.strategy_staking()
    }
    
    # Mostrar recomendaciones
    recommendations = strategy.get_recommendations()
    
    print("\n" + "="*60)
    print("RESUMEN")
    print("="*60)
    print("\n💡 Estrategia más recomendada para principiantes:")
    print("   DCA (Dollar Cost Averaging) + Staking")
    print("   - 70% en compras periódicas")
    print("   - 30% en staking para rendimientos pasivos")
    print("   - Riesgo: Bajo")
    print("   - Tiempo requerido: Mínimo")
    
    print("\n📝 Próximos pasos:")
    print("   1. Prueba todas las estrategias en TESTNET primero")
    print("   2. Elige la estrategia que mejor se adapte a tu perfil")
    print("   3. Empieza con montos pequeños")
    print("   4. Aprende de cada trade")
    print("   5. Nunca inviertas más de lo que puedes perder")

if __name__ == "__main__":
    main()
