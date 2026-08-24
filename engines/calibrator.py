"""
engines/calibrator.py
Rule #1 core: every threshold comes from THIS asset + THIS timeframe history.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List
from data.providers import Candle
from utils.indicators import atr, percentile
from config import DEFAULTS

class CalibrationError(Exception):
    pass

@dataclass
class AssetTimeframeProfile:
    asset: str
    timeframe: str
    n_candles: int
    atr_series: List[float]
    equal_level_tolerance: float
    median_wick_body_ratio: float
    penetration_depth_atr_p40: float
    penetration_depth_atr_p65: float
    penetration_depth_atr_p80: float
    min_meaningful_distance: float  # absolute price units derived from history
    calibration_window_candles: int = 0
    regime_shift_flag: bool = False
    regime_shift_ratio: float = 1.0
    current_atr: float = 0.0

def calibrate(candles: List[Candle], asset: str, timeframe: str,
              rolling_window: int = None) -> AssetTimeframeProfile:
    if len(candles) < DEFAULTS.min_lookback_candles:
        raise CalibrationError(
            f"Only {len(candles)} closed candles for {asset}/{timeframe}; "
            f"minimum {DEFAULTS.min_lookback_candles} required. "
            f"اطلاعات معتبر برای این بخش موجود نیست و اصلاح انجام نشد."
        )

    window = rolling_window or DEFAULTS.rolling_calibration_window
    recent = candles[-window:] if len(candles) > window else candles
    offset = len(candles) - len(recent)

    atr_series = atr(candles, period=DEFAULTS.atr_period)
    current_atr = atr_series[-1] if atr_series and atr_series[-1] > 0 else 0.0

    # Equal level tolerance from recent High-High / Low-Low deltas
    high_deltas = [abs(recent[i].high - recent[i-1].high) for i in range(1, len(recent))]
    low_deltas = [abs(recent[i].low - recent[i-1].low) for i in range(1, len(recent))]
    combined = high_deltas + low_deltas
    tolerance = percentile(combined, DEFAULTS.equal_level_tolerance_pctile) if combined else 0.0

    # Wick/body
    ratios = []
    for c in recent:
        body = abs(c.close - c.open)
        upper = c.high - max(c.open, c.close)
        lower = min(c.open, c.close) - c.low
        wick = max(upper, lower)
        if body > 1e-12:
            ratios.append(wick / body)
    median_wr = percentile(ratios, 0.5) if ratios else 1.0

    # Historical penetration depths (ATR-normalized)
    penetrations = []
    lookback_extreme = 20
    for i in range(lookback_extreme, len(recent)):
        global_i = offset + i
        w = recent[i - lookback_extreme:i]
        prior_high = max(c.high for c in w)
        prior_low = min(c.low for c in w)
        a = atr_series[global_i] if global_i < len(atr_series) and atr_series[global_i] > 0 else None
        if not a:
            continue
        c = recent[i]
        if c.high > prior_high:
            penetrations.append((c.high - prior_high) / a)
        if c.low < prior_low:
            penetrations.append((prior_low - c.low) / a)

    p40 = percentile(penetrations, DEFAULTS.risk_pct_40) if penetrations else 0.25
    p65 = percentile(penetrations, DEFAULTS.risk_pct_65) if penetrations else 0.45
    p80 = percentile(penetrations, DEFAULTS.risk_pct_80) if penetrations else 0.70

    # Minimum meaningful distance = max of (0.35 * current ATR, small fraction of price)
    last_close = candles[-1].close
    min_dist = max(DEFAULTS.min_distance_atr_fraction * current_atr, last_close * 0.0015)

    # Regime shift detection
    regime_flag = False
    regime_ratio = 1.0
    prior_start = offset - len(recent)
    if prior_start >= 0:
        recent_atr = [v for v in atr_series[offset:offset+len(recent)] if v > 0]
        prior_atr = [v for v in atr_series[prior_start:offset] if v > 0]
        if recent_atr and prior_atr:
            r_mean = sum(recent_atr) / len(recent_atr)
            p_mean = sum(prior_atr) / len(prior_atr)
            if p_mean > 0:
                regime_ratio = r_mean / p_mean
                regime_flag = regime_ratio >= 2.0 or regime_ratio <= 0.5

    return AssetTimeframeProfile(
        asset=asset,
        timeframe=timeframe,
        n_candles=len(candles),
        atr_series=atr_series,
        equal_level_tolerance=tolerance,
        median_wick_body_ratio=median_wr,
        penetration_depth_atr_p40=max(p40, 0.15),
        penetration_depth_atr_p65=max(p65, 0.30),
        penetration_depth_atr_p80=max(p80, 0.50),
        min_meaningful_distance=min_dist,
        calibration_window_candles=len(recent),
        regime_shift_flag=regime_flag,
        regime_shift_ratio=round(regime_ratio, 3),
        current_atr=current_atr,
    )
