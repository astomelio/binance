#!/bin/bash

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Configurando Conector de Binance...${NC}"

# Verificar si Python está instalado
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 no está instalado. Por favor instala Python 3.9 o superior.${NC}"
    exit 1
fi

# Verificar si pip está instalado
if ! command -v pip &> /dev/null; then
    echo -e "${RED}❌ pip no está instalado. Por favor instala pip.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Python y pip están instalados${NC}"

# Crear entorno virtual si no existe
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}📦 Creando entorno virtual...${NC}"
    python3 -m venv venv
fi

# Activar entorno virtual
echo -e "${YELLOW}🔧 Activando entorno virtual...${NC}"
source venv/bin/activate

# Instalar dependencias
echo -e "${YELLOW}📚 Instalando dependencias...${NC}"
pip install -r requirements.txt

# Crear archivo .env si no existe
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}📝 Creando archivo .env...${NC}"
    cp env.example .env
    echo -e "${GREEN}✅ Archivo .env creado${NC}"
    echo -e "${YELLOW}⚠️  IMPORTANTE: Edita el archivo .env con tus credenciales de Binance${NC}"
else
    echo -e "${GREEN}✅ Archivo .env ya existe${NC}"
fi

# Verificar si Chalice está instalado
if ! command -v chalice &> /dev/null; then
    echo -e "${YELLOW}📦 Instalando Chalice CLI...${NC}"
    pip install chalice
fi

echo -e "${GREEN}✅ Configuración completada!${NC}"
echo -e "${BLUE}📋 Próximos pasos:${NC}"
echo -e "1. ${YELLOW}Edita el archivo .env con tus credenciales de Binance${NC}"
echo -e "2. ${YELLOW}Para ejecutar localmente:${NC} make run"
echo -e "3. ${YELLOW}Para ejecutar tests:${NC} make test"
echo -e "4. ${YELLOW}Para ver todos los comandos disponibles:${NC} make help"

# Preguntar si quiere ejecutar tests
read -p "¿Quieres ejecutar los tests ahora? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}🧪 Ejecutando tests...${NC}"
    make test
fi

# Preguntar si quiere ejecutar el servidor
read -p "¿Quieres ejecutar el servidor ahora? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}🚀 Iniciando servidor...${NC}"
    echo -e "${GREEN}✅ Servidor disponible en: http://localhost:8000${NC}"
    echo -e "${YELLOW}💡 Presiona Ctrl+C para detener el servidor${NC}"
    make run
fi

echo -e "${GREEN}🎉 ¡Configuración completada!${NC}"
