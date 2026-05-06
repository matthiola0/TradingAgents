"""Strategy V2: Equity-Trend — for stocks where Strategy V1 (crypto-tuned) fails.

V1 used a -15% stop loss as its primary alpha source, which works on crypto's
fat-tail return distribution but cuts profitable runs short on equities like
NVDA where secular uptrends + smaller monthly losses dominate.

V2 keeps the framework's signal but trades the rules:
- No stop loss (the cause of V1's NVDA underperformance)
- Overweight = 0.7 (not 0.5) — stay high-position in mild uncertainty
- Hold = 0 (only fully exit on explicit Hold rating)
- No confluence filter (don't delay entry)
- Wider drawdown brake at -30% (vs V1 -25%) to avoid over-reacting

Usage:
    python scripts/strategy_v2.py NVDA
    python scripts/strategy_v2.py TSLA
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

LOG = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"
HOLDING_DAYS = 20
FEE = 0.001  # 0.1% — equities lower (~0.005% IB) but be conservative
DRAWDOWN_BRAKE = -0.30
DRAWDOWN_HALT_PERIODS = 1

POSITION_MAP = {"Buy": 1.0, "Overweight": 0.7, "Hold": 0.0,
                "Underweight": 0.0, "Sell": 0.0}


@dataclass
class Trade:
    date: str
    rating: str
    target_pos: float
    actual_pos: float
    raw_return: float
    realized_pnl: float
    on_brake: bool


def load_monthly(ticker: str) -> list[tuple[str, str]]:
    text = LOG.read_text(encoding="utf-8")
    pattern = re.compile(rf"\[(\d{{4}}-\d{{2}}-\d{{2}}) \| {re.escape(ticker)} \| (\w+) \|")
    entries = pattern.findall(text)
    seen_ym = set()
    monthly = []
    for date, rating in sorted(entries):
        ym = date[:7]
        if ym in seen_ym:
            continue
        seen_ym.add(ym)
        monthly.append((date, rating))
    return monthly


def get_holding_return(prices: pd.Series, entry_date: str, holding_days: int) -> Optional[float]:
    entry = pd.Timestamp(entry_date)
    avail = prices[prices.index >= entry]
    if len(avail) < holding_days + 1:
        return None
    return float((avail.iloc[holding_days] - avail.iloc[0]) / avail.iloc[0])


def run_v2(entries: list[tuple[str, str]], prices: pd.Series, *,
           use_brake: bool = True, use_fee: bool = True) -> tuple[list[Trade], float, float]:
    portfolio = 1.0
    peak = 1.0
    brake_until_idx = -1

    trades: list[Trade] = []

    for i, (date, rating) in enumerate(entries):
        target = POSITION_MAP.get(rating, 0.0)
        on_brake = use_brake and i < brake_until_idx
        actual = 0.0 if on_brake else target

        raw = get_holding_return(prices, date, HOLDING_DAYS)
        if raw is None:
            continue

        realized = raw * actual
        if use_fee and actual > 0:
            realized -= 2 * FEE * actual

        portfolio *= (1 + realized)
        peak = max(peak, portfolio)
        drawdown = portfolio / peak - 1
        if use_brake and drawdown <= DRAWDOWN_BRAKE and not on_brake:
            brake_until_idx = i + 1 + DRAWDOWN_HALT_PERIODS
            peak = portfolio

        trades.append(Trade(date, rating, target, actual, raw, realized, on_brake))

    if not trades:
        return [], 0.0, 0.0

    equity = [1.0]
    for t in trades:
        equity.append(equity[-1] * (1 + t.realized_pnl))
    eq = pd.Series(equity)
    max_dd = float((eq / eq.cummax() - 1).min())

    return trades, portfolio - 1, max_dd


def naive_baseline(entries: list[tuple[str, str]], prices: pd.Series) -> tuple[float, float]:
    portfolio = 1.0
    equity = [1.0]
    for date, _ in entries:
        raw = get_holding_return(prices, date, HOLDING_DAYS)
        if raw is None:
            continue
        portfolio *= (1 + raw)
        equity.append(portfolio)
    eq = pd.Series(equity)
    max_dd = float((eq / eq.cummax() - 1).min())
    return portfolio - 1, max_dd


def main() -> None:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    entries = load_monthly(ticker)
    if not entries:
        print(f"No {ticker} monthly entries.")
        return

    print(f"{ticker} monthly cohort: {len(entries)} entries from {entries[0][0]} to {entries[-1][0]}")
    print()

    start_year = int(entries[0][0][:4])
    hist = yf.Ticker(ticker).history(start=f"{start_year - 1}-12-15", end="2026-03-01")
    hist.index = hist.index.tz_localize(None)
    prices = hist["Close"]

    naive_ret, naive_dd = naive_baseline(entries, prices)
    print("=" * 95)
    print(f"{'Naive Buy&Hold every month (1.0x always)':<45} total={naive_ret*100:+8.1f}%   max_dd={naive_dd*100:+6.1f}%")

    trades, ret, dd = run_v2(entries, prices, use_brake=False, use_fee=True)
    n = len(trades)
    wins = sum(1 for t in trades if t.realized_pnl > 0)
    flat = sum(1 for t in trades if t.actual_pos == 0)
    print(f"{'V2: Buy=1.0/OW=0.7/Hold=0 + fee':<45} total={ret*100:+8.1f}%   max_dd={dd*100:+6.1f}%   N={n} wins={wins}/{n-flat} flat={flat}")

    trades, ret, dd = run_v2(entries, prices, use_brake=True, use_fee=True)
    n = len(trades)
    wins = sum(1 for t in trades if t.realized_pnl > 0)
    flat = sum(1 for t in trades if t.actual_pos == 0)
    brakes = sum(1 for t in trades if t.on_brake)
    print(f"{'V2 + DD brake -30%':<45} total={ret*100:+8.1f}%   max_dd={dd*100:+6.1f}%   N={n} wins={wins}/{n-flat} brakes={brakes}")
    print("=" * 95)


if __name__ == "__main__":
    main()
