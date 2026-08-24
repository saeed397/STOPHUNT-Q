"""utils/aggregate.py — standard OHLCV resampling. Does not invent prices."""
from __future__ import annotations
from typing import List, TypeVar

CandleLike = TypeVar("CandleLike")

def aggregate_candles(candles: List[CandleLike], factor: int) -> List[CandleLike]:
    if factor <= 1:
        return candles
    from data.providers import Candle
    out: List[Candle] = []
    for i in range(0, len(candles) - factor + 1, factor):
        group = candles[i:i + factor]
        out.append(Candle(
            timestamp=group[0].timestamp,
            open=group[0].open,
            high=max(c.high for c in group),
            low=min(c.low for c in group),
            close=group[-1].close,
            volume=sum(c.volume for c in group),
            closed=all(c.closed for c in group),
        ))
    return out
