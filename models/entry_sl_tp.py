"""
models/entry_sl_tp.py
Produces the two mandatory groups, each with three risk levels (40/65/80).

CORE PHILOSOPHY (strictly enforced – unchanged):
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

def _get_ordered_buffers(profile: AssetTimeframeProfile) -> List[float]:
    """
    Return three buffers (price units) for 40% / 65% / 80% risk.
    Taken directly from the asset's own historical percentiles × current ATR.
    Only the asset's own min_meaningful_distance is used as floor.
    No artificial widening between the three values.
    """
    atr = profile.current_atr if profile.current_atr > 0 else 0.0
    floor = profile.min_meaningful_distance

    b40 = max(atr * profile.penetration_depth_atr_p40, floor)
    b65 = max(atr * profile.penetration_depth_atr_p65, floor)
    b80 = max(atr * profile.penetration_depth_atr_p80, floor)

    # Preserve natural order if history produced inverted percentiles
    # (very rare). We only sort ascending; we do NOT force gaps.
    buffers = sorted([b40, b65, b80])
    return buffers

def _find_liquidity_targets(levels: List[LiquidityLevel], from_price: float,
                            is_buy: bool, from_index: int) -> List[float]:
    """Real opposing liquidity prices, nearest first."""
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

    buffers = _get_ordered_buffers(profile)          # [b40, b65, b80]
    tp_candidates = _find_liquidity_targets(levels, entry_price, is_buy, entry_idx)

    rows: List[RiskLevelRow] = []
    labels = ["40%", "65%", "80%"]

    for i, label in enumerate(labels):
        buffer = buffers[i]

        if is_buy:
            stop_loss = extreme - buffer
            if stop_loss >= entry_price:
                stop_loss = entry_price - buffer
            risk = entry_price - stop_loss
            if risk <= 0:
                continue

            # Assign progressively farther real targets when available
            tp_price = None
            if tp_candidates:
                # i=0 → nearest, i=1 → next, i=2 → farthest available
                idx = min(i, len(tp_candidates) - 1)
                candidate = tp_candidates[idx]
                if candidate > entry_price:
                    tp_price = candidate

            if tp_price is None:
                # Only when no real opposing level exists
                tp_price = entry_price + risk * rr_target

        else:
            stop_loss = extreme + buffer
            if stop_loss <= entry_price:
                stop_loss = entry_price + buffer
            risk = stop_loss - entry_price
            if risk <= 0:
                continue

            tp_price = None
            if tp_candidates:
                idx = min(i, len(tp_candidates) - 1)
                candidate = tp_candidates[idx]
                if candidate < entry_price:
                    tp_price = candidate

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
    buffers = _get_ordered_buffers(profile)
    tp_candidates = _find_liquidity_targets(levels, trigger_price, is_buy, current_index)

    rows: List[RiskLevelRow] = []
    labels = ["40%", "65%", "80%"]

    for i, label in enumerate(labels):
        buffer = buffers[i]

        if is_buy:
            stop_loss = trigger_price - buffer
            risk = trigger_price - stop_loss
            if risk <= 0:
                continue

            tp_price = None
            if tp_candidates:
                idx = min(i, len(tp_candidates) - 1)
                candidate = tp_candidates[idx]
                if candidate > trigger_price:
                    tp_price = candidate

            if tp_price is None:
                tp_price = trigger_price + risk * rr_target

        else:
            stop_loss = trigger_price + buffer
            risk = stop_loss - trigger_price
            if risk <= 0:
                continue

            tp_price = None
            if tp_candidates:
                idx = min(i, len(tp_candidates) - 1)
                candidate = tp_candidates[idx]
                if candidate < trigger_price:
                    tp_price = candidate

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
