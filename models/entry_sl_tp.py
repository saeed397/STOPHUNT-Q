"""
models/entry_sl_tp.py
FIX VERSION: 2026-08-25-final
Produces the two mandatory groups, each with three DISTINCT risk levels (40/65/80).

CORE PHILOSOPHY preserved:
- Buffers come from the asset's own historical penetration-depth percentiles.
- Take-Profit priority remains real opposing liquidity levels of the same asset.
- No external invented prices. Only when no real level exists, user R:R is used.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
from data.providers import Candle
from engines.sweep_engine import SweepEvent
from engines.structure_engine import StructureConfirmation
from engines.liquidity_engine import LiquidityLevel, LevelStatus
from engines.calibrator import AssetTimeframeProfile

@dataclass
class RiskLevelRow:
    risk_label: str
    entry_price: float
    take_profit: float
    stop_loss: float
    rr_actual: float

@dataclass
class SignalGroup:
    mode: str
    direction: str
    rows: List[RiskLevelRow]
    entry_basis: str
    notes: str = ""

def _get_three_buffers(profile: AssetTimeframeProfile) -> List[float]:
    """
    Create three distinct buffers from the asset's own data.
    Base values = historical percentiles × current ATR.
    If history produces almost identical values, we spread them
    using the asset's own ATR as the unit of distance (still data-driven).
    """
    atr = max(profile.current_atr, 1e-8)
    floor = max(profile.min_meaningful_distance, atr * 0.15)

    raw = [
        profile.penetration_depth_atr_p40,
        profile.penetration_depth_atr_p65,
        profile.penetration_depth_atr_p80,
    ]
    # Convert to price units
    bufs = [max(atr * r, floor) for r in raw]

    # Ensure strict ascending order and minimum separation based on THIS asset's ATR
    min_sep = max(atr * 0.12, floor * 0.4)
    bufs = sorted(bufs)
    for i in range(1, 3):
        if bufs[i] < bufs[i-1] + min_sep:
            bufs[i] = bufs[i-1] + min_sep

    return bufs  # [buffer_40, buffer_65, buffer_80]

def _find_liquidity_targets(levels: List[LiquidityLevel], from_price: float,
                            is_buy: bool, from_index: int) -> List[float]:
    candidates = [
        l.price for l in levels
        if l.status == LevelStatus.ACTIVE
        and l.formed_index <= from_index
        and ((is_buy and l.kind.name.endswith("HIGH") and l.price > from_price)
             or (not is_buy and l.kind.name.endswith("LOW") and l.price < from_price))
    ]
    if not candidates:
        return []
    return sorted(set(candidates), key=lambda p: abs(p - from_price))

def _build_rows(entry_price: float, extreme_or_trigger: float, is_buy: bool,
                buffers: List[float], tp_candidates: List[float],
                rr_target: float, is_trigger: bool) -> List[RiskLevelRow]:
    labels = ["40%", "65%", "80%"]
    rows = []

    for i, label in enumerate(labels):
        buffer = buffers[i]

        if is_buy:
            stop_loss = extreme_or_trigger - buffer
            if stop_loss >= entry_price:
                stop_loss = entry_price - buffer
            risk = entry_price - stop_loss
            if risk <= 0:
                continue

            # Prefer real liquidity targets; assign farther ones to higher risk rows
            tp_price = None
            if tp_candidates:
                idx = min(i, len(tp_candidates) - 1)
                if tp_candidates[idx] > entry_price:
                    tp_price = tp_candidates[idx]

            if tp_price is None:
                # Fallback only when no real level exists
                # Use slightly increasing R:R for higher risk rows (still based on user rr_target)
                tp_price = entry_price + risk * (rr_target * (1.0 + i * 0.15))

        else:
            stop_loss = extreme_or_trigger + buffer
            if stop_loss <= entry_price:
                stop_loss = entry_price + buffer
            risk = stop_loss - entry_price
            if risk <= 0:
                continue

            tp_price = None
            if tp_candidates:
                idx = min(i, len(tp_candidates) - 1)
                if tp_candidates[idx] < entry_price:
                    tp_price = tp_candidates[idx]

            if tp_price is None:
                tp_price = entry_price - risk * (rr_target * (1.0 + i * 0.15))

        rr_actual = abs(tp_price - entry_price) / risk if risk > 0 else 0.0

        rows.append(RiskLevelRow(
            risk_label=label,
            entry_price=round(entry_price, 6),
            take_profit=round(tp_price, 6),
            stop_loss=round(stop_loss, 6),
            rr_actual=round(rr_actual, 2),
        ))

    return rows

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

    buffers = _get_three_buffers(profile)
    tp_candidates = _find_liquidity_targets(levels, entry_price, is_buy, entry_idx)

    rows = _build_rows(entry_price, extreme, is_buy, buffers, tp_candidates, rr_target, is_trigger=False)

    if not rows:
        return None

    return SignalGroup(
        mode="STANDARD",
        direction=direction.upper(),
        rows=rows,
        entry_basis=f"Close of CHoCH confirmation candle (index {entry_idx})",
        notes="FIX-2026-08-25: Based on confirmed Sweep → Reclaim → Displacement → CHoCH from this asset history. Three distinct risk buffers applied.",
    )

def build_stophunt_trigger_group(candles: List[Candle], level: LiquidityLevel,
                                 profile: AssetTimeframeProfile,
                                 levels: List[LiquidityLevel],
                                 direction: str, rr_target: float,
                                 current_index: int) -> Optional[SignalGroup]:
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
    buffers = _get_three_buffers(profile)
    tp_candidates = _find_liquidity_targets(levels, trigger_price, is_buy, current_index)

    rows = _build_rows(trigger_price, trigger_price, is_buy, buffers, tp_candidates, rr_target, is_trigger=True)

    if not rows:
        return None

    return SignalGroup(
        mode="STOPHUNT_TRIGGER",
        direction=direction.upper(),
        rows=rows,
        entry_basis=f"Pending trigger at liquidity level {level.id} ({level.kind.value}). "
                    f"Activates only when price reaches this level and hunts the stops.",
        notes="FIX-2026-08-25: Hunt-the-hunters entry. Three distinct risk buffers from this asset history.",
    )
