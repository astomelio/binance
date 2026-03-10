@echo off
:: Sincroniza la hora de Windows con internet (necesario para Binance API -1021).
:: Ejecutar como Administrador: clic derecho en el .bat -> "Ejecutar como administrador"

echo Iniciando servicio de hora (W32Time)...
net start w32time 2>nul
echo Sincronizando hora con servidor NTP...
w32tm /resync
if %errorlevel% neq 0 (
    echo.
    echo Si falla: abre "Configuracion" - Hora e idioma - Sincronizar ahora.
    echo O en una consola como Administrador: w32tm /resync
    pause
    exit /b 1
)
echo OK. Hora sincronizada.
echo.
echo Reinicia el contenedor API para que use la hora nueva:
echo   docker compose -f docker-compose.run.yml up -d --force-recreate api
echo.
pause
