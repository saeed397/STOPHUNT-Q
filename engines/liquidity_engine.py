"""
engines/liquidity_engine.py
Swing + Equal High/Low + PDH/PDL with strength scoring.
Produces clearly separated medium and strong levels.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List
from data.providers import Candle
from engines.calibrator import AssetTimeframeProfile
from config import DEFAULTS

class SwingType(Enum):
    HIGH = "HIGH"
    LOW = "LOW"

class LevelStatus(Enum):
    ACTIVE = "ACTIVE"
    SWEPT = "SWEPT"
    INVALID = "INVALID"

class LevelKind(Enum):
    SWING_HIGH = "SWING_HIGH"
    SWING_LOW = "SWING_LOW"
    EQUAL_HIGH = "EQUAL_HIGH"
    EQUAL_LOW = "EQUAL_LOW"
    PREV_DAY_HIGH = "PREV_DAY_HIGH"
    PREV_DAY_LOW = "PREV_DAY_LOW"
    PREV_WEEK_HIGH = "PREV_WEEK_HIGH"
    PREV_WEEK_LOW = "PREV_WEEK_LOW"

@dataclass
class Swing:
    index: int
    type: SwingType
    price: float
    event_ts: int
    detection_ts: int
    strength: float = 0.0

@dataclass
class LiquidityLevel:
    id: str
    kind: LevelKind
    price: float
    formed_index: int
    status: LevelStatus = LevelStatus.ACTIVE
    touches: int = 1
    strength: float = 0.0
    member_swings: List[int] = field(default_factory=list)

def detect_swings(candles: List[Candle], fractal_order: int = None) -> List[Swing]:
    order = fractal_order or DEFAULTS.swing_fractal_order
    swings: List[Swing] = []
    n = len(candles)
    for i in range(order, n - order):
        window = candles[i - order: i + order + 1]
        c = candles[i]
        detection_index = min(i + order, n - 1)
        if c.high == max(w.high for w in window):
            swings.append(Swing(
                index=i, type=SwingType.HIGH, price=c.high,
                event_ts=c.timestamp, detection_ts=candles[detection_index].timestamp,
            ))
        if c.low == min(w.low for w in window):
            swings.append(Swing(
                index=i, type=SwingType.LOW, price=c.low,
                event_ts=c.timestamp, detection_ts=candles[detection_index].timestamp,
            ))
    return swings

def build_liquidity_levels(swings: List[Swing], profile: AssetTimeframeProfile) -> List[LiquidityLevel]:
    tol = profile.equal_level_tolerance
    highs = sorted([s for s in swings if s.type == SwingType.HIGH], key=lambda s: s.price)
    lows = sorted([s for s in swings if s.type == SwingType.LOW], key=lambda s: s.price)
    levels: List[LiquidityLevel] = []
    levels.extend(_cluster(highs, tol, LevelKind.SWING_HIGH, LevelKind.EQUAL_HIGH, "EQH"))
    levels.extend(_cluster(lows, tol, LevelKind.SWING_LOW, LevelKind.EQUAL_LOW, "EQL"))
    return levels

def _cluster(swings: List[Swing], tol: float, single_kind: LevelKind,
             equal_kind: LevelKind, prefix: str) -> List[LiquidityLevel]:
    levels: List[LiquidityLevel] = []
    used = [False] * len(swings)
    for i, s in enumerate(swings):
        if used[i]:
            continue
        cluster = [s]
        used[i] = True
        for j in range(i + 1, len(swings)):
            if used[j]:
                continue
            if abs(swings[j].price - s.price) <= tol:
                cluster.append(swings[j])
                used[j] = True
        kind = equal_kind if len(cluster) > 1 else single_kind
        avg_price = sum(c.price for c in cluster) / len(cluster)
        touches = len(cluster)
        # Simple strength: more touches + more recent = higher
        strength = touches * 1.0 + (0.3 if kind.name.startswith("EQUAL") else 0.0)
        levels.append(LiquidityLevel(
            id=f"{prefix}-{s.index}",
            kind=kind,
            price=avg_price,
            formed_index=max(c.index for c in cluster),
            touches=touches,
            strength=strength,
            member_swings=[c.index for c in cluster],
        ))
    return levels

def add_periodic_levels(candles: List[Candle], levels: List[LiquidityLevel]) -> List[LiquidityLevel]:
    import datetime as dt
    if not candles:
        return levels
    by_day = {}
    for c in candles:
        day = dt.datetime.utcfromtimestamp(c.timestamp).date()
        by_day.setdefault(day, []).append(c)
    days_sorted = sorted(by_day.keys())
    for day in days_sorted[:-1]:
        day_candles = by_day[day]
        pdh = max(c.high for c in day_candles)
        pdl = min(c.low for c in day_candles)
        last_idx = candles.index(day_candles[-1])
        levels.append(LiquidityLevel(
            id=f"PDH-{day}", kind=LevelKind.PREV_DAY_HIGH,
            price=pdh, formed_index=last_idx, touches=1, strength=1.5
        ))
        levels.append(LiquidityLevel(
            id=f"PDL-{day}", kind=LevelKind.PREV_DAY_LOW,
            price=pdl, formed_index=last_idx, touches=1, strength=1.5
        ))
    return levels

def select_medium_strong_levels(levels: List[LiquidityLevel], current_price: float,
                                is_buy: bool, profile: AssetTimeframeProfile,
                                n_each: int = 3) -> tuple[List[LiquidityLevel], List[LiquidityLevel]]:
    """
    Return (medium_levels, strong_levels) clearly separated and ordered.
    For Buy we want resistances above price. For Sell we want supports below price.
    """
    if is_buy:
        candidates = [l for l in levels if l.price > current_price and l.status == LevelStatus.ACTIVE]
        candidates = sorted(candidates, key=lambda l: l.price)  # nearest first
    else:
        candidates = [l for l in levels if l.price < current_price and l.status == LevelStatus.ACTIVE]
        candidates = sorted(candidates, key=lambda l: -l.price)  # nearest first

    # Enforce minimum distance between selected levels
    min_sep = profile.min_meaningful_distance * 1.2
    selected = []
    for lv in candidates:
        if all(abs(lv.price - s.price) >= min_sep for s in selected):
            selected.append(lv)
        if len(selected) >= n_each * 2 + 2:
            break

    # Split by strength
    selected = sorted(selected, key=lambda l: (-l.strength, abs(l.price - current_price)))
    strong = [l for l in selected if l.strength >= DEFAULTS.strong_level_min_touches or l.kind.name.startswith("EQUAL") or "PREV" in l.kind.name][:n_each]
    remaining = [l for l in selected if l not in strong]
    medium = remaining[:n_each]

    # If not enough strong, promote from medium
    while len(strong) < n_each and medium:
        strong.append(medium.pop(0))

    # Ensure we have exactly up to n_each each, ordered by price
    if is_buy:
        strong = sorted(strong, key=lambda l: l.price)[:n_each]
        medium = sorted(medium, key=lambda l: l.price)[:n_each]
    else:
        strong = sorted(strong, key=lambda l: -l.price)[:n_each]
        medium = sorted(medium, key=lambda l: -l.price)[:n_each]

    return medium, strong
