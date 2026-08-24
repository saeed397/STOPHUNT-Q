# Liquidity-Centric Stop Hunt Order System

Python + Streamlit implementation of a strict, asset-specific Stop-Hunt / Liquidity Sweep strategy.

## Core Philosophy (Non-negotiable)

1. **Every signal is derived only from the historical behavior of that specific cryptocurrency and timeframe.** No shared magic numbers between BTC and alts.
2. **No fabricated data.** Only Yahoo Finance (primary) + CoinGecko (fallback). Clear error when data is insufficient.
3. **Two mandatory output groups:**
   - Standard (confirmed Sweep → Reclaim → Displacement → CHoCH)
   - StopHunt Trigger (pending order exactly at high-quality unswept liquidity levels where other traders’ stops cluster)
4. **Fewer but higher-quality signals.** Strict filters with balanced thresholds so signals can still appear.

## Features

- Per-asset / per-timeframe statistical calibration (ATR, penetration depth, equal-level tolerance, min distances)
- Clear separation of Medium vs Strong liquidity levels (no overlapping prices)
- Three risk rows (40% / 65% / 80%) built from historical sweep-depth percentiles of the same asset
- Exact UI layout requested by the strategy owner
- Regime-shift detection and warning
- Plain-language Persian explanations behind ℹ️ buttons

## Quick Start

```bash
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

## Project Structure

```
liquidity-stop-hunt/
├── app/streamlit_app.py          # Exact required UI
├── engines/
│   ├── calibrator.py             # Asset-specific thresholds (Rule #1)
│   ├── liquidity_engine.py       # Swings, Equal High/Low, Medium/Strong selection
│   ├── sweep_engine.py           # True Sweep = penetration + reclaim
│   ├── structure_engine.py       # Displacement + CHoCH confirmation
│   └── stophunt_engine.py        # Orchestrator
├── models/
│   ├── entry_sl_tp.py            # Dual groups + 3 risk levels
│   └── setup_score.py
├── data/
│   ├── providers.py              # Yahoo Finance + CoinGecko only
│   └── validator.py
├── presentation/explain.py
├── risk/risk_management.py
├── config.py
└── requirements.txt
```

## Important Notes

- Setup Score weights are provisional and should be refined with walk-forward backtesting.
- Fee / slippage values in risk module are placeholders — replace with your real exchange numbers.
- The system prefers quality over quantity. If no high-quality setup exists, it honestly reports that instead of inventing a signal.
