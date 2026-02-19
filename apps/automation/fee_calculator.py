#!/usr/bin/env python3
"""
Calculadora de Fees y Rentabilidad Real
Calcula fees reales de Binance y determina si las estrategias son rentables
"""

import requests
from typing import Dict, Optional, Tuple
from decimal import Decimal, ROUND_DOWN

class FeeCalculator:
    """Calculadora de fees y rentabilidad"""
    
    def __init__(self, api_url: str = "http://localhost:8000"):
        self.api_url = api_url
        # Fees estándar de Binance (pueden variar según VIP level)
        self.spot_maker_fee = 0.001  # 0.1% maker
        self.spot_taker_fee = 0.001  # 0.1% taker (puede ser 0.075% para VIP)
        self.futures_maker_fee = 0.0002  # 0.02% maker
        self.futures_taker_fee = 0.0004  # 0.04% taker
        
    def get_account_fees(self) -> Optional[Dict]:
        """Obtener fees reales de la cuenta desde Binance"""
        try:
            response = requests.get(f"{self.api_url}/account/info")
            if response.status_code == 200:
                data = response.json()
                account_data = data.get('data', {})
                
                # Binance devuelve fees como porcentajes (ej: 10 = 0.1%)
                maker_commission = account_data.get('maker_commission', 10) / 10000
                taker_commission = account_data.get('taker_commission', 10) / 10000
                
                return {
                    'maker_fee': maker_commission,
                    'taker_fee': taker_commission,
                    'maker_percent': maker_commission * 100,
                    'taker_percent': taker_commission * 100
                }
        except Exception as e:
            print(f"Error obteniendo fees de cuenta: {e}")
        return None
    
    def calculate_spot_fees(self, amount: float, is_maker: bool = True) -> Dict:
        """
        Calcular fees de spot trading
        
        Args:
            amount: Monto de la operación en USD
            is_maker: True si es orden limit (maker), False si es market (taker)
        """
        account_fees = self.get_account_fees()
        
        if account_fees:
            fee_rate = account_fees['maker_fee'] if is_maker else account_fees['taker_fee']
        else:
            fee_rate = self.spot_maker_fee if is_maker else self.spot_taker_fee
        
        fee = amount * fee_rate
        net_amount = amount - fee
        
        return {
            'gross_amount': amount,
            'fee': fee,
            'fee_rate': fee_rate,
            'fee_percent': fee_rate * 100,
            'net_amount': net_amount,
            'is_maker': is_maker,
            'fee_type': 'maker' if is_maker else 'taker'
        }
    
    def calculate_futures_fees(self, notional: float, is_maker: bool = True) -> Dict:
        """
        Calcular fees de futures trading
        
        Args:
            notional: Valor notional de la posición (precio * cantidad)
            is_maker: True si es orden limit (maker), False si es market (taker)
        """
        account_fees = self.get_account_fees()
        
        if account_fees:
            fee_rate = account_fees['maker_fee'] if is_maker else account_fees['taker_fee']
        else:
            fee_rate = self.futures_maker_fee if is_maker else self.futures_taker_fee
        
        fee = notional * fee_rate
        net_notional = notional - fee
        
        return {
            'notional': notional,
            'fee': fee,
            'fee_rate': fee_rate,
            'fee_percent': fee_rate * 100,
            'net_notional': net_notional,
            'is_maker': is_maker,
            'fee_type': 'maker' if is_maker else 'taker'
        }
    
    def calculate_round_trip_fees(self, amount: float, is_maker: bool = True, 
                                 market_type: str = 'spot') -> Dict:
        """
        Calcular fees de ida y vuelta (compra + venta)
        
        Args:
            amount: Monto inicial
            is_maker: Si usa órdenes limit (maker)
            market_type: 'spot' o 'futures'
        """
        if market_type == 'spot':
            # Compra
            buy_fees = self.calculate_spot_fees(amount, is_maker)
            amount_after_buy = buy_fees['net_amount']
            
            # Venta (asumiendo mismo precio para simplificar)
            sell_fees = self.calculate_spot_fees(amount_after_buy, is_maker)
            amount_after_sell = sell_fees['net_amount']
            
            total_fees = buy_fees['fee'] + sell_fees['fee']
            net_profit_loss = amount_after_sell - amount
            
        else:  # futures
            # Apertura
            open_fees = self.calculate_futures_fees(amount, is_maker)
            # Cierre
            close_fees = self.calculate_futures_fees(amount, is_maker)
            
            total_fees = open_fees['fee'] + close_fees['fee']
            amount_after_sell = amount - total_fees
            net_profit_loss = amount_after_sell - amount
        
        return {
            'initial_amount': amount,
            'total_fees': total_fees,
            'final_amount': amount_after_sell,
            'net_profit_loss': net_profit_loss,
            'fee_percent_total': (total_fees / amount) * 100,
            'break_even_percent': (total_fees / amount) * 100,
            'market_type': market_type,
            'is_maker': is_maker
        }
    
    def calculate_min_profit_needed(self, amount: float, target_profit_percent: float = 0,
                                   market_type: str = 'spot', is_maker: bool = True) -> Dict:
        """
        Calcular ganancia mínima necesaria para cubrir fees y obtener profit
        
        Args:
            amount: Monto inicial
            target_profit_percent: Porcentaje de ganancia objetivo (ej: 1.0 = 1%)
            market_type: 'spot' o 'futures'
            is_maker: Si usa órdenes limit
        """
        round_trip = self.calculate_round_trip_fees(amount, is_maker, market_type)
        
        # Ganancia mínima para break even
        break_even_percent = round_trip['break_even_percent']
        
        # Ganancia mínima para profit objetivo
        min_profit_percent = break_even_percent + target_profit_percent
        min_profit_amount = amount * (min_profit_percent / 100)
        
        return {
            'initial_amount': amount,
            'break_even_percent': break_even_percent,
            'target_profit_percent': target_profit_percent,
            'min_profit_percent': min_profit_percent,
            'min_profit_amount': min_profit_amount,
            'total_fees': round_trip['total_fees'],
            'market_type': market_type,
            'is_maker': is_maker,
            'is_profitable': target_profit_percent > break_even_percent
        }
    
    def analyze_strategy_profitability(self, strategy: Dict, market_type: str = 'spot') -> Dict:
        """
        Analizar si una estrategia es rentable después de fees
        
        Args:
            strategy: Dict con 'amount', 'expected_profit_percent', etc.
            market_type: 'spot' o 'futures'
        """
        amount = strategy.get('amount', 0)
        expected_profit_percent = strategy.get('expected_profit_percent', 0)
        is_maker = strategy.get('use_limit_orders', True)
        
        min_profit = self.calculate_min_profit_needed(
            amount, expected_profit_percent, market_type, is_maker
        )
        
        # Calcular profit real después de fees
        expected_profit_amount = amount * (expected_profit_percent / 100)
        net_profit = expected_profit_amount - min_profit['total_fees']
        net_profit_percent = (net_profit / amount) * 100
        
        is_profitable = net_profit > 0
        
        return {
            'strategy': strategy.get('name', 'Unknown'),
            'initial_amount': amount,
            'expected_profit_percent': expected_profit_percent,
            'expected_profit_amount': expected_profit_amount,
            'total_fees': min_profit['total_fees'],
            'net_profit': net_profit,
            'net_profit_percent': net_profit_percent,
            'break_even_percent': min_profit['break_even_percent'],
            'is_profitable': is_profitable,
            'margin': net_profit_percent - min_profit['break_even_percent'],
            'recommendation': '✅ Rentable' if is_profitable else '❌ No rentable (fees muy altos)'
        }
    
    def compare_maker_vs_taker(self, amount: float, market_type: str = 'spot') -> Dict:
        """Comparar fees de maker vs taker"""
        maker_fees = self.calculate_round_trip_fees(amount, is_maker=True, market_type=market_type)
        taker_fees = self.calculate_round_trip_fees(amount, is_maker=False, market_type=market_type)
        
        savings = taker_fees['total_fees'] - maker_fees['total_fees']
        savings_percent = (savings / amount) * 100
        
        return {
            'amount': amount,
            'maker_fees': maker_fees['total_fees'],
            'taker_fees': taker_fees['total_fees'],
            'savings_with_maker': savings,
            'savings_percent': savings_percent,
            'market_type': market_type,
            'recommendation': f"Usar órdenes LIMIT (maker) ahorra {savings_percent:.3f}%"
        }
    
    def calculate_grid_profitability(self, grid_config: Dict) -> Dict:
        """
        Calcular si grid trading es rentable
        
        Args:
            grid_config: {
                'total_capital': 500,
                'num_levels': 5,
                'grid_spacing_percent': 2.0,
                'expected_trades_per_month': 10
            }
        """
        total_capital = grid_config['total_capital']
        num_levels = grid_config['num_levels']
        grid_spacing = grid_config['grid_spacing_percent']
        expected_trades = grid_config.get('expected_trades_per_month', 10)
        
        amount_per_level = total_capital / num_levels
        
        # Cada trade es compra + venta (round trip)
        profit_per_trade_percent = grid_spacing  # Asumiendo que capturamos el spread completo
        profit_per_trade_amount = amount_per_level * (profit_per_trade_percent / 100)
        
        # Fees por trade
        round_trip = self.calculate_round_trip_fees(amount_per_level, is_maker=True, market_type='spot')
        fees_per_trade = round_trip['total_fees']
        
        # Profit neto por trade
        net_profit_per_trade = profit_per_trade_amount - fees_per_trade
        
        # Profit mensual estimado
        monthly_profit = net_profit_per_trade * expected_trades
        monthly_profit_percent = (monthly_profit / total_capital) * 100
        
        is_profitable = net_profit_per_trade > 0
        
        return {
            'total_capital': total_capital,
            'num_levels': num_levels,
            'grid_spacing': grid_spacing,
            'amount_per_level': amount_per_level,
            'profit_per_trade_percent': profit_per_trade_percent,
            'profit_per_trade_amount': profit_per_trade_amount,
            'fees_per_trade': fees_per_trade,
            'net_profit_per_trade': net_profit_per_trade,
            'expected_trades_per_month': expected_trades,
            'monthly_profit': monthly_profit,
            'monthly_profit_percent': monthly_profit_percent,
            'is_profitable': is_profitable,
            'break_even_trades': round_trip['break_even_percent'] / grid_spacing if grid_spacing > 0 else 0,
            'recommendation': f"{'✅ Rentable' if is_profitable else '❌ No rentable'} - Necesitas {grid_spacing:.2f}% de spread mínimo"
        }

def main():
    """Ejemplos de uso"""
    calc = FeeCalculator()
    
    print("="*60)
    print("CALCULADORA DE FEES Y RENTABILIDAD")
    print("="*60)
    
    # 1. Obtener fees reales de la cuenta
    print("\n1. FEES REALES DE TU CUENTA:")
    account_fees = calc.get_account_fees()
    if account_fees:
        print(f"   Maker Fee: {account_fees['maker_percent']:.3f}%")
        print(f"   Taker Fee: {account_fees['taker_percent']:.3f}%")
    else:
        print("   Usando fees estándar (no se pudo obtener de cuenta)")
    
    # 2. Comparar Maker vs Taker
    print("\n2. COMPARACIÓN MAKER vs TAKER ($500 operación):")
    comparison = calc.compare_maker_vs_taker(500, 'spot')
    print(f"   Maker Fees: ${comparison['maker_fees']:.2f}")
    print(f"   Taker Fees: ${comparison['taker_fees']:.2f}")
    print(f"   Ahorro con Maker: ${comparison['savings_with_maker']:.2f} ({comparison['savings_percent']:.3f}%)")
    print(f"   💡 {comparison['recommendation']}")
    
    # 3. Calcular ganancia mínima necesaria
    print("\n3. GANANCIA MÍNIMA NECESARIA (Break Even):")
    for amount in [50, 100, 500]:
        min_profit = calc.calculate_min_profit_needed(amount, 0, 'spot', True)
        print(f"\n   Monto: ${amount}")
        print(f"   Fees totales: ${min_profit['total_fees']:.4f}")
        print(f"   Break Even: {min_profit['break_even_percent']:.3f}%")
        print(f"   → Necesitas {min_profit['break_even_percent']:.3f}% de ganancia solo para cubrir fees")
    
    # 4. Analizar estrategia DCA
    print("\n4. ANÁLISIS ESTRATEGIA DCA ($50 por compra):")
    dca_strategy = {
        'name': 'DCA',
        'amount': 50,
        'expected_profit_percent': 5.0,  # Esperas 5% de ganancia
        'use_limit_orders': True
    }
    dca_analysis = calc.analyze_strategy_profitability(dca_strategy, 'spot')
    print(f"   Profit esperado: {dca_analysis['expected_profit_percent']:.2f}%")
    print(f"   Fees totales: ${dca_analysis['total_fees']:.4f}")
    print(f"   Profit neto: {dca_analysis['net_profit_percent']:.3f}% (${dca_analysis['net_profit']:.2f})")
    print(f"   {dca_analysis['recommendation']}")
    
    # 5. Analizar Grid Trading
    print("\n5. ANÁLISIS GRID TRADING:")
    grid_config = {
        'total_capital': 500,
        'num_levels': 5,
        'grid_spacing_percent': 2.0,
        'expected_trades_per_month': 10
    }
    grid_analysis = calc.calculate_grid_profitability(grid_config)
    print(f"   Capital: ${grid_analysis['total_capital']}")
    print(f"   Profit por trade: {grid_analysis['profit_per_trade_percent']:.2f}%")
    print(f"   Fees por trade: ${grid_analysis['fees_per_trade']:.4f}")
    print(f"   Profit neto por trade: ${grid_analysis['net_profit_per_trade']:.4f}")
    print(f"   Profit mensual estimado: ${grid_analysis['monthly_profit']:.2f} ({grid_analysis['monthly_profit_percent']:.2f}%)")
    print(f"   {grid_analysis['recommendation']}")
    
    # 6. Comparar Spot vs Futures
    print("\n6. COMPARACIÓN SPOT vs FUTURES ($500):")
    spot_fees = calc.calculate_round_trip_fees(500, True, 'spot')
    futures_fees = calc.calculate_round_trip_fees(500, True, 'futures')
    print(f"   Spot Fees: ${spot_fees['total_fees']:.4f} ({spot_fees['fee_percent_total']:.3f}%)")
    print(f"   Futures Fees: ${futures_fees['total_fees']:.4f} ({futures_fees['fee_percent_total']:.3f}%)")
    savings = spot_fees['total_fees'] - futures_fees['total_fees']
    print(f"   💰 Ahorro con Futures: ${savings:.4f} ({abs(savings/500*100):.3f}%)")
    
    print("\n" + "="*60)
    print("CONCLUSIONES:")
    print("="*60)
    print("✅ SIEMPRE usa órdenes LIMIT (maker) para ahorrar fees")
    print("✅ Futures tiene fees más bajos que Spot")
    print("✅ Necesitas al menos 0.2-0.4% de ganancia para cubrir fees")
    print("✅ Grid trading necesita spreads > 0.5% para ser rentable")
    print("❌ Market orders (taker) te comen las ganancias")

if __name__ == "__main__":
    main()
