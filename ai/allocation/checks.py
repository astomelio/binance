"""
Comprobaciones antes de backtest/suite para evitar errores silenciosos.
- alpha_score: si la estrategia usa alpha_score y la columna está vacía o a 0 en casi todas las filas,
  estás "optimizando el vacío". Assert o warning explícito.
"""

from __future__ import annotations


def check_alpha_score_coverage(
    rows: list[dict],
    score_key: str = "alpha_score",
    min_fraction_non_null: float = 0.05,
    min_fraction_non_zero: float = 0.02,
    raise_on_fail: bool = False,
) -> tuple[bool, dict]:
    """
    Comprueba que alpha_score (u otra columna de score) tenga cobertura suficiente.
    Evita confundir "el modelo no aporta señal" con "el modelo funciona mal" cuando
    en realidad la columna estaba vacía.

    Returns:
        (ok, stats): ok=False si hay demasiadas filas con score null o 0.
        stats: total, non_null_count, non_zero_count, fraction_non_null, fraction_non_zero.
    Si raise_on_fail=True y ok=False, lanza AssertionError.
    """
    if not rows:
        return False, {"total": 0, "non_null_count": 0, "non_zero_count": 0, "fraction_non_null": 0.0, "fraction_non_zero": 0.0}
    total = len(rows)
    non_null = 0
    non_zero = 0
    for r in rows:
        v = r.get(score_key)
        if v is not None:
            non_null += 1
            try:
                if float(v) != 0.0:
                    non_zero += 1
            except (TypeError, ValueError):
                pass
    frac_null = non_null / total if total else 0.0
    frac_zero = non_zero / total if total else 0.0
    stats = {
        "total": total,
        "non_null_count": non_null,
        "non_zero_count": non_zero,
        "fraction_non_null": frac_null,
        "fraction_non_zero": frac_zero,
    }
    ok = frac_null >= min_fraction_non_null and frac_zero >= min_fraction_non_zero
    if not ok and raise_on_fail:
        raise AssertionError(
            f"alpha_score coverage too low: {score_key} non_null={frac_null:.2%} (min {min_fraction_non_null:.0%}), "
            f"non_zero={frac_zero:.2%} (min {min_fraction_non_zero:.0%}). "
            "Rellena con enrich_rows_with_model() o no uses estrategia alpha_score."
        )
    return ok, stats


def warn_alpha_score_if_low(
    rows: list[dict],
    score_key: str = "alpha_score",
    min_fraction_non_zero: float = 0.02,
) -> None:
    """
    Si la fracción de filas con score no cero está por debajo del mínimo, imprime warning.
    No lanza; para fallar en CI/suite usar check_alpha_score_coverage(..., raise_on_fail=True).
    """
    ok, stats = check_alpha_score_coverage(
        rows,
        score_key=score_key,
        min_fraction_non_null=0.05,
        min_fraction_non_zero=min_fraction_non_zero,
        raise_on_fail=False,
    )
    if not ok:
        import warnings
        warnings.warn(
            f"alpha_score coverage low: {stats['non_zero_count']}/{stats['total']} rows with non-zero {score_key} "
            f"({stats['fraction_non_zero']:.1%}). You may be evaluating an empty column. "
            "Use --use-champion to fill from MLflow or enrich_rows_with_model().",
            UserWarning,
            stacklevel=2,
        )
