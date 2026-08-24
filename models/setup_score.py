"""
models/setup_score.py
Provisional weights — to be calibrated later by walk-forward backtest.
"""
from __future__ import annotations
from dataclasses import dataclass
from engines.liquidity_engine import LiquidityLevel
from engines.sweep_engine import SweepEvent
from engines.structure_engine import StructureConfirmation

@dataclass
class ScoreWeights:
    liquidity_quality_max: float = 25
    sweep_quality_max: float = 20
    reclaim_max: float = 15
    structure_shift_max: float = 20
    volume_orderflow_max: float = 10
    htf_alignment_max: float = 10

DEFAULT_WEIGHTS = ScoreWeights()

def score_setup(level: LiquidityLevel, sweep: SweepEvent, confirmation: StructureConfirmation,
                htf_aligned: bool = True, volume_percentile: float = 0.5,
                weights: ScoreWeights = DEFAULT_WEIGHTS) -> dict:
    liquidity_quality = min(weights.liquidity_quality_max, level.strength * 8)

    if sweep.wick_body_ratio != float("inf"):
        sweep_quality = min(weights.sweep_quality_max, sweep.wick_body_ratio * (weights.sweep_quality_max / 3))
    else:
        sweep_quality = weights.sweep_quality_max

    reclaim = weights.reclaim_max if sweep.outcome.name == "TRUE_SWEEP" else 0.0

    structure_shift = 0.0
    if confirmation.confirmed:
        structure_shift = weights.structure_shift_max * min(1.0, confirmation.displacement_strength_pctile)

    volume_orderflow = weights.volume_orderflow_max * min(1.0, max(0.0, volume_percentile))
    htf_alignment = weights.htf_alignment_max if htf_aligned else 0.0

    total = liquidity_quality + sweep_quality + reclaim + structure_shift + volume_orderflow + htf_alignment

    if total < 60:
        band = "NO TRADE"
    elif total < 72:
        band = "WEAK SETUP"
    elif total < 85:
        band = "VALID SETUP"
    else:
        band = "HIGH QUALITY SETUP"

    return {
        "liquidity_quality": round(liquidity_quality, 1),
        "sweep_quality": round(sweep_quality, 1),
        "reclaim": round(reclaim, 1),
        "structure_shift": round(structure_shift, 1),
        "volume_orderflow": round(volume_orderflow, 1),
        "htf_alignment": round(htf_alignment, 1),
        "total": round(total, 1),
        "band": band,
    }
