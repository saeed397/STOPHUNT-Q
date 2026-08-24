"""
models/entry_sl_tp.py
Produces the two mandatory groups, each with three risk levels (40/65/80).
All distances derived from the asset's own historical sweep depth distribution.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple
from data.providers import Candle
from engines.sweep_engine import SweepEvent
from engines.structure_engine import StructureConfirmation
from engines.liquidity_engine import LiquidityLevel, LevelStatus
from engines.calibrator import AssetTimeframeProfile

@dataclass
class RiskLevelRow:
    risk_label: str          # "40%", "65%", "80%"
    entry_price: float
    take_profit: float
    stop_loss: float
    rr_actual: float

@dataclass
class SignalGroup:
    mode: str                # "STANDARD" or "STOPHUNT_TRIGGER"
    direction: str           # "BUY" or "SELL"
    rows: List[RiskLevelRow]
    entry_basis: str
    notes: str = ""

def _buffer_for_risk(profile: AssetTimeframeProfile, risk_pct: float) -> float:
    """Return ATR-multiple buffer for the given risk percentile."""
    if risk_pct <= 0.45:
        return profile.penetration_depth_atr_p40
    elif risk_pct <= 0.70:
        return profile.penetration_depth_atr_p65
    else:
        return profile.penetration_depth_atr_p80

def _find_liquidity_target(levels: List[LiquidityLevel], from_price: float,
                           is_buy: bool, from_index: int) -> Tuple[Optional[float], str]:
    candidates = [
        l for l in levels
        if l.status == LevelStatus.ACTIVE
        and l.formed_index <= from_index
        and ((is_buy and l.kind.name.endswith("HIGH") and l.price > from_price)
             or (not is_buy and l.kind.name.endswith("LOW") and l.price < from_price))
    ]
    if not candidates:
        return None, "No opposing liquidity level found; used R:R fallback"
    nearest = min(candidates, key=lambda l: abs(l.price - from_price))
    return nearest.price, f"Nearest opposing liquidity: {nearest.id}"

def build_standard_group(candles: List[Candle], sweep: SweepEvent,
                         confirmation: StructureConfirmation,
                         levels: List[LiquidityLevel],
                         profile: AssetTimeframeProfile,
                         direction: str, rr_target: float) -> Optional[SignalGroup]:
    if not confirmation.confirmed or confirmation.choch_index is None:
        return None

    entry_idx = confirmation.choch_index
    entry_price = candles[entry_idx].close
    is_buy = direction.upper() == "BUY"
    extreme = sweep.extreme_price

    rows: List[RiskLevelRow] = []
    risk_levels = [("40%", 0.40), ("65%", 0.65), ("80%", 0.80)]

    for label, pct in risk_levels:
        atr_mult = _buffer_for_risk(profile, pct)
        buffer = profile.current_atr * atr_mult
        # Enforce minimum meaningful distance
        buffer = max(buffer, profile.min_meaningful_distance)

        if is_buy:
            stop_loss = extreme - buffer
            risk = entry_price - stop_loss
            if risk <= 0:
                continue
            tp_price, _ = _find_liquidity_target(levels, entry_price, True, entry_idx)
            if tp_price is None or tp_price <= entry_price:
                tp_price = entry_price + risk * rr_target
            # Ensure TP is meaningfully above entry
            if tp_price - entry_price < profile.min_meaningful_distance:
                tp_price = entry_price + max(risk * rr_target, profile.min_meaningful_distance * 1.5)
        else:
            stop_loss = extreme + buffer
            risk = stop_loss - entry_price
            if risk <= 0:
                continue
            tp_price, _ = _find_liquidity_target(levels, entry_price, False, entry_idx)
            if tp_price is None or tp_price >= entry_price:
                tp_price = entry_price - risk * rr_target
            if entry_price - tp_price < profile.min_meaningful_distance:
                tp_price = entry_price - max(risk * rr_target, profile.min_meaningful_distance * 1.5)

        rr_actual = abs(tp_price - entry_price) / risk if risk > 0 else 0.0
        rows.append(RiskLevelRow(
            risk_label=label,
            entry_price=round(entry_price, 6),
            take_profit=round(tp_price, 6),
            stop_loss=round(stop_loss, 6),
            rr_actual=round(rr_actual, 2),
        ))

    if not rows:
        return None

    return SignalGroup(
        mode="STANDARD",
        direction=direction.upper(),
        rows=rows,
        entry_basis=f"Close of CHoCH confirmation candle (index {entry_idx})",
        notes="Based on confirmed Sweep → Reclaim → Displacement → CHoCH chain from this asset history.",
    )

def build_stophunt_trigger_group(candles: List[Candle], level: LiquidityLevel,
                                 profile: AssetTimeframeProfile,
                                 levels: List[LiquidityLevel],
                                 direction: str, rr_target: float,
                                 current_index: int) -> Optional[SignalGroup]:
    """
    Pending order exactly at a high-quality unswept liquidity level.
    Activates only when price reaches the level and hunts the stops sitting there.
    """
    if level.status != LevelStatus.ACTIVE:
        return None
    if level.strength < 1.5:  # quality filter
        return None

    is_buy = direction.upper() == "BUY"
    is_low_level = level.kind.name.endswith("LOW")
    # For BUY we place trigger on sell-side liquidity (lows)
    if is_buy and not is_low_level:
        return None
    if not is_buy and is_low_level:
        return None

    trigger_price = level.price
    rows: List[RiskLevelRow] = []
    risk_levels = [("40%", 0.40), ("65%", 0.65), ("80%", 0.80)]

    for label, pct in risk_levels:
        atr_mult = _buffer_for_risk(profile, pct)
        buffer = profile.current_atr * atr_mult
        buffer = max(buffer, profile.min_meaningful_distance)

        if is_buy:
            stop_loss = trigger_price - buffer
            risk = trigger_price - stop_loss
            if risk <= 0:
                continue
            tp_price, _ = _find_liquidity_target(levels, trigger_price, True, current_index)
            if tp_price is None or tp_price <= trigger_price:
                tp_price = trigger_price + risk * rr_target
            if tp_price - trigger_price < profile.min_meaningful_distance:
                tp_price = trigger_price + max(risk * rr_target, profile.min_meaningful_distance * 1.5)
        else:
            stop_loss = trigger_price + buffer
            risk = stop_loss - trigger_price
            if risk <= 0:
                continue
            tp_price, _ = _find_liquidity_target(levels, trigger_price, False, current_index)
            if tp_price is None or tp_price >= trigger_price:
                tp_price = trigger_price - risk * rr_target
            if trigger_price - tp_price < profile.min_meaningful_distance:
                tp_price = trigger_price - max(risk * rr_target, profile.min_meaningful_distance * 1.5)

        rr_actual = abs(tp_price - trigger_price) / risk if risk > 0 else 0.0
        rows.append(RiskLevelRow(
            risk_label=label,
            entry_price=round(trigger_price, 6),
            take_profit=round(tp_price, 6),
            stop_loss=round(stop_loss, 6),
            rr_actual=round(rr_actual, 2),
        ))

    if not rows:
        return None

    return SignalGroup(
        mode="STOPHUNT_TRIGGER",
        direction=direction.upper(),
        rows=rows,
        entry_basis=f"Pending trigger at liquidity level {level.id} ({level.kind.value}). "
                    f"Activates only when price reaches this level and hunts the stops.",
        notes="This is the 'hunt the hunters' entry: order sits where other traders' stops are clustered.",
    )
