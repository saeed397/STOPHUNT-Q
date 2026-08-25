"""
engines/stophunt_engine.py
Top-level orchestrator. Enforces the layered architecture and dual output groups.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional

from data.providers import MultiProviderOHLC
from data.validator import validate_candles, DataQualityReport
from engines.calibrator import calibrate, AssetTimeframeProfile, CalibrationError
from engines.liquidity_engine import (
    detect_swings, build_liquidity_levels, add_periodic_levels,
    select_medium_strong_levels, LiquidityLevel, LevelStatus
)
from engines.sweep_engine import scan_for_sweeps, SweepEvent
from engines.structure_engine import confirm_structure, StructureConfirmation
from models.entry_sl_tp import (
    build_standard_group, build_stophunt_trigger_group, SignalGroup
)
from models.setup_score import score_setup
from config import HIGHER_TIMEFRAME_MAP, DEFAULTS

class SignalEngineError(Exception):
    pass

@dataclass
class EngineResult:
    asset: str
    timeframe: str
    higher_timeframe: str
    current_price: float
    direction: str
    data_quality: DataQualityReport
    profile: AssetTimeframeProfile
    medium_levels: List[LiquidityLevel] = field(default_factory=list)
    strong_levels: List[LiquidityLevel] = field(default_factory=list)
    standard_group: Optional[SignalGroup] = None
    stophunt_group: Optional[SignalGroup] = None
    notes: List[str] = field(default_factory=list)
    data_source: str = ""

def run_signal_engine(asset: str, coingecko_id: str, quote: str, timeframe: str,
                      direction: str, rr_target: float,
                      provider: MultiProviderOHLC,
                      lookback: int = 1000,
                      calibration_window: int = None) -> EngineResult:
    notes: List[str] = []
    higher_tf = HIGHER_TIMEFRAME_MAP.get(timeframe, timeframe)

    batch = provider.get_ohlcv(asset, coingecko_id, quote, timeframe, desired_candle_count=lookback)
    if batch.note:
        notes.append(batch.note)

    candles, quality = validate_candles(
        batch.candles, asset, timeframe,
        actual_interval_seconds=batch.actual_interval_seconds
    )
    if quality.gaps:
        notes.append(f"{len(quality.gaps)} data gap(s) detected and excluded.")
    if quality.ohlc_violations:
        notes.append(f"{quality.ohlc_violations} candle(s) failed OHLC checks and were dropped.")

    try:
        profile = calibrate(candles, asset, timeframe, rolling_window=calibration_window)
    except CalibrationError as e:
        raise SignalEngineError(str(e)) from e

    if profile.regime_shift_flag:
        notes.append(
            f"⚠️ تغییر رژیم نوسان: ATR اخیر {profile.regime_shift_ratio}x نسبت به دوره قبل تغییر کرده. "
            f"آستانه‌ها با داده تازه کالیبره شده‌اند."
        )

    # Prefer a fresh real-time price from CoinGecko for display.
    # Fall back to last closed candle if CoinGecko is unavailable.
    current_price = candles[-1].close
    try:
        from data.providers import CoinGeckoProvider
        cg = CoinGeckoProvider()
        live_price = cg.get_simple_price(coingecko_id, quote)
        if live_price and live_price > 0:
            current_price = live_price
            notes.append(f"قیمت لحظه‌ای از CoinGecko گرفته شد ({live_price:.4f}).")
    except Exception as e:
        notes.append(f"قیمت لحظه‌ای از آخرین کندل Yahoo/CoinGecko استفاده شد (خطا در دریافت زنده: {e}).")

    is_buy = direction.upper() in ("BUY", "BOTH")

    swings = detect_swings(candles)
    levels = build_liquidity_levels(swings, profile)
    levels = add_periodic_levels(candles, levels)

    # Select clean medium / strong levels
    medium, strong = select_medium_strong_levels(
        levels, current_price, is_buy=(direction.upper() != "SELL"), profile=profile
    )

    sweeps = scan_for_sweeps(candles, levels, profile)

    # Build Standard group from the best confirmed setup
    standard_group = None
    directions_to_try = ["BUY", "SELL"] if direction.upper() == "BOTH" else [direction.upper()]

    for sweep in sweeps:
        conf = confirm_structure(candles, swings, sweep, profile, DEFAULTS.max_setup_age_candles)
        if not conf.confirmed:
            continue
        level = next((l for l in levels if l.id == sweep.level_id), None)
        if level is None:
            continue
        implied_dir = "BUY" if level.kind.name.endswith("LOW") else "SELL"
        if implied_dir not in directions_to_try:
            continue
        score = score_setup(level, sweep, conf)
        if score["total"] < DEFAULTS.min_setup_score:
            continue
        grp = build_standard_group(candles, sweep, conf, levels, profile, implied_dir, rr_target)
        if grp:
            standard_group = grp
            break  # take the first high-quality confirmed setup

    # Build StopHunt Trigger group from best active high-strength level
    stophunt_group = None
    active_levels = [l for l in levels if l.status == LevelStatus.ACTIVE and l.strength >= 1.5]
    active_levels = sorted(active_levels, key=lambda l: -l.strength)

    for level in active_levels:
        for d in directions_to_try:
            grp = build_stophunt_trigger_group(
                candles, level, profile, levels, d, rr_target, current_index=len(candles)-1
            )
            if grp:
                stophunt_group = grp
                break
        if stophunt_group:
            break

    if not standard_group and not stophunt_group:
        notes.append("No qualifying high-quality setups found at this time — no signal fabricated.")

    return EngineResult(
        asset=asset,
        timeframe=timeframe,
        higher_timeframe=higher_tf,
        current_price=current_price,
        direction=direction.upper(),
        data_quality=quality,
        profile=profile,
        medium_levels=medium,
        strong_levels=strong,
        standard_group=standard_group,
        stophunt_group=stophunt_group,
        notes=notes,
        data_source=batch.source,
    )
