"""
models/entry_sl_tp.py
Produces the two mandatory groups, each with three risk levels (40/65/80).

CORE PHILOSOPHY (strictly enforced):
- All distances, buffers and targets are derived ONLY from the historical
  behavior of the specific asset + timeframe (via AssetTimeframeProfile).
- No artificial forced multipliers or hard-coded R:R that override the
  asset's own history.
- Take-Profit priority: real opposing liquidity levels from the same asset.
- Stop-Loss priority: beyond the actual sweep extreme + buffer taken from
  the asset's own penetration-depth distribution.
- If the historical distribution produces close values, the rows will be
  close — this is accepted as reflection of reality, not a bug.
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
    """
    Return ATR-multiple buffer taken directly from the asset's own
    historical penetration-depth percentiles.
    No artificial widening is applied here.
    """
    if risk_pct <= 0.45:
        return max(profile.penetration_depth_atr_p40, 0.0)
    elif risk_pct <= 0.70:
        return max(profile.penetration_depth_atr_p65, 0.0)
    else:
        return max(profile.penetration_depth_atr_p80, 0.0)

def _find_liquidity_targets(levels: List[LiquidityLevel], from_price: float,
                            is_buy: bool, from_index: int) -> List[float]:
    """Return opposing liquidity prices sorted by distance (nearest first).
    Only real levels that exist in the data are returned.
    """
    candidates = [
        l.price for l in levels
        if l.status == LevelStatus.ACTIVE
        and l.formed_index <= from_index
        and ((is_buy and l.kind.name.endswith("HIGH") and l.price > from_price)
             or (not is_buy and l.kind.name.endswith("LOW") and l.price < from_price))
    ]
    if not candidates:
        return []
    # unique and sorted by distance from entry
    return sorted(set(candidates), key=lambda p: abs(p - from_price))

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

    # Real opposing liquidity targets from the same asset data
    tp_candidates = _find_liquidity_targets(levels, entry_price, is_buy, entry_idx)

    rows: List[RiskLevelRow] = []
    risk_levels = [("40%", 0.40), ("65%", 0.65), ("80%", 0.80)]

    for idx, (label, pct) in enumerate(risk_levels):
        atr_mult = _buffer_for_risk(profile, pct)
        buffer = profile.current_atr * atr_mult

        # Only enforce the asset's own historically-derived minimum distance
        # (never a number invented by us)
        if buffer < profile.min_meaningful_distance:
            buffer = profile.min_meaningful_distance

        if is_buy:
            stop_loss = extreme - buffer
            # Safety: SL must be below entry
            if stop_loss >= entry_price:
                stop_loss = entry_price - max(buffer, profile.min_meaningful_distance)
            risk = entry_price - stop_loss
            if risk <= 0:
                continue

            # Priority 1: real opposing liquidity level
            tp_price = None
            for cand in tp_candidates:
                if cand > entry_price:
                    tp_price = cand
                    break

            # Priority 2: only if no real level exists, fall back to user R:R
            # (this is the only place user-selected R:R is used)
            if tp_price is None:
                tp_price = entry_price + risk * rr_target

        else:  # SELL
            stop_loss = extreme + buffer
            if stop_loss <= entry_price:
                stop_loss = entry_price + max(buffer, profile.min_meaningful_distance)
            risk = stop_loss - entry_price
            if risk <= 0:
                continue

            tp_price = None
            for cand in tp_candidates:
                if cand < entry_price:
                    tp_price = cand
                    break

            if tp_price is None:
                tp_price = entry_price - risk * rr_target

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
    All distances derived from the asset's own history.
    """
    if level.status != LevelStatus.ACTIVE:
        return None
    if level.strength < 1.5:
        return None

    is_buy = direction.upper() == "BUY"
    is_low_level = level.kind.name.endswith("LOW")
    if is_buy and not is_low_level:
        return None
    if not is_buy and is_low_level:
        return None

    trigger_price = level.price
    tp_candidates = _find_liquidity_targets(levels, trigger_price, is_buy, current_index)

    rows: List[RiskLevelRow] = []
    risk_levels = [("40%", 0.40), ("65%", 0.65), ("80%", 0.80)]

    for idx, (label, pct) in enumerate(risk_levels):
        atr_mult = _buffer_for_risk(profile, pct)
        buffer = profile.current_atr * atr_mult

        if buffer < profile.min_meaningful_distance:
            buffer = profile.min_meaningful_distance

        if is_buy:
            stop_loss = trigger_price - buffer
            risk = trigger_price - stop_loss
            if risk <= 0:
                continue

            tp_price = None
            for cand in tp_candidates:
                if cand > trigger_price:
                    tp_price = cand
                    break

            if tp_price is None:
                tp_price = trigger_price + risk * rr_target

        else:
            stop_loss = trigger_price + buffer
            risk = stop_loss - trigger_price
            if risk <= 0:
                continue

            tp_price = None
            for cand in tp_candidates:
                if cand < trigger_price:
                    tp_price = cand
                    break

            if tp_price is None:
                tp_price = trigger_price - risk * rr_target

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
