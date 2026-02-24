#!/usr/bin/env python3
"""
Comprueba que la GPU y CUDA estén listos para el entrenamiento AI.
Ejecutar: python scripts/check_gpu_cuda.py
"""
from __future__ import annotations

import os
import subprocess
import sys


def _run(cmd: list[str], timeout: int = 5) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return -1, str(e)


def main() -> int:
    print("=== Verificación GPU / CUDA ===\n")

    # 1) NVIDIA driver / GPU
    code, out = _run(["nvidia-smi"], timeout=10)
    if code == 0:
        print("[OK] nvidia-smi (drivers NVIDIA)")
        for line in out.splitlines():
            if "CUDA Version" in line or "GPU  Name" in line or "NVIDIA" in line.strip():
                print("     ", line.strip())
    else:
        print("[--] nvidia-smi no encontrado o error. Instala drivers NVIDIA.")
        print("     ", out.strip()[:200] if out else "")

    # 2) CUDA Toolkit (nvcc)
    code, out = _run(["nvcc", "--version"], timeout=5)
    if code == 0:
        for line in out.splitlines():
            if "release" in line.lower():
                print("[OK] CUDA Toolkit (nvcc):", line.strip())
                break
        else:
            print("[OK] nvcc disponible")
    else:
        print("[--] nvcc no encontrado. Opcional para XGBoost GPU; para compilar LightGBM GPU puede hacer falta.")
        print("     Descarga: https://developer.nvidia.com/cuda-downloads")

    # 3) LightGBM
    try:
        import lightgbm as lgb  # noqa: F401
        print("[OK] LightGBM", lgb.__version__)
        gpu_ok = False
        try:
            m = lgb.LGBMClassifier(n_estimators=2, device="gpu", verbose=-1)
            import numpy as np
            X = np.random.rand(50, 3).astype(np.float32)
            y = (X[:, 0] > 0.5).astype(int)
            # Redirigir salida LightGBM para capturar "Using GPU Device"
            m.fit(X, y)
            gpu_ok = True
        except Exception as e:
            msg = str(e).strip()
            if "GPU" in msg or "gpu" in msg or "OpenCL" in msg:
                print("     GPU: no (build CPU-only). Para GPU: pip install lightgbm --config-settings=cmake.define.USE_GPU=ON")
            else:
                print("     GPU: error:", msg[:70])
        if gpu_ok:
            print("     GPU: sí (device='gpu' funciona; LightGBM usa OpenCL, puede ser Intel o NVIDIA)")
    except ImportError as e:
        print("[--] LightGBM no instalado:", e)

    # 4) XGBoost
    try:
        import xgboost as xgb  # noqa: F401
        print("[OK] XGBoost", xgb.__version__)
        gpu_ok = False
        try:
            import numpy as np
            X = np.random.rand(50, 3)
            y = (X[:, 0] > 0.5).astype(int)
            m = xgb.XGBClassifier(n_estimators=2, tree_method="hist", device="cuda")
            m.fit(X, y)
            gpu_ok = True
        except Exception as e:
            msg = str(e).strip()
            print("     CUDA/GPU: no -", msg[:75])
        if gpu_ok:
            print("     CUDA/GPU: sí (device='cuda' funciona)")
    except ImportError:
        print("[--] XGBoost no instalado. Opcional: pip install xgboost (para evaluation con GPU)")

    # 5) Variable USE_GPU
    v = os.environ.get("USE_GPU", "")
    print("\nUSE_GPU =", repr(v) if v else "(no definida)")

    print("\n--- Resumen ---")
    print("Si LightGBM o XGBoost marcan GPU/CUDA = sí, puedes usar USE_GPU=1 al entrenar.")
    print("Ver: docs/GPU_CUDA_SETUP.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
