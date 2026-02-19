#!/usr/bin/env python3
"""
Sistema de Señales de Trading - Conector entre Bot Long/Short y API de Binance
Integra el bot de momentum con el conector de Binance para ejecución inteligente
"""

import os
import time
import json
import logging
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SignalType(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    CLOSE = "CLOSE"
    REBALANCE = "REBALANCE"

@dataclass
class TradingSignal:
    symbol: str
    signal_type: SignalType
    quantity: float
    price: Optional[float] = None
    leverage: Optional[int] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    timestamp: datetime = None
    metadata: Dict = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
        if self.metadata is None:
            self.metadata = {}

class BinanceConnectorClient:
    """Cliente para el Conector de Binance"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
    
    def _make_request(self, method: str, endpoint: str, data: Dict = None) -> Dict:
        """Realizar petición HTTP al conector"""
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
            logger.error(f"Error en petición HTTP: {e}")
            return {"error": str(e)}
    
    def health_check(self) -> Dict:
        """Verificar estado del conector"""
        return self._make_request('GET', '/health')
    
    def get_optimal_price(self, symbol: str, side: str, price_offset_percent: float = 0.1) -> Dict:
        """Obtener precio óptimo para órdenes limit"""
        endpoint = f'/order/optimal-price/{symbol}?side={side}&price_offset_percent={price_offset_percent}'
        return self._make_request('GET', endpoint)
    
    def create_smart_limit_order(self, symbol: str, side: str, quantity: float, 
                               price_offset_percent: float = 0.1) -> Dict:
        """Crear orden limit inteligente"""
        data = {
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'price_offset_percent': price_offset_percent
        }
        return self._make_request('POST', '/order/smart-limit', data)
    
    def create_smart_futures_order(self, symbol: str, side: str, quantity: float,
                                 position_side: str = None, price_offset_percent: float = 0.1) -> Dict:
        """Crear orden limit de futuros inteligente"""
        data = {
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'price_offset_percent': price_offset_percent
        }
        if position_side:
            data['position_side'] = position_side
        
        return self._make_request('POST', '/futures/order/smart-limit', data)
    
    def get_futures_positions(self) -> Dict:
        """Obtener posiciones de futuros"""
        return self._make_request('GET', '/futures/positions')
    
    def cancel_order(self, symbol: str, order_id: int) -> Dict:
        """Cancelar orden"""
        return self._make_request('DELETE', f'/order/{symbol}/{order_id}')
    
    def cancel_futures_order(self, symbol: str, order_id: int) -> Dict:
        """Cancelar orden de futuros"""
        return self._make_request('DELETE', f'/futures/order/{symbol}/{order_id}')
    
    def set_futures_margin_type(self, symbol: str, margin_type: str) -> Dict:
        """Establecer tipo de margen para futuros (ISOLATED o CROSSED)"""
        data = {
            'symbol': symbol,
            'margin_type': margin_type
        }
        return self._make_request('POST', '/futures/margin_type', data)

class TradingSignalProcessor:
    """Procesador de señales de trading"""
    
    def __init__(self, connector_url: str = "http://localhost:8000"):
        self.connector = BinanceConnectorClient(connector_url)
        self.active_signals: Dict[str, TradingSignal] = {}
        self.signal_history: List[TradingSignal] = []
    
    def process_signal(self, signal: TradingSignal) -> Dict:
        """Procesar una señal de trading"""
        logger.info(f"Procesando señal: {signal.symbol} {signal.signal_type.value}")
        
        try:
            if signal.signal_type == SignalType.LONG:
                return self._execute_long_signal(signal)
            elif signal.signal_type == SignalType.SHORT:
                return self._execute_short_signal(signal)
            elif signal.signal_type == SignalType.CLOSE:
                return self._execute_close_signal(signal)
            elif signal.signal_type == SignalType.REBALANCE:
                return self._execute_rebalance_signal(signal)
            else:
                return {"error": f"Tipo de señal no soportado: {signal.signal_type}"}
        
        except Exception as e:
            logger.error(f"Error procesando señal: {e}")
            return {"error": str(e)}
    
    def _execute_long_signal(self, signal: TradingSignal) -> Dict:
        """Ejecutar señal de compra con orden limit inteligente (anti-slippage)"""
        # Obtener precio óptimo para evitar slippage
        price_info = self.connector.get_optimal_price(
            signal.symbol, "BUY", price_offset_percent=0.1
        )
        
        if price_info.get('status') != 'success':
            return {"error": f"No se pudo obtener precio óptimo para {signal.symbol}"}
        
        # Crear orden limit inteligente (anti-slippage)
        order_result = self.connector.create_smart_limit_order(
            symbol=signal.symbol,
            side="BUY",
            quantity=signal.quantity,
            price_offset_percent=0.1  # 0.1% offset para mejor ejecución
        )
        
        if order_result.get('status') == 'success':
            self.active_signals[signal.symbol] = signal
            self.signal_history.append(signal)
            
            # Log detallado de la orden
            data = order_result.get('data', {})
            price_data = price_info.get('data', {})
            logger.info(f"Orden LONG limit inteligente ejecutada: {signal.symbol}")
            logger.info(f"  Precio de mercado: {price_data.get('market_price', 'N/A')}")
            logger.info(f"  Precio limit: {data.get('price', 'N/A')}")
            logger.info(f"  Cantidad: {signal.quantity}")
            logger.info(f"  Offset aplicado: 0.1%")
        
        return order_result
    
    def _execute_short_signal(self, signal: TradingSignal) -> Dict:
        """Ejecutar señal de SHORT con orden limit inteligente de FUTUROS (anti-slippage)"""
        # CRÍTICO: Configurar margen AISLADO para shorts (ISOLATED)
        # Esto previene pérdidas mayores a la inversión inicial
        margin_result = self.connector.set_futures_margin_type(
            symbol=signal.symbol,
            margin_type="ISOLATED"
        )
        
        if margin_result.get('status') != 'success':
            logger.warning(f"No se pudo configurar margen aislado para {signal.symbol}: {margin_result.get('error')}")
            # Continuar pero con advertencia
        
        # Obtener precio óptimo para futuros para evitar slippage
        price_info = self.connector.get_optimal_price(
            signal.symbol, "SELL", price_offset_percent=0.1
        )
        
        if price_info.get('status') != 'success':
            return {"error": f"No se pudo obtener precio óptimo para {signal.symbol}"}
        
        # Crear orden limit inteligente de FUTUROS para SHORT
        order_result = self.connector.create_smart_futures_order(
            symbol=signal.symbol,
            side="SELL",  # Para abrir posición SHORT
            quantity=signal.quantity,
            position_side="SHORT",  # Especificar que es posición SHORT
            price_offset_percent=0.1  # 0.1% offset para mejor ejecución
        )
        
        if order_result.get('status') == 'success':
            self.active_signals[signal.symbol] = signal
            self.signal_history.append(signal)
            
            # Log detallado de la orden
            data = order_result.get('data', {})
            price_data = price_info.get('data', {})
            logger.info(f"Orden SHORT (FUTUROS) limit inteligente ejecutada: {signal.symbol}")
            logger.info(f"  Precio de mercado: {price_data.get('market_price', 'N/A')}")
            logger.info(f"  Precio limit: {data.get('price', 'N/A')}")
            logger.info(f"  Cantidad: {signal.quantity}")
            logger.info(f"  Position Side: SHORT")
            logger.info(f"  Margen: AISLADO (ISOLATED) - Protección contra pérdidas excesivas")
            logger.info(f"  Offset aplicado: 0.1%")
        
        return order_result
    
    def _execute_close_signal(self, signal: TradingSignal) -> Dict:
        """Ejecutar señal de cierre de posición"""
        # Obtener posiciones activas de futuros
        positions = self.connector.get_futures_positions()
        
        if positions.get('status') != 'success':
            return {"error": "No se pudieron obtener posiciones"}
        
        # Buscar posición para cerrar
        for position in positions.get('data', []):
            if position['symbol'] == signal.symbol and abs(float(position['position_amt'])) > 0:
                position_amt = float(position['position_amt'])
                quantity = abs(position_amt)
                
                # Determinar lado de la orden de cierre
                if position_amt > 0:
                    # Posición LONG - cerrar con SELL
                    side = "SELL"
                    position_side = "LONG"
                else:
                    # Posición SHORT - cerrar con BUY
                    side = "BUY"
                    position_side = "SHORT"
                
                # Crear orden de cierre usando futuros
                order_result = self.connector.create_smart_futures_order(
                    symbol=signal.symbol,
                    side=side,
                    quantity=quantity,
                    position_side=position_side,
                    price_offset_percent=0.1
                )
                
                if order_result.get('status') == 'success':
                    if signal.symbol in self.active_signals:
                        del self.active_signals[signal.symbol]
                    logger.info(f"Posición cerrada: {signal.symbol} ({position_side})")
                    logger.info(f"  Cantidad cerrada: {quantity}")
                    logger.info(f"  Lado de cierre: {side}")
                
                return order_result
        
        return {"error": f"No se encontró posición activa para {signal.symbol}"}
    
    def _execute_rebalance_signal(self, signal: TradingSignal) -> Dict:
        """Ejecutar señal de rebalance"""
        # Implementar lógica de rebalance basada en el bot long/short
        # Por ahora, ejecutar como una señal normal
        if signal.quantity > 0:
            return self._execute_long_signal(signal)
        else:
            signal.quantity = abs(signal.quantity)
            signal.signal_type = SignalType.SHORT
            return self._execute_short_signal(signal)
    
    def get_signal_status(self) -> Dict:
        """Obtener estado de las señales"""
        return {
            "active_signals": len(self.active_signals),
            "total_signals": len(self.signal_history),
            "active_symbols": list(self.active_signals.keys())
        }

class LongShortBotAdapter:
    """Adaptador para conectar el bot long/short con el sistema de señales"""
    
    def __init__(self, signal_processor: TradingSignalProcessor):
        self.signal_processor = signal_processor
    
    def process_bot_weights(self, weights: Dict[str, float], metadata: Dict) -> List[Dict]:
        """Procesar pesos del bot long/short y convertirlos en señales"""
        signals = []
        
        for symbol, weight in weights.items():
            if abs(weight) < 0.001:  # Ignorar pesos muy pequeños
                continue
            
            # Determinar tipo de señal
            if weight > 0:
                signal_type = SignalType.LONG
                quantity = abs(weight)  # Ajustar según lógica del bot
            else:
                signal_type = SignalType.SHORT
                quantity = abs(weight)  # Ajustar según lógica del bot
            
            # Crear señal
            signal = TradingSignal(
                symbol=symbol,
                signal_type=signal_type,
                quantity=quantity,
                metadata={
                    "weight": weight,
                    "bot_metadata": metadata,
                    "source": "long_short_bot"
                }
            )
            
            # Procesar señal
            result = self.signal_processor.process_signal(signal)
            signals.append({
                "symbol": symbol,
                "signal_type": signal_type.value,
                "weight": weight,
                "result": result
            })
        
        return signals
    
    def process_rebalance_cycle(self, targets: Dict[str, float], current_positions: Dict[str, float]) -> List[Dict]:
        """Procesar ciclo de rebalance del bot"""
        signals = []
        
        for symbol, target in targets.items():
            current = current_positions.get(symbol, 0.0)
            delta = target - current
            
            if abs(delta) < 0.001:  # Ignorar cambios muy pequeños
                continue
            
            # Determinar tipo de señal
            if delta > 0:
                signal_type = SignalType.LONG
                quantity = delta
            else:
                signal_type = SignalType.SHORT
                quantity = abs(delta)
            
            # Crear señal
            signal = TradingSignal(
                symbol=symbol,
                signal_type=signal_type,
                quantity=quantity,
                metadata={
                    "target": target,
                    "current": current,
                    "delta": delta,
                    "source": "rebalance_cycle"
                }
            )
            
            # Procesar señal
            result = self.signal_processor.process_signal(signal)
            signals.append({
                "symbol": symbol,
                "signal_type": signal_type.value,
                "target": target,
                "current": current,
                "delta": delta,
                "result": result
            })
        
        return signals

def create_signal_from_bot_output(bot_output: Dict) -> TradingSignal:
    """Crear señal desde la salida del bot long/short"""
    # Adaptar según la estructura de salida del bot
    symbol = bot_output.get('symbol')
    weight = bot_output.get('weight', 0.0)
    
    if weight > 0:
        signal_type = SignalType.LONG
    else:
        signal_type = SignalType.SHORT
    
    return TradingSignal(
        symbol=symbol,
        signal_type=signal_type,
        quantity=abs(weight),
        metadata={
            "bot_output": bot_output,
            "source": "long_short_bot"
        }
    )

# API endpoints para el sistema de señales
def create_signals_api():
    """Crear API endpoints para el sistema de señales"""
    from flask import Flask, request, jsonify
    
    app = Flask(__name__)
    signal_processor = TradingSignalProcessor()
    bot_adapter = LongShortBotAdapter(signal_processor)
    
    @app.route('/signals/process', methods=['POST'])
    def process_signal():
        """Procesar una señal de trading"""
        try:
            data = request.json
            signal = TradingSignal(
                symbol=data['symbol'],
                signal_type=SignalType(data['signal_type']),
                quantity=float(data['quantity']),
                price=data.get('price'),
                leverage=data.get('leverage'),
                stop_loss=data.get('stop_loss'),
                take_profit=data.get('take_profit'),
                metadata=data.get('metadata', {})
            )
            
            result = signal_processor.process_signal(signal)
            return jsonify(result)
        
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    
    @app.route('/signals/bot-weights', methods=['POST'])
    def process_bot_weights():
        """Procesar pesos del bot long/short"""
        try:
            data = request.json
            weights = data['weights']
            metadata = data.get('metadata', {})
            
            results = bot_adapter.process_bot_weights(weights, metadata)
            return jsonify({"results": results})
        
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    
    @app.route('/signals/rebalance', methods=['POST'])
    def process_rebalance():
        """Procesar rebalance del bot"""
        try:
            data = request.json
            targets = data['targets']
            current_positions = data.get('current_positions', {})
            
            results = bot_adapter.process_rebalance_cycle(targets, current_positions)
            return jsonify({"results": results})
        
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    
    @app.route('/signals/status', methods=['GET'])
    def get_signal_status():
        """Obtener estado de las señales"""
        return jsonify(signal_processor.get_signal_status())
    
    return app

if __name__ == "__main__":
    # Ejemplo de uso
    signal_processor = TradingSignalProcessor()
    
    # Ejemplo de señal de compra
    signal = TradingSignal(
        symbol="BTCUSDT",
        signal_type=SignalType.LONG,
        quantity=0.001,
        metadata={"source": "test"}
    )
    
    result = signal_processor.process_signal(signal)
    print(f"Resultado: {result}")
    
    # Ejemplo de procesamiento de pesos del bot
    bot_adapter = LongShortBotAdapter(signal_processor)
    
    weights = {
        "BTCUSDT": 0.3,
        "ETHUSDT": -0.2,
        "ADAUSDT": 0.1
    }
    
    results = bot_adapter.process_bot_weights(weights, {"cycle": 1})
    print(f"Resultados del bot: {results}")
