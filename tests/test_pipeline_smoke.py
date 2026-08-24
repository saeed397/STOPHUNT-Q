"""
Offline smoke test with synthetic candles.
Real signals only ever come from live providers.
"""
import sys, os, math, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.providers import Candle
from data.validator import validate_candles
from engines.calibrator import calibrate
from engines.liquidity_engine import detect_swings, build_liquidity_levels
from engines.sweep_engine import scan_for_sweeps
from config import DEFAULTS

def make_synthetic_candles(n=600, seed=42):
    random.seed(seed)
    candles = []
    price = 50000.0
    ts = 1_700_000_000
    step = 14400  # 4h
    for i in range(n):
        drift = math.sin(i / 20.0) * 80
        vol = random.uniform(50, 300)
        open_ = price
        close = open_ + drift + random.uniform(-vol, vol)
        high = max(open_, close) + random.uniform(0, vol)
        low = min(open_, close) - random.uniform(0, vol)
        candles.append(Candle(timestamp=ts, open=open_, high=high, low=low,
                              close=close, volume=random.uniform(100, 1000), closed=True))
        price = close
        ts += step
    return candles

def test_pipeline_runs():
    raw = make_synthetic_candles()
    candles, report = validate_candles(raw, "TEST", "4h")
    assert report.accepted
    assert len(candles) > DEFAULTS.min_lookback_candles

    profile = calibrate(candles, "TEST", "4h")
    assert profile.n_candles == len(candles)
    assert profile.current_atr > 0

    swings = detect_swings(candles)
    levels = build_liquidity_levels(swings, profile)
    sweeps = scan_for_sweeps(candles, levels, profile)

    print(f"Smoke test passed: {len(candles)} candles, {len(levels)} levels, {len(sweeps)} sweeps.")
    print(f"ATR={profile.current_atr:.2f}, min_dist={profile.min_meaningful_distance:.2f}")

if __name__ == "__main__":
    test_pipeline_runs()
