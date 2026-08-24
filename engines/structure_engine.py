"""
engines/structure_engine.py
Full confirmation chain: Sweep → Reclaim → Displacement → CHoCH
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
from data.providers import Candle
from engines.liquidity_engine import Swing, SwingType
from engines.sweep_engine import SweepEvent, SweepOutcome
from engines.calibrator import AssetTimeframeProfile
from utils.indicators import percentile

@dataclass
class StructureConfirmation:
    sweep: SweepEvent
    displacement_index: Optional[int]
    displacement_strength_pctile: float
    choch_index: Optional[int]
    confirmed: bool
    reason: str

def _recent_body_sizes(candles: List[Candle], upto_index: int, lookback: int = 80) -> List[float]:
    start = max(0, upto_index - lookback)
    return [abs(c.close - c.open) for c in candles[start:upto_index]]

def find_displacement(candles: List[Candle], sweep_index: int, direction_up: bool,
                      max_lookahead: int) -> Optional[int]:
    bodies_ref = _recent_body_sizes(candles, sweep_index)
    if not bodies_ref:
        return None
    for i in range(sweep_index, min(sweep_index + max_lookahead, len(candles))):
        c = candles[i]
        body = c.close - c.open
        size = abs(body)
        pct = sum(1 for b in bodies_ref if b <= size) / len(bodies_ref)
        is_directional = (body > 0) if direction_up else (body < 0)
        if is_directional and pct >= 0.70:  # top ~30% body
            return i
    return None

def find_choch(candles: List[Candle], swings: List[Swing], from_index: int,
               direction_up: bool, max_lookahead: int) -> Optional[int]:
    opposite_type = SwingType.HIGH if direction_up else SwingType.LOW
    candidates = [s for s in swings if s.type == opposite_type and s.index < from_index]
    if not candidates:
        return None
    last_opposite = max(candidates, key=lambda s: s.index)
    for i in range(from_index, min(from_index + max_lookahead, len(candles))):
        c = candles[i]
        if direction_up and c.close > last_opposite.price:
            return i
        if not direction_up and c.close < last_opposite.price:
            return i
    return None

def confirm_structure(candles: List[Candle], swings: List[Swing], sweep: SweepEvent,
                      profile: AssetTimeframeProfile, max_setup_age_candles: int) -> StructureConfirmation:
    if sweep.outcome != SweepOutcome.TRUE_SWEEP:
        return StructureConfirmation(sweep, None, 0.0, None, False,
                                     "Not a true sweep (no reclaim) — structure check skipped.")

    # Infer direction: low-side sweep → expect bullish reversal
    direction_up = "LOW" in sweep.level_id or "EQL" in sweep.level_id or "PDL" in sweep.level_id

    disp_idx = find_displacement(candles, sweep.candle_index, direction_up, max_setup_age_candles)
    if disp_idx is None:
        return StructureConfirmation(sweep, None, 0.0, None, False,
                                     "No qualifying displacement within expiry window.")

    bodies_ref = _recent_body_sizes(candles, sweep.candle_index)
    size = abs(candles[disp_idx].close - candles[disp_idx].open)
    disp_pct = (sum(1 for b in bodies_ref if b <= size) / len(bodies_ref)) if bodies_ref else 0.0

    choch_idx = find_choch(candles, swings, disp_idx, direction_up, max_setup_age_candles)
    if choch_idx is None:
        return StructureConfirmation(sweep, disp_idx, disp_pct, None, False,
                                     "Displacement found but no CHoCH within expiry window.")

    return StructureConfirmation(sweep, disp_idx, disp_pct, choch_idx, True,
                                 "Full chain confirmed: Sweep → Reclaim → Displacement → CHoCH.")
