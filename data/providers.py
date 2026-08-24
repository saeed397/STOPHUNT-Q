"""
data/providers.py
Real data only. Primary: Yahoo Finance (yfinance). Fallback: CoinGecko OHLC.
No Binance. No fabricated candles.
Sources:
- https://github.com/ranaroussi/yfinance
- https://docs.coingecko.com/reference/coins-id-ohlc
- https://docs.coingecko.com/reference/coins-markets
"""
from __future__ import annotations
import time
import requests
from dataclasses import dataclass
from typing import List, Optional, Tuple

from config import COINGECKO_MARKETS_URL, TOP_N_ASSETS, YF_INTERVAL_LIMITS_DAYS
from utils.aggregate import aggregate_candles

class ProviderError(Exception):
    """Must be surfaced to user. Never replace with guesses."""
    pass

@dataclass
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    closed: bool = True

@dataclass
class OHLCVBatch:
    candles: List[Candle]
    actual_interval_seconds: int
    source: str
    note: Optional[str] = None

_NOMINAL_SECONDS = {
    "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400,
    "1d": 86400, "1w": 604800, "1M": 2592000
}

class YahooFinanceProvider:
    NATIVE_INTERVAL = {
        "15m": "15m", "30m": "30m", "1h": "60m",
        "1d": "1d", "1w": "1wk", "1M": "1mo",
    }

    def get_ohlcv(self, symbol: str, quote: str, timeframe: str,
                  desired_candle_count: int = 1000) -> OHLCVBatch:
        try:
            import yfinance as yf
        except ImportError as e:
            raise ProviderError(
                "کتابخانه yfinance نصب نیست (pip install yfinance). "
                "اطلاعات معتبر برای این بخش موجود نیست و اصلاح انجام نشد."
            ) from e

        ticker_symbol = f"{symbol.upper()}-{quote.upper()}"
        aggregate_factor = 1
        native_tf = timeframe
        if timeframe == "4h":
            native_tf = "1h"
            aggregate_factor = 4

        native_interval = self.NATIVE_INTERVAL.get(native_tf)
        if native_interval is None:
            raise ProviderError(f"Unsupported timeframe '{timeframe}' for Yahoo Finance.")

        max_days = YF_INTERVAL_LIMITS_DAYS.get(native_interval)
        needed_days = self._estimate_days_needed(native_interval, desired_candle_count * aggregate_factor)
        period_days = min(needed_days, max_days) if max_days else needed_days

        try:
            ticker = yf.Ticker(ticker_symbol)
            df = ticker.history(period=f"{period_days}d", interval=native_interval)
        except Exception as e:
            raise ProviderError(f"Yahoo Finance request failed for {ticker_symbol}: {e}") from e

        if df is None or df.empty:
            raise ProviderError(
                f"No Yahoo Finance data for {ticker_symbol}. "
                f"اطلاعات معتبر برای این بخش موجود نیست و اصلاح انجام نشد."
            )

        now = int(time.time())
        native_seconds = _NOMINAL_SECONDS.get(native_tf, 3600)
        candles: List[Candle] = []
        for idx, row in df.iterrows():
            ts = int(idx.timestamp())
            is_closed = (ts + native_seconds) <= now
            candles.append(Candle(
                timestamp=ts,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row.get("Volume", 0.0)),
                closed=is_closed,
            ))

        actual_seconds = native_seconds
        if aggregate_factor > 1:
            candles = aggregate_candles(candles, aggregate_factor)
            actual_seconds = native_seconds * aggregate_factor

        if not candles:
            raise ProviderError(f"No usable candles for {ticker_symbol}.")

        return OHLCVBatch(candles=candles, actual_interval_seconds=actual_seconds, source="Yahoo Finance")

    @staticmethod
    def _estimate_days_needed(interval: str, candle_count: int) -> int:
        per_day = {"15m": 96, "30m": 48, "60m": 24, "1d": 1, "1wk": 1/7, "1mo": 1/30}.get(interval, 24)
        return max(2, int(candle_count / per_day) + 2)

class CoinGeckoOHLCProvider:
    BASE_URL = "https://api.coingecko.com/api/v3"
    GRANULARITY_TABLE: List[Tuple[int, int]] = [
        (2, 1800), (30, 14400), (180, 345600),
    ]

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()

    def _choose_days(self, timeframe: str, desired_candle_count: int) -> Tuple[int, int]:
        nominal = _NOMINAL_SECONDS.get(timeframe, 14400)
        best = self.GRANULARITY_TABLE[-1]
        for days, gran in self.GRANULARITY_TABLE:
            if gran <= nominal:
                best = (days, gran)
        days, gran = best
        needed_days = max(days, int((desired_candle_count * gran) / 86400) + 1)
        return needed_days, gran

    def get_ohlcv(self, coingecko_id: str, quote: str, timeframe: str,
                  desired_candle_count: int = 1000) -> OHLCVBatch:
        days, expected_granularity = self._choose_days(timeframe, desired_candle_count)
        url = f"{self.BASE_URL}/coins/{coingecko_id}/ohlc"
        params = {"vs_currency": quote.lower(), "days": days}
        try:
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            raise ProviderError(f"CoinGecko OHLC request failed: {e}") from e

        if not payload:
            raise ProviderError(
                "اطلاعات معتبر برای این بخش موجود نیست و اصلاح انجام نشد. "
                f"(CoinGecko returned nothing for {coingecko_id})"
            )

        now = int(time.time())
        candles: List[Candle] = []
        for row in payload:
            ts_ms, o, h, l, c = row
            ts = int(ts_ms / 1000)
            is_closed = (ts + expected_granularity) <= now
            candles.append(Candle(timestamp=ts, open=float(o), high=float(h),
                                  low=float(l), close=float(c), volume=0.0, closed=is_closed))

        if len(candles) >= 3:
            deltas = sorted(candles[i+1].timestamp - candles[i].timestamp for i in range(len(candles)-1))
            observed = deltas[len(deltas)//2]
            if observed > 0:
                expected_granularity = observed

        nominal = _NOMINAL_SECONDS.get(timeframe, 14400)
        note = None
        if expected_granularity != nominal:
            note = (f"CoinGecko free tier returned ~{expected_granularity//60}-min candles, "
                    f"not the requested {timeframe}. Real bar size used for calibration.")

        return OHLCVBatch(candles=candles, actual_interval_seconds=expected_granularity,
                          source="CoinGecko", note=note)

class MultiProviderOHLC:
    def __init__(self):
        self.yahoo = YahooFinanceProvider()
        self.coingecko = CoinGeckoOHLCProvider()

    def get_ohlcv(self, symbol: str, coingecko_id: str, quote: str, timeframe: str,
                  desired_candle_count: int = 1000) -> OHLCVBatch:
        try:
            return self.yahoo.get_ohlcv(symbol, quote, timeframe, desired_candle_count)
        except ProviderError as yahoo_err:
            try:
                batch = self.coingecko.get_ohlcv(coingecko_id, quote, timeframe, desired_candle_count)
                fallback_note = f"Yahoo Finance unavailable ({yahoo_err}); used CoinGecko fallback."
                batch.note = f"{fallback_note} {batch.note or ''}".strip()
                return batch
            except ProviderError as cg_err:
                raise ProviderError(
                    "هیچ‌کدام از منابع داده در دسترس نبودند — "
                    "اطلاعات معتبر برای این بخش موجود نیست و اصلاح انجام نشد. "
                    f"[Yahoo: {yahoo_err}] [CoinGecko: {cg_err}]"
                )

class CoinGeckoProvider:
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()

    def get_top_assets(self, n: int = TOP_N_ASSETS) -> List[dict]:
        results = []
        per_page = 250
        pages = -(-n // per_page)
        try:
            for page in range(1, pages + 1):
                resp = self.session.get(
                    COINGECKO_MARKETS_URL,
                    params={
                        "vs_currency": "usd",
                        "order": "market_cap_desc",
                        "per_page": per_page,
                        "page": page,
                        "sparkline": "false",
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                batch = resp.json()
                if not batch:
                    break
                results.extend(batch)
                if len(results) >= n:
                    break
        except Exception as e:
            raise ProviderError(f"CoinGecko markets request failed: {e}") from e

        if not results:
            raise ProviderError("اطلاعات معتبر برای این بخش موجود نیست و اصلاح انجام نشد.")

        return [
            {"symbol": c["symbol"].upper(), "name": c["name"], "id": c["id"],
             "market_cap_rank": c.get("market_cap_rank")}
            for c in results[:n]
        ]
