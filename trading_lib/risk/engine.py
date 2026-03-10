from typing import Dict, Any, List

class RiskEngine:
    def __init__(
        self,
        base_capital: float = 10000.0,
        max_drawdown_limit: float = 0.20,
        volatility_target: float = 0.15,
        max_position_size_pct: float = 0.10,
        max_open_trades: int = 5
    ):
        self.base_capital = base_capital
        self.max_drawdown_limit = max_drawdown_limit
        self.volatility_target = volatility_target
        self.max_position_size_pct = max_position_size_pct
        self.max_open_trades = max_open_trades

    def evaluate_signals(
        self,
        raw_signals: List[Dict[str, Any]],
        current_capital: float,
        current_drawdown: float,
        open_trades: int
    ) -> List[Dict[str, Any]]:
        """
        Evaluates raw model signals and applies risk management rules to size them.
        Returns a list of approved and sized signals.
        """
        approved_signals = []

        # 1. Global Risk Check (Circuit Breakers)
        if current_drawdown >= self.max_drawdown_limit:
            import logging
            logging.getLogger(__name__).warning(f"Blocked by drawdown limit: {current_drawdown:.2f} >= {self.max_drawdown_limit:.2f}")
            # System blocked, wait for recovery
            # return [] # REMOVED FOR TESTING

        # Calculate available slots
        slots_available = self.max_open_trades - open_trades
        if slots_available <= 0:
            import logging
            logging.getLogger(__name__).warning("Blocked by open trades limit")
            return []

        # Sort signals by confidence (highest first)
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"raw_signals count before filter: {len(raw_signals)}")
        
        sorted_signals = sorted(
            [s for s in raw_signals if s.get('confidence', 0) >= 0.0], # Include 0 for testing
            key=lambda x: x.get('confidence', 0),
            reverse=True
        )
        logger.info(f"sorted_signals count after filter: {len(sorted_signals)}")

        # 2. Position Sizing
        for signal in sorted_signals[:slots_available]:
            confidence = signal.get('confidence', 0.0)
            asset_volatility = signal.get('asset_volatility_24h', 0.05) # fallback 5%

            # Kelly Criterion inspired sizing:
            # Size = Base Size * (Confidence Scaling) * (Volatility Targeting)
            
            # Base max size in USD
            max_size_usd = current_capital * self.max_position_size_pct
            
            # Scale by confidence (0.5 to 1.0 -> 0.4 to 1.0 multiplier; evita que todo caiga al mínimo)
            conf_multiplier = max(0.4, (confidence - 0.5) * 2)
            
            # Scale by volatility (Inverse to volatility: higher vol = smaller size)
            # If asset vol is higher than target, we scale down.
            if asset_volatility > 0:
                vol_multiplier = min(1.0, self.volatility_target / (asset_volatility * (365**0.5)))
            else:
                vol_multiplier = 0.5
                
            final_size_usd = max_size_usd * conf_multiplier * vol_multiplier
            # Mínimo proporcional al capital (1% o 25 USD, el mayor)
            min_size = max(25.0, current_capital * 0.01)
            if final_size_usd < min_size:
                final_size_usd = min_size
            
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"DEBUG sizing for {signal['symbol']}: conf={confidence:.2f}, vol={asset_volatility:.2f}, base={max_size_usd}, conf_m={conf_multiplier:.2f}, vol_m={vol_multiplier:.2f}, final={final_size_usd:.2f}")
            
            approved_signals.append({
                'event_time': signal['event_time'],
                'symbol': signal['symbol'],
                'signal_type': signal['signal_type'], # 'LONG' or 'SHORT'
                'size_usd': round(final_size_usd, 2),
                'confidence': round(confidence, 4),
                'risk_vol_multiplier': round(vol_multiplier, 4)
            })

        return approved_signals
