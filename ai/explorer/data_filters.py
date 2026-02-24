"""
Filtros para exploración y optimización: sesión (horas), conjuntos de activos.
"""

from __future__ import annotations

from collections import defaultdict


def filter_rows_by_session(
    rows: list[dict],
    start_hour_utc: int = 0,
    end_hour_utc: int = 24,
) -> list[dict]:
    """
    Filtra filas por hora UTC del event_time (inclusive).
    start_hour_utc=8, end_hour_utc=16 -> solo barras entre 08:00 y 16:59 UTC.
    """
    if start_hour_utc <= end_hour_utc:
        def ok(ts: str) -> bool:
            if not ts or "T" not in ts:
                return True
            try:
                h = int(ts.split("T")[1][:2])
                return start_hour_utc <= h <= end_hour_utc
            except (ValueError, IndexError):
                return True
    else:
        # Cruzar medianoche: 22 a 06 -> 22,23,0,1,...,6
        def ok(ts: str) -> bool:
            if not ts or "T" not in ts:
                return True
            try:
                h = int(ts.split("T")[1][:2])
                return h >= start_hour_utc or h <= end_hour_utc
            except (ValueError, IndexError):
                return True
    return [r for r in rows if ok(r.get("event_time", ""))]


def get_top_symbols_by_volume(
    rows: list[dict],
    top_n: int,
    volume_key: str = "quote_volume_24h",
) -> list[str]:
    """Devuelve los top_n símbolos por volumen medio (USD) en los datos."""
    by_sym: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        sym = r.get("symbol", "")
        if not sym:
            continue
        v = r.get(volume_key)
        if v is not None:
            try:
                by_sym[sym].append(float(v))
            except (TypeError, ValueError):
                pass
    # Media por símbolo
    avg_by_sym = [(s, sum(v) / len(v)) for s, v in by_sym.items() if v]
    avg_by_sym.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in avg_by_sym[:top_n]]


def get_symbol_set(
    rows: list[dict],
    kind: str,
    top_n: int | None = None,
) -> list[str] | None:
    """
    kind: "all" -> None (todos).
    "top20", "top50", "top100" -> esos símbolos por volumen.
    "topN" con top_n dado -> top_n símbolos.
    """
    if kind == "all" or kind == "":
        return None
    if kind.startswith("top"):
        n = top_n
        if n is None and kind != "top":
            try:
                n = int(kind.replace("top", ""))
            except ValueError:
                n = 20
        if n is None:
            n = 20
        return get_top_symbols_by_volume(rows, n)
    return None
