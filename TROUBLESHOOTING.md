# Por qué se apaga el sistema (contenedores Docker)

## Causas habituales

### 1. Docker Desktop se duerme o se cierra
- **Qué pasa**: Si el PC entra en suspensión o cierras Docker Desktop, los contenedores se paran.
- **Qué hacer**: Mantén Docker Desktop abierto y evita suspender el PC si quieres que el stack siga corriendo.

### 2. Fallo de montaje de volúmenes (Windows)
- **Qué pasa**: Si `LAKE_ROOT_HOST` apunta a una ruta que no existe o es incorrecta, el contenedor puede fallar al arrancar.
- **Qué hacer**:
  - Crea `data_lake` en la raíz del proyecto: `mkdir data_lake`
  - O define en `.env`: `LAKE_ROOT_HOST=C:\binance\data_lake` (ruta absoluta)
  - Usa `.\scripts\start-stack.ps1` para arrancar (crea `data_lake` si falta)

### 3. Puerto 8000 o 3000 ocupado
- **Qué pasa**: Si otro proceso usa el puerto, el contenedor no arranca.
- **Qué hacer**: `docker compose down --remove-orphans` y vuelve a levantar.

### 4. Falta de memoria o disco
- **Qué pasa**: Docker puede matar contenedores si hay poco RAM o disco.
- **Qué hacer**: Libera espacio y aumenta recursos en Docker Desktop (Settings → Resources).

### 5. Contenedores parados manualmente
- **Qué pasa**: `docker compose down` o parar contenedores a mano.
- **Qué hacer**: `docker compose up -d` o `.\scripts\start-stack.ps1` para volver a arrancar.

### 6. Muchos jobs simultáneos → se queda sin RAM
- **Qué pasa**: API con 2 workers + Dagster (daemon + webserver) + varios runs en paralelo = OOM.
- **Qué hacer**: Ya está ajustado: API 1 worker, Dagster `max_concurrent_runs: 1`. Si sigue fallando, sube RAM en Docker Desktop.

### 7. Sobrecarga de I/O en Windows (WSL2 Vmmem)
- **Qué pasa**: Compartir archivos `.py` entre Windows y Docker (con `.:/app`) obliga a WSL2 a leer miles de archivos por red (9p). Esto pone la CPU al 100%, causa que Dagster no envíe "heartbeats" (y se reinicie el daemon) y consume RAM infinita hasta crashear.
- **Qué hacer**: El `docker-compose.yml` se ha modificado para montar SÓLO los `artifacts` y el `data_lake`. **Recuerda:** ahora si modificas un archivo `.py`, DEBES usar `.\scripts\start-stack.ps1` (que incluye `--build`) para aplicar el código nuevo.

---

## Comandos útiles

```powershell
# Ver estado de contenedores
docker compose ps -a

# Ver logs (últimos errores)
docker compose logs --tail=50

# Reiniciar todo
docker compose down --remove-orphans
.\scripts\start-stack.ps1
```
