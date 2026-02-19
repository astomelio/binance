from __future__ import annotations

from typing import Dict, List
from datetime import datetime, timezone


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def enrich_with_multi_timeframe(
    rows_1h: List[Dict],
    rows_4h: List[Dict],
    rows_1d: List[Dict],
) -> List[Dict]:
    """
    Enrich 1h data with features from 4h and 1d timeframes.
    This integrates ALL timeframes into the model indirectly.
    """
    # Index 4h and 1d by timestamp for fast lookup
    idx_4h: Dict[str, Dict] = {}
    for r in rows_4h:
        ts = r.get("event_time", "")
        if ts:
            # Round to nearest 4h boundary for matching
            dt = _parse_iso(ts)
            rounded = dt.replace(minute=0, second=0, microsecond=0)
            rounded = rounded.replace(hour=(rounded.hour // 4) * 4)
            key = rounded.isoformat()
            idx_4h[key] = r
    
    idx_1d: Dict[str, Dict] = {}
    for r in rows_1d:
        ts = r.get("event_time", "")
        if ts:
            # Round to day boundary
            dt = _parse_iso(ts)
            rounded = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            key = rounded.isoformat()
            idx_1d[key] = r
    
    # Enrich 1h rows with 4h and 1d features
    enriched: List[Dict] = []
    for r1h in rows_1h:
        r = dict(r1h)
        ts = r.get("event_time", "")
        if not ts:
            enriched.append(r)
            continue
        
        dt = _parse_iso(ts)
        
        # Find matching 4h data (within same 4h window)
        rounded_4h = dt.replace(minute=0, second=0, microsecond=0)
        rounded_4h = rounded_4h.replace(hour=(rounded_4h.hour // 4) * 4)
        key_4h = rounded_4h.isoformat()
        
        if key_4h in idx_4h:
            r4h = idx_4h[key_4h]
            # Add 4h features with prefix
            r["tf4h_alpha_score"] = float(r4h.get("alpha_score", 0) or 0)
            r["tf4h_momentum_score"] = float(r4h.get("momentum_score", 0) or 0)
            r["tf4h_basis_bps"] = float(r4h.get("basis_bps", 0) or 0)
            r["tf4h_funding_rate_8h"] = float(r4h.get("funding_rate_8h", 0) or 0)
            r["tf4h_liquidity_event_score"] = float(r4h.get("liquidity_event_score", 0) or 0)
        else:
            r["tf4h_alpha_score"] = 0.0
            r["tf4h_momentum_score"] = 0.0
            r["tf4h_basis_bps"] = 0.0
            r["tf4h_funding_rate_8h"] = 0.0
            r["tf4h_liquidity_event_score"] = 0.0
        
        # Find matching 1d data (same day)
        rounded_1d = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        key_1d = rounded_1d.isoformat()
        
        if key_1d in idx_1d:
            r1d = idx_1d[key_1d]
            # Add 1d features with prefix
            r["tf1d_alpha_score"] = float(r1d.get("alpha_score", 0) or 0)
            r["tf1d_momentum_score"] = float(r1d.get("momentum_score", 0) or 0)
            r["tf1d_basis_bps"] = float(r1d.get("basis_bps", 0) or 0)
            r["tf1d_funding_rate_8h"] = float(r1d.get("funding_rate_8h", 0) or 0)
            r["tf1d_regime_label"] = str(r1d.get("regime_label", "NEUTRAL") or "NEUTRAL")
        else:
            r["tf1d_alpha_score"] = 0.0
            r["tf1d_momentum_score"] = 0.0
            r["tf1d_basis_bps"] = 0.0
            r["tf1d_funding_rate_8h"] = 0.0
            r["tf1d_regime_label"] = "NEUTRAL"
        
        enriched.append(r)
    
    return enriched
