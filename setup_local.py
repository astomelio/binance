#!/usr/bin/env python3
"""
Script de configuración para pruebas locales del Conector de Binance
"""

import os
import sys
from pathlib import Path

def print_banner():
    """Imprimir banner del setup"""
    print("=" * 60)
    print("🚀 CONFIGURACIÓN LOCAL - CONECTOR DE BINANCE")
    print("=" * 60)

def check_env_file():
    """Verificar si existe el archivo .env"""
    env_file = Path('.env')
    if env_file.exists():
        print("✅ Archivo .env encontrado")
        return True
    else:
        print("❌ Archivo .env no encontrado")
        return False

def create_env_file():
    """Crear archivo .env desde template"""
    print("\n📝 Creando archivo .env...")
    
    env_content = """# Binance API Configuration
BINANCE_API_KEY=your_api_key_here
BINANCE_SECRET_KEY=your_secret_key_here

# Optional: Testnet configuration (RECOMMENDED for testing)
BINANCE_TESTNET=true
"""
    
    with open('.env', 'w') as f:
        f.write(env_content)
    
    print("✅ Archivo .env creado")

def get_api_keys():
    """Obtener API keys del usuario"""
    print("\n🔑 CONFIGURACIÓN DE API KEYS")
    print("-" * 40)
    
    print("¿Dónde quieres obtener tus API keys?")
    print("1. Binance Testnet (RECOMENDADO para pruebas)")
    print("2. Binance Real (SOLO para producción)")
    
    choice = input("\nSelecciona una opción (1 o 2): ").strip()
    
    if choice == "1":
        print("\n📋 Pasos para Testnet:")
        print("1. Ve a https://testnet.binance.vision/")
        print("2. Crea una cuenta de prueba")
        print("3. Genera API keys de prueba")
        print("4. Copia las keys aquí")
        
        api_key = input("\n🔑 API Key: ").strip()
        secret_key = input("🔐 Secret Key: ").strip()
        
        # Actualizar .env
        update_env_file(api_key, secret_key, testnet=True)
        
    elif choice == "2":
        print("\n⚠️  ADVERTENCIA: Usarás dinero real!")
        print("Asegúrate de:")
        print("- Tener fondos en tu cuenta")
        print("- Entender los riesgos")
        print("- Configurar solo los permisos necesarios")
        
        confirm = input("\n¿Estás seguro? (escribe 'SI' para confirmar): ").strip()
        
        if confirm.upper() == 'SI':
            print("\n📋 Pasos para Binance Real:")
            print("1. Ve a https://binance.com")
            print("2. Ve a Profile → API Management")
            print("3. Crea una nueva API key")
            print("4. Configura permisos:")
            print("   ✅ Spot & Margin Trading")
            print("   ✅ Futures (para futuros)")
            print("   ✅ Reading")
            print("   ❌ Withdraw (no recomendado)")
            print("5. Copia las keys aquí")
            
            api_key = input("\n🔑 API Key: ").strip()
            secret_key = input("🔐 Secret Key: ").strip()
            
            # Actualizar .env
            update_env_file(api_key, secret_key, testnet=False)
        else:
            print("❌ Configuración cancelada")
            return False
    else:
        print("❌ Opción inválida")
        return False
    
    return True

def update_env_file(api_key, secret_key, testnet=True):
    """Actualizar archivo .env con las API keys"""
    env_content = f"""# Binance API Configuration
BINANCE_API_KEY={api_key}
BINANCE_SECRET_KEY={secret_key}

# Optional: Testnet configuration
BINANCE_TESTNET={'true' if testnet else 'false'}
"""
    
    with open('.env', 'w') as f:
        f.write(env_content)
    
    print("✅ Archivo .env actualizado")

def test_connection():
    """Probar la conexión con Binance"""
    print("\n🧪 Probando conexión con Binance...")
    
    try:
        # Importar después de configurar .env
        from dotenv import load_dotenv
        load_dotenv()
        
        from app import get_binance_client
        client = get_binance_client()
        
        # Probar conexión
        account_info = client.get_account()
        print("✅ Conexión exitosa!")
        print(f"   Cuenta: {account_info.get('canTrade', 'N/A')}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        print("\n💡 Posibles soluciones:")
        print("1. Verifica que las API keys sean correctas")
        print("2. Asegúrate de que tengan los permisos necesarios")
        print("3. Si usas testnet, verifica que las keys sean del testnet")
        return False

def install_dependencies():
    """Instalar dependencias"""
    print("\n📦 Instalando dependencias...")
    
    try:
        import subprocess
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'], check=True)
        print("✅ Dependencias instaladas")
        return True
    except Exception as e:
        print(f"❌ Error instalando dependencias: {e}")
        return False

def run_local_server():
    """Ejecutar servidor local"""
    print("\n🚀 Iniciando servidor local...")
    print("💡 El servidor estará disponible en: http://localhost:8000")
    print("💡 Presiona Ctrl+C para detener")
    
    try:
        import subprocess
        subprocess.run(['chalice', 'local'], check=True)
    except KeyboardInterrupt:
        print("\n👋 Servidor detenido")
    except Exception as e:
        print(f"❌ Error iniciando servidor: {e}")

def main():
    """Función principal"""
    print_banner()
    
    # Verificar archivo .env
    if not check_env_file():
        create_env_file()
    
    # Instalar dependencias
    if not install_dependencies():
        print("❌ No se pudieron instalar las dependencias")
        return
    
    # Configurar API keys
    if get_api_keys():
        # Probar conexión
        if test_connection():
            print("\n🎉 ¡Configuración completada!")
            print("\n📋 Próximos pasos:")
            print("1. Ejecutar: python setup_local.py --run")
            print("2. Probar endpoints en: http://localhost:8000")
            print("3. Ver documentación en README.md")
            
            # Preguntar si quiere ejecutar el servidor
            run_now = input("\n¿Quieres ejecutar el servidor ahora? (y/n): ").strip().lower()
            if run_now == 'y':
                run_local_server()
        else:
            print("\n❌ No se pudo conectar a Binance")
            print("Revisa tu configuración e intenta de nuevo")
    else:
        print("\n❌ Configuración incompleta")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--run":
        run_local_server()
    else:
        main()
