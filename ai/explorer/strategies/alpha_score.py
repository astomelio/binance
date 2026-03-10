"""Estrategia alpha_score: composite ML (basis + funding + momentum)."""

from ai.allocation.strategies import compute_allocations

from ai.explorer.types import StrategyDef


def _build_compute_fn(rows: list, params: dict):
    lt = params.get("long_threshold", 0.10)
    st = params.get("short_threshold", -0.10)
    min_a = params.get("min_allocation", 0.1)
    max_a = params.get("max_allocation", 0.4)
    vt = params.get("volatility_target", 0.15)
    
    # Pesos dinámicos (si no están, usa los del SQL por defecto)
    w_micro = params.get("w_micro", 0.35)
    w_momentum = params.get("w_momentum", 0.20)
    w_session = params.get("w_session", 0.10)
    w_liquidity = params.get("w_liquidity", 0.10)
    w_sentiment = params.get("w_sentiment", 0.10) # Suma de news + grok
    w_extra = params.get("w_extra", 0.15) # Suma de cross_exchange + dex + depth

    def fn(features_by_symbol: dict, event_time: str):
        # Recalcular alpha_score dinámicamente si hay pesos en params
        dynamic_features = {}
        for sym, f in features_by_symbol.items():
            f_copy = dict(f)
            # Solo recalculamos si tenemos los componentes
            if "alpha_microstructure_score" in f_copy:
                # Normalización de pesos para que sumen 1 (por si el optimizer prueba locuras)
                total_w = w_micro + w_momentum + w_session + w_liquidity + w_sentiment + w_extra
                wm = w_micro / total_w
                wmo = w_momentum / total_w
                ws = w_session / total_w
                wl = w_liquidity / total_w
                wse = w_sentiment / total_w
                we = w_extra / total_w

                score = (
                    float(f_copy.get("alpha_microstructure_score", 0) or 0) * wm +
                    float(f_copy.get("momentum_score", 0) or 0) * wmo +
                    float(f_copy.get("session_overlap_score", 0) or 0) * ws +
                    float(f_copy.get("liquidity_event_score", 0) or 0) * wl +
                    (float(f_copy.get("sentiment_score_1h", 0) or 0) * 0.5 + float(f_copy.get("grok_x_sentiment_1h", 0) or 0) * 0.5) * wse +
                    (float(f_copy.get("cross_exchange_score", 0) or 0) * 0.33 + 
                     float(f_copy.get("dex_alpha_score", 0) or 0) * 0.33 + 
                     (1.0 - float(f_copy.get("depth_imbalance_score", 0) or 0)) * 0.33) * we
                )
                f_copy["alpha_score"] = score
            dynamic_features[sym] = f_copy

        return compute_allocations(
            dynamic_features,
            long_threshold=lt,
            short_threshold=st,
            min_allocation=min_a,
            max_allocation=max_a,
            volatility_target=vt,
            max_exposure=1.0,
        )
    return fn


alpha_score_strategy = StrategyDef(
    id="alpha_score",
    name="Alpha Score (composite)",
    description="Basis + funding + momentum + microstructure. Dynamic weights for components.",
    default_params={
        "long_threshold": 0.10,
        "short_threshold": -0.10,
        "min_allocation": 0.1,
        "max_allocation": 0.4,
        "volatility_target": 0.15,
        "w_micro": 0.35,
        "w_momentum": 0.20,
        "w_session": 0.10,
        "w_liquidity": 0.10,
        "w_sentiment": 0.10,
        "w_extra": 0.15,
    },
    param_ranges={
        "long_threshold": [0.10, 0.15, 0.20],
        "short_threshold": [-0.20, -0.15, -0.10],
        "volatility_target": [0.12, 0.15, 0.20],
        "w_micro": [0.20, 0.35, 0.50],
        "w_momentum": [0.10, 0.20, 0.35],
        "w_session": [0.05, 0.10, 0.15],
        "w_liquidity": [0.05, 0.10, 0.20],
        "w_sentiment": [0.05, 0.10, 0.20],
    },
    build_compute_fn=_build_compute_fn,
)
