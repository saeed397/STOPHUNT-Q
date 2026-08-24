"""risk/risk_management.py — position sizing and daily limits."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List

@dataclass
class RiskConfig:
    risk_percent_per_trade: float = 1.0
    max_daily_loss_percent: float = 3.0
    max_consecutive_losses: int = 3
    min_rr: float = 1.2
    max_concurrent_trades: int = 1
    account_equity: float = 1000.0
    fee_percent_roundtrip: float = 0.08
    slippage_percent: float = 0.05

@dataclass
class DailyState:
    date: str
    realized_pnl_percent: float = 0.0
    consecutive_losses: int = 0
    open_trades: int = 0

class RiskManager:
    def __init__(self, config: RiskConfig):
        self.config = config

    def position_size(self, entry: float, stop_loss: float) -> float:
        risk_amount = self.config.account_equity * (self.config.risk_percent_per_trade / 100.0)
        per_unit_risk = abs(entry - stop_loss)
        if per_unit_risk <= 0:
            return 0.0
        return risk_amount / per_unit_risk

    def is_trade_allowed(self, state: DailyState, rr_actual: float, symbol: str,
                         currently_open_symbols: List[str]) -> tuple[bool, str]:
        if rr_actual < self.config.min_rr:
            return False, f"R:R {rr_actual:.2f} below minimum"
        if state.consecutive_losses >= self.config.max_consecutive_losses:
            return False, "Max consecutive losses reached"
        if state.realized_pnl_percent <= -abs(self.config.max_daily_loss_percent):
            return False, "Max daily loss reached"
        if state.open_trades >= self.config.max_concurrent_trades:
            return False, "Max concurrent trades reached"
        return True, "OK"
