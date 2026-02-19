#!/usr/bin/env python3
"""
Ejemplo de Integración - Bot Long/Short + Conector de Binance
Muestra cómo conectar el bot de momentum con el sistema de ejecución inteligente
"""

import time
import json
import requests
from datetime import datetime

def test_connector():
    """Probar que el conector esté funcionando"""
    print("🔍 Probando conector de Binance...")
    
    try:
        response = requests.get("http://localhost:8000/health")
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Conector funcionando: {data}")
            return True
        else:
            print(f"❌ Conector no responde: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error conectando al conector: {e}")
        return False

def test_bot_integrator():
    """Probar el integrador del bot"""
    print("\n🤖 Probando integrador del bot...")
    
    try:
        response = requests.get("http://localhost:5000/bot/status")
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Bot integrado funcionando: {data}")
            return True
        else:
            print(f"❌ Bot integrado no responde: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error conectando al bot: {e}")
        return False

def execute_single_rebalance():
    """Ejecutar un solo ciclo de rebalance"""
    print("\n🔄 Ejecutando rebalance...")
    
    try:
        response = requests.post("http://localhost:5000/bot/rebalance")
        if response.status_code == 200:
            data = response.json()
            print("✅ Rebalance ejecutado:")
            print(json.dumps(data, indent=2))
            return data
        else:
            print(f"❌ Error en rebalance: {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ Error ejecutando rebalance: {e}")
        return None

def get_positions():
    """Obtener posiciones actuales"""
    print("\n📊 Obteniendo posiciones...")
    
    try:
        response = requests.get("http://localhost:5000/bot/positions")
        if response.status_code == 200:
            positions = response.json()
            print("✅ Posiciones actuales:")
            for symbol, amount in positions.items():
                print(f"   {symbol}: {amount}")
            return positions
        else:
            print(f"❌ Error obteniendo posiciones: {response.status_code}")
            return {}
    except Exception as e:
        print(f"❌ Error obteniendo posiciones: {e}")
        return {}

def test_signal_processing():
    """Probar procesamiento de señales"""
    print("\n📡 Probando procesamiento de señales...")
    
    # Ejemplo de señal de compra
    signal_data = {
        "symbol": "BTCUSDT",
        "signal_type": "LONG",
        "quantity": 0.001,
        "metadata": {
            "source": "test",
            "momentum": 0.05
        }
    }
    
    try:
        response = requests.post(
            "http://localhost:5000/signals/process",
            json=signal_data
        )
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Señal procesada:")
            print(json.dumps(result, indent=2))
            return result
        else:
            print(f"❌ Error procesando señal: {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ Error procesando señal: {e}")
        return None

def test_bot_weights():
    """Probar procesamiento de pesos del bot"""
    print("\n⚖️ Probando procesamiento de pesos del bot...")
    
    # Ejemplo de pesos del bot
    weights_data = {
        "weights": {
            "BTCUSDT": 0.3,
            "ETHUSDT": -0.2,
            "ADAUSDT": 0.1,
            "DOTUSDT": -0.15
        },
        "metadata": {
            "cycle": 1,
            "universe_size": 30,
            "timestamp": datetime.now().isoformat()
        }
    }
    
    try:
        response = requests.post(
            "http://localhost:5000/signals/bot-weights",
            json=weights_data
        )
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Pesos del bot procesados:")
            print(json.dumps(result, indent=2))
            return result
        else:
            print(f"❌ Error procesando pesos: {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ Error procesando pesos: {e}")
        return None

def start_bot_continuous():
    """Iniciar bot en modo continuo"""
    print("\n🚀 Iniciando bot en modo continuo...")
    
    try:
        response = requests.post(
            "http://localhost:5000/bot/start",
            json={"rebalance_interval_minutes": 15}
        )
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Bot iniciado:")
            print(json.dumps(result, indent=2))
            return result
        else:
            print(f"❌ Error iniciando bot: {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ Error iniciando bot: {e}")
        return None

def main():
    """Función principal de demostración"""
    print("🎯 DEMOSTRACIÓN - SISTEMA INTEGRADO")
    print("=" * 50)
    
    # 1. Probar conector
    if not test_connector():
        print("❌ El conector no está funcionando. Ejecuta: chalice local")
        return
    
    # 2. Probar bot integrado
    if not test_bot_integrator():
        print("❌ El bot integrado no está funcionando. Ejecuta: python bot_integrator.py --api")
        return
    
    # 3. Obtener posiciones actuales
    positions = get_positions()
    
    # 4. Ejecutar rebalance de prueba
    rebalance_result = execute_single_rebalance()
    
    # 5. Probar procesamiento de señales
    signal_result = test_signal_processing()
    
    # 6. Probar procesamiento de pesos
    weights_result = test_bot_weights()
    
    # 7. Mostrar resumen
    print("\n📋 RESUMEN DE LA DEMOSTRACIÓN")
    print("=" * 30)
    print(f"✅ Conector: Funcionando")
    print(f"✅ Bot integrado: Funcionando")
    print(f"📊 Posiciones activas: {len(positions)}")
    print(f"🔄 Rebalance: {'Exitoso' if rebalance_result else 'Falló'}")
    print(f"📡 Señales: {'Procesadas' if signal_result else 'Falló'}")
    print(f"⚖️ Pesos: {'Procesados' if weights_result else 'Falló'}")
    
    print("\n💡 Para usar en producción:")
    print("1. Configura API keys en .env")
    print("2. Ejecuta: chalice local")
    print("3. Ejecuta: python bot_integrator.py --api")
    print("4. Ejecuta: python example_integration.py")

if __name__ == "__main__":
    main()
