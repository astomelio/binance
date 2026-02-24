# Usar GPU (tarjeta de video) para el entrenamiento AI

Para aprovechar la GPU y aliviar la carga del PC en Optuna, evaluación de modelos y benchmarks.

**Comprobar estado:** ejecuta `python scripts/check_gpu_cuda.py` para ver si nvidia-smi, CUDA, LightGBM GPU y XGBoost CUDA están listos.

---

## Qué usa GPU en este proyecto

| Componente | Modelo | Cómo activa GPU |
|------------|--------|------------------|
| **Optuna tuning** | LightGBM | `USE_GPU=1` o `--use-gpu` |
| **Model evaluation** | LightGBM / XGBoost | `USE_GPU=1` |
| **Benchmark / real model** | LightGBM | `USE_GPU=1` |

- **LightGBM:** usa **OpenCL** (en Windows la GPU NVIDIA se usa vía OpenCL).
- **XGBoost:** usa **CUDA** (necesita CUDA Toolkit instalado).

---

## 1. Requisitos previos

- **Drivers NVIDIA** actualizados.
- **LightGBM con GPU:** compilar con soporte GPU (OpenCL) o usar wheel con GPU si existe para tu entorno.
- **XGBoost con GPU:** instalar **CUDA Toolkit** (p. ej. 11.8 o 12.x) desde [NVIDIA CUDA](https://developer.nvidia.com/cuda-downloads). Añadir al PATH: `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\vX.Y\bin`.

Comprobar CUDA (solo necesario si usas XGBoost en GPU):

```bash
nvcc --version
```

---

## 2. Instalar LightGBM con soporte GPU (OpenCL)

En Windows, LightGBM usa OpenCL para GPU (no CUDA). La GPU NVIDIA funciona con OpenCL.

### Opción A: Pip con compilación GPU (requiere Visual Studio Build Tools + OpenCL)

```bash
pip uninstall lightgbm -y
pip install lightgbm --config-settings=cmake.define.USE_GPU=ON
```

Requisitos: Visual Studio Build Tools con “Desktop development with C++”, y que el sistema tenga OpenCL (los drivers NVIDIA suelen incluirlo).

Si la compilación falla, usa la **Opción B**.

### Opción B: LightGBM estándar (solo CPU)

Si no compila la versión GPU, deja la instalación normal; el código sigue funcionando en CPU:

```bash
pip install lightgbm
```

En ese caso no pongas `USE_GPU=1` para LightGBM (daría error “GPU Tree Learner was not enabled”).

---

## 3. XGBoost con CUDA (opcional)

Para que **model evaluation** use GPU con XGBoost:

1. Instala **CUDA Toolkit** (p. ej. 12.x) y reinicia/verifica `nvcc`.
2. Instala XGBoost (suele detectar CUDA si está en el PATH):

```bash
pip install xgboost
```

En muchos entornos el wheel de PyPI ya incluye soporte CUDA. Si no, en la [doc de XGBoost](https://xgboost.readthedocs.io/en/stable/install.html) indican builds con CUDA.

---

## 4. Activar GPU en ejecución

**Variable de entorno (recomendado):**

```bash
# Windows (PowerShell)
$env:USE_GPU = "1"

# Windows (cmd)
set USE_GPU=1

# Linux/macOS
export USE_GPU=1
```

Luego ejecuta los scripts como siempre:

```bash
make quant-optuna
# o
python examples/quant_optuna_tuning.py --trials 50
```

**Solo Optuna (CLI):**

```bash
python examples/quant_optuna_tuning.py --use-gpu --trials 50
```

---

## 5. Verificación rápida (recomendado)

Ejecuta en la raíz del proyecto:

```bash
python scripts/check_gpu_cuda.py
```

Muestra: nvidia-smi, CUDA (nvcc), LightGBM con device='gpu', XGBoost con device='cuda' y si USE_GPU está definida.

**Nota:** LightGBM usa **OpenCL**; en PCs con NVIDIA + Intel integrada puede elegir la Intel. Para usar la **NVIDIA** en entrenamiento, instala XGBoost y usa `USE_GPU=1` en la evaluación (XGBoost sí usa CUDA → NVIDIA). Opcionalmente en LightGBM puedes probar `gpu_device_id` para forzar otro dispositivo OpenCL.

---

## 6. Versión CUDA (driver vs Toolkit)

Si `nvidia-smi` muestra "CUDA Version: 12.x" pero `nvcc --version` es 10.1, tienes un **Toolkit antiguo**. Para XGBoost con GPU suele ir bien CUDA 11 o 12. Puedes instalar un CUDA Toolkit más reciente desde NVIDIA y dejar que XGBoost use esa versión; el driver ya soporta versiones superiores. No es obligatorio: si con 10.1 XGBoost no usa GPU, actualiza el Toolkit.

## 7. Resumen

| Objetivo | Acción |
|----------|--------|
| Entrenar más rápido con la GPU | Instalar LightGBM con GPU (OpenCL) y/o XGBoost con CUDA; poner `USE_GPU=1` o `--use-gpu` en Optuna. |
| Usar la NVIDIA (no la Intel) | LightGBM usa OpenCL y puede elegir la Intel integrada; **XGBoost con CUDA** usa la NVIDIA. Instala `pip install xgboost` y en evaluation con `USE_GPU=1` usará la GTX/RTX. |
| Sin compilar nada | Mantener `pip install lightgbm`; si tu build ya tiene GPU (OpenCL), `USE_GPU=1` funciona. Si no, no pongas USE_GPU. |

Los scripts ya leen `USE_GPU` y pasan `device='gpu'` (LightGBM) o `device='cuda'` (XGBoost) cuando está activado.
