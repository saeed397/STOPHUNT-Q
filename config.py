"""
config.py
Central configuration for Liquidity-Centric Stop Hunt Strategy (Strict Version)

Rule compliance:
1. All thresholds are either computed from the specific asset+timeframe history
   or explicitly labeled as provisional defaults to be overridden by calibration.
2. No fabricated data sources.
3. Documented sources only.
4. Dual output groups are mandatory.
"""

from dataclasses import dataclass
from typing import Dict, List

# Timeframe hierarchy
TIMEFRAME_ORDER: List[str] = ["15m", "30m", "1h", "4h", "1d", "1w", "1M"]

HIGHER_TIMEFRAME_MAP: Dict[str, str] = {
    "15m": "1h",
    "30m": "4h",
    "1h": "4h",
    "4h": "1d",
    "1d": "1w",
    "1w": "1M",
    "1M": "1M",
}

# Yahoo Finance documented limits (days)
YF_INTERVAL_LIMITS_DAYS: Dict[str, int] = {
    "15m": 60,
    "30m": 60,
    "60m": 730,
}

RR_OPTIONS: List[str] = ["1:1", "1:1.5", "1:2", "1:3", "1:4", "1:5"]
DEFAULT_RR = "1:2"

COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
TOP_N_ASSETS = 500

@dataclass
class StrategyDefaults:
    """
    Provisional defaults only. All critical thresholds (penetration, tolerance,
    min distances, score cutoffs) MUST be overridden by per-asset calibration
    from real historical data. These exist only as safe starting points.
    """
    min_lookback_candles: int = 400
    rolling_calibration_window: int = 350
    swing_fractal_order: int = 2
    equal_level_tolerance_pctile: float = 0.20
    atr_period: int = 14
    max_setup_age_candles: int = 12

    # Quality filters (balanced strictness)
    min_setup_score: float = 72.0          # Higher = fewer but better signals
    min_level_strength: float = 1.8        # Minimum strength score for a level to be used
    min_distance_atr_fraction: float = 0.35  # Minimum Entry-SL / Entry-TP distance in ATR units
    strong_level_min_touches: int = 2
    medium_level_min_touches: int = 1

    # Risk level percentiles (from historical sweep depth distribution)
    risk_pct_40: float = 0.40
    risk_pct_65: float = 0.65
    risk_pct_80: float = 0.80

DEFAULTS = StrategyDefaults()
