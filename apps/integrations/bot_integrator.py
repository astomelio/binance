#!/usr/bin/env python3
"""
Integrador del Bot Long/Short con el Conector de Binance
Conecta el bot de momentum con el sistema de ejecución inteligente
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
import requests

# Agregar el directorio del bot long/short al path
sys.path.append('/Users/joaquincano/Downloads')

# Importar el bot long/short
try:
    from long_short_binance import BinanceUSDM, Config, run_once, live_loop, build_universe, rank_and_weights, desired_positions
except ImportError as e:
    print(f"Error importando bot long/short: {e}")
    print("Asegúrate de que el archivo long_short_binance.py esté en Downloads/")

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BotIntegrator:
    """Integrador entre el bot long/short y el conector de Binance"""
    
    def __init__(self, connector_url: str = "http://localhost:8000"):
        self.connector_url = connector_url
        self.bot = None
        self.config = Config()
        self.last_rebalance = None
        self.active_positions = {}
        
    def initialize_bot(self):
        """Inicializar el bot long/short"""
        try:
            # Crear instancia del bot
            self.bot = BinanceUSDM()
            logger.info("Bot long/short inicializado correctamente")
            return True
        except Exception as e:
            logger.error(f"Error inicializando bot: {e}")
            return False
    
    def get_connector_status(self) -> Dict:
        """Verificar estado del conector"""
        try:
            response = requests.get(f"{self.connector_url}/health")
            return response.json()
        except Exception as e:
            logger.error(f"Error verificando conector: {e}")
            return {"error": str(e)}
    
    def execute_smart_order(self, symbol: str, side: str, quantity: float, 
                          position_side: str = None) -> Dict:
        """Ejecutar orden inteligente a través del conector (anti-slippage)"""
        try:
            # CRÍTICO: Para SHORTS, configurar margen AISLADO automáticamente
            if position_side == "SHORT":
                margin_response = requests.post(
                    f"{self.connector_url}/futures/margin_type",
                    json={"symbol": symbol, "margin_type": "ISOLATED"}
                )
                
                if margin_response.status_code == 200:
                    margin_data = margin_response.json()
                    if margin_data.get('status') == 'success':
                        logger.info(f"Margen aislado configurado para SHORT: {symbol}")
                    else:
                        logger.warning(f"No se pudo configurar margen aislado para {symbol}: {margin_data.get('error')}")
                else:
                    logger.warning(f"Error configurando margen aislado para {symbol}")
            
            # Obtener precio óptimo para evitar slippage
            price_response = requests.get(
                f"{self.connector_url}/futures/order/optimal-price/{symbol}",
                params={"side": side, "price_offset_percent": 0.1}
            )
            
            if price_response.status_code != 200:
                return {"error": "No se pudo obtener precio óptimo"}
            
            price_data = price_response.json()
            if price_data.get('status') != 'success':
                return {"error": "Error obteniendo precio óptimo"}
            
            # Crear orden limit inteligente (anti-slippage)
            order_data = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price_offset_percent": 0.1  # 0.1% offset para mejor ejecución
            }
            
            if position_side:
                order_data["position_side"] = position_side
            
            # Usar el endpoint de órdenes limit inteligentes
            order_response = requests.post(
                f"{self.connector_url}/futures/order/smart-limit",
                json=order_data
            )
            
            if order_response.status_code != 200:
                return {"error": "Error creando orden limit inteligente"}
            
            result = order_response.json()
            
            # Log de la orden ejecutada
            if result.get('status') == 'success':
                data = result.get('data', {})
                margin_info = " (Margen AISLADO)" if position_side == "SHORT" else ""
                logger.info(f"Orden limit inteligente ejecutada: {symbol} {side} {quantity} @ {data.get('price', 'N/A')}{margin_info}")
                logger.info(f"Precio óptimo: {price_data.get('data', {}).get('market_price', 'N/A')}")
                logger.info(f"Precio limit: {data.get('price', 'N/A')}")
                if position_side == "SHORT":
                    logger.info(f"Protección: Margen aislado previene pérdidas excesivas")
            
            return result
            
        except Exception as e:
            logger.error(f"Error ejecutando orden limit inteligente: {e}")
            return {"error": str(e)}
    
    def get_current_positions(self) -> Dict[str, float]:
        """Obtener posiciones actuales"""
        try:
            response = requests.get(f"{self.connector_url}/futures/positions")
            if response.status_code != 200:
                return {}
            
            data = response.json()
            if data.get('status') != 'success':
                return {}
            
            positions = {}
            for pos in data.get('data', []):
                symbol = pos['symbol']
                amount = float(pos['position_amt'])
                if abs(amount) > 0:
                    positions[symbol] = amount
            
            return positions
            
        except Exception as e:
            logger.error(f"Error obteniendo posiciones: {e}")
            return {}
    
    def execute_bot_rebalance(self) -> Dict:
        """Ejecutar ciclo de rebalance del bot"""
        if not self.bot:
            return {"error": "Bot no inicializado"}
        
        try:
            logger.info("Ejecutando ciclo de rebalance del bot...")
            
            # Obtener universo de símbolos
            universe = build_universe(self.bot, self.config)
            if not universe:
                return {"error": "No se pudo obtener universo de símbolos"}
            
            logger.info(f"Universe: {len(universe)} símbolos")
            
            # Obtener datos y calcular indicadores
            data_map = {}
            prices = {}
            
            for symbol in universe:
                try:
                    df = self.bot.fetch_ohlcv_df(symbol, timeframe=self.config.tf, limit=2000)
                    if df.empty:
                        continue
                    
                    # Aquí necesitarías importar compute_indicators del bot original
                    # Por ahora usamos datos básicos
                    data_map[symbol] = df
                    prices[symbol] = float(df['close'].iloc[-1])
                    
                except Exception as e:
                    logger.warning(f"Error obteniendo datos para {symbol}: {e}")
                    continue
            
            if len(data_map) < 10:
                return {"error": "Insuficientes datos para trading"}
            
            # Calcular pesos (simplificado)
            weights = self._calculate_weights_simplified(data_map)
            
            if not weights:
                return {"error": "No se pudieron calcular pesos"}
            
            # Obtener posiciones actuales
            current_positions = self.get_current_positions()
            
            # Calcular targets
            equity = 10000  # Valor fijo para ejemplo
            targets = self._calculate_targets(weights, prices, equity)
            
            # Ejecutar órdenes
            results = self._execute_rebalance_orders(targets, current_positions)
            
            self.last_rebalance = datetime.now(timezone.utc)
            
            return {
                "status": "success",
                "universe_size": len(universe),
                "weights": weights,
                "targets": targets,
                "results": results,
                "timestamp": self.last_rebalance.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error en rebalance: {e}")
            return {"error": str(e)}
    
    def _calculate_weights_simplified(self, data_map: Dict) -> Dict[str, float]:
        """Cálculo simplificado de pesos (reemplazar con lógica del bot original)"""
        weights = {}
        
        # Simular pesos basados en momentum simple
        for symbol, df in data_map.items():
            if len(df) < 20:
                continue
            
            # Calcular momentum simple
            current_price = df['close'].iloc[-1]
            past_price = df['close'].iloc[-20]
            momentum = (current_price - past_price) / past_price
            
            # Asignar peso basado en momentum
            if momentum > 0.02:  # 2% de momentum positivo
                weights[symbol] = 0.1
            elif momentum < -0.02:  # 2% de momentum negativo
                weights[symbol] = -0.1
        
        return weights
    
    def _calculate_targets(self, weights: Dict[str, float], prices: Dict[str, float], equity: float) -> Dict[str, float]:
        """Calcular targets de posición"""
        targets = {}
        
        # Distribuir equity entre posiciones
        total_weight = sum(abs(w) for w in weights.values())
        if total_weight == 0:
            return targets
        
        for symbol, weight in weights.items():
            if abs(weight) < 0.001:
                continue
            
            price = prices.get(symbol, 0)
            if price <= 0:
                continue
            
            # Calcular cantidad basada en peso y equity
            notional = equity * abs(weight) / total_weight
            quantity = notional / price
            
            targets[symbol] = quantity if weight > 0 else -quantity
        
        return targets
    
    def _execute_rebalance_orders(self, targets: Dict[str, float], current_positions: Dict[str, float]) -> List[Dict]:
        """Ejecutar órdenes de rebalance con manejo correcto de shorts"""
        results = []
        
        for symbol, target in targets.items():
            current = current_positions.get(symbol, 0.0)
            delta = target - current
            
            if abs(delta) < 0.001:  # Ignorar cambios muy pequeños
                continue
            
            # Determinar lado de la orden y posición
            if delta > 0:
                # Aumentar posición LONG o abrir LONG
                if current >= 0:
                    # Ya tenemos posición LONG o no tenemos posición
                    side = "BUY"
                    position_side = "LONG"
                else:
                    # Tenemos posición SHORT, necesitamos cerrar parte y abrir LONG
                    # Primero cerrar parte del SHORT
                    close_quantity = min(abs(current), delta)
                    close_result = self.execute_smart_order(
                        symbol=symbol,
                        side="BUY",  # Para cerrar SHORT
                        quantity=close_quantity,
                        position_side="SHORT"
                    )
                    
                    # Luego abrir LONG con el resto
                    remaining_quantity = delta - close_quantity
                    if remaining_quantity > 0:
                        open_result = self.execute_smart_order(
                            symbol=symbol,
                            side="BUY",
                            quantity=remaining_quantity,
                            position_side="LONG"
                        )
                        result = open_result
                    else:
                        result = close_result
                    
                    results.append({
                        "symbol": symbol,
                        "operation": "SHORT_TO_LONG",
                        "close_quantity": close_quantity,
                        "open_quantity": remaining_quantity,
                        "current": current,
                        "target": target,
                        "result": result
                    })
                    continue
            else:
                # Aumentar posición SHORT o abrir SHORT
                if current <= 0:
                    # Ya tenemos posición SHORT o no tenemos posición
                    side = "SELL"
                    position_side = "SHORT"
                else:
                    # Tenemos posición LONG, necesitamos cerrar parte y abrir SHORT
                    # Primero cerrar parte del LONG
                    close_quantity = min(current, abs(delta))
                    close_result = self.execute_smart_order(
                        symbol=symbol,
                        side="SELL",  # Para cerrar LONG
                        quantity=close_quantity,
                        position_side="LONG"
                    )
                    
                    # Luego abrir SHORT con el resto
                    remaining_quantity = abs(delta) - close_quantity
                    if remaining_quantity > 0:
                        open_result = self.execute_smart_order(
                            symbol=symbol,
                            side="SELL",
                            quantity=remaining_quantity,
                            position_side="SHORT"
                        )
                        result = open_result
                    else:
                        result = close_result
                    
                    results.append({
                        "symbol": symbol,
                        "operation": "LONG_TO_SHORT",
                        "close_quantity": close_quantity,
                        "open_quantity": remaining_quantity,
                        "current": current,
                        "target": target,
                        "result": result
                    })
                    continue
            
            # Ejecutar orden simple (mismo tipo de posición)
            result = self.execute_smart_order(
                symbol=symbol,
                side=side,
                quantity=abs(delta),
                position_side=position_side
            )
            
            results.append({
                "symbol": symbol,
                "side": side,
                "quantity": abs(delta),
                "current": current,
                "target": target,
                "result": result
            })
            
            logger.info(f"Orden ejecutada: {symbol} {side} {abs(delta):.6f} ({position_side})")
        
        return results
    
    def run_continuous(self, rebalance_interval_minutes: int = 15):
        """Ejecutar bot en modo continuo"""
        if not self.initialize_bot():
            return
        
        logger.info(f"Iniciando bot integrado - Rebalance cada {rebalance_interval_minutes} minutos")
        
        while True:
            try:
                # Verificar estado del conector
                connector_status = self.get_connector_status()
                if connector_status.get('status') != 'healthy':
                    logger.error("Conector no disponible")
                    time.sleep(60)
                    continue
                
                # Ejecutar rebalance
                result = self.execute_bot_rebalance()
                
                if result.get('status') == 'success':
                    logger.info(f"Rebalance exitoso: {len(result.get('results', []))} órdenes")
                else:
                    logger.error(f"Error en rebalance: {result.get('error')}")
                
                # Esperar hasta próximo rebalance
                time.sleep(rebalance_interval_minutes * 60)
                
            except KeyboardInterrupt:
                logger.info("Bot detenido por usuario")
                break
            except Exception as e:
                logger.error(f"Error en loop principal: {e}")
                time.sleep(60)
    
    def run_once(self):
        """Ejecutar un solo ciclo de rebalance"""
        if not self.initialize_bot():
            return {"error": "Bot no inicializado"}
        
        return self.execute_bot_rebalance()

def create_bot_api():
    """Crear API para el bot integrado"""
    from flask import Flask, request, jsonify
    
    app = Flask(__name__)
    integrator = BotIntegrator()
    
    @app.route('/bot/status', methods=['GET'])
    def get_bot_status():
        """Obtener estado del bot"""
        connector_status = integrator.get_connector_status()
        positions = integrator.get_current_positions()
        
        return jsonify({
            "connector_status": connector_status,
            "active_positions": len(positions),
            "last_rebalance": integrator.last_rebalance.isoformat() if integrator.last_rebalance else None
        })
    
    @app.route('/bot/rebalance', methods=['POST'])
    def execute_rebalance():
        """Ejecutar rebalance del bot"""
        result = integrator.run_once()
        return jsonify(result)
    
    @app.route('/bot/start', methods=['POST'])
    def start_bot():
        """Iniciar bot en modo continuo"""
        data = request.json or {}
        interval = data.get('rebalance_interval_minutes', 15)
        
        # Ejecutar en background (simplificado)
        import threading
        thread = threading.Thread(
            target=integrator.run_continuous,
            args=(interval,),
            daemon=True
        )
        thread.start()
        
        return jsonify({
            "status": "Bot iniciado",
            "rebalance_interval_minutes": interval
        })
    
    @app.route('/bot/positions', methods=['GET'])
    def get_positions():
        """Obtener posiciones actuales"""
        positions = integrator.get_current_positions()
        return jsonify(positions)
    
    return app

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Bot Integrado Long/Short")
    parser.add_argument("--once", action="store_true", help="Ejecutar un solo ciclo")
    parser.add_argument("--continuous", action="store_true", help="Ejecutar en modo continuo")
    parser.add_argument("--interval", type=int, default=15, help="Intervalo de rebalance en minutos")
    parser.add_argument("--api", action="store_true", help="Ejecutar como API")
    
    args = parser.parse_args()
    
    integrator = BotIntegrator()
    
    if args.api:
        app = create_bot_api()
        app.run(host='0.0.0.0', port=5000)
    elif args.once:
        result = integrator.run_once()
        print(json.dumps(result, indent=2))
    elif args.continuous:
        integrator.run_continuous(args.interval)
    else:
        print("Usar --once, --continuous, o --api")
