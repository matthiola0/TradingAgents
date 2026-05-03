"""Compare TradingAgents 2022 signal vs naive every-month-Buy baseline.

Reads the memory log, filters to 2022 entries for the requested ticker,
and computes:
- per-trade P&L using the rating-to-position map
- naive baseline (buy every month, 20-day hold)
- side-by-side comparison

Usage:
    python scripts/analyze_2022.py [TICKER]    # default NVDA
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

POS = {"Buy": 1.0, "Overweight": 0.5, "Hold": 0.0, "Underweight": -0.5, "Sell": -1.0}
HOLDING_DAYS = 20


def main() -> None:
    ticker = (sys.argv[1] if len(sys.argv) > 1 else "NVDA").upper()
    log_path = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"
    text = log_path.read_text(encoding="utf-8")

    pattern = re.compile(rf"\[(2022-\d{{2}}-\d{{2}}) \| {re.escape(ticker)} \| (\w+) \|")
    entries = pattern.findall(text)
    print(f"2022 {ticker} entries: {len(entries)}")

    hist = yf.Ticker(ticker).history(start="2022-01-01", end="2023-02-15")
    hist.index = hist.index.tz_localize(None)
    prices = hist["Close"]

    print()
    print(f"{'date':12} {'rating':12} {'raw_ret':>10} {'position':>9} {'trade_pnl':>10}")
    print("-" * 60)

    strat_total = 1.0
    strat_wins = 0
    naive_total = 1.0
    naive_wins = 0

    for date_str, rating in entries:
        entry = pd.Timestamp(date_str)
        avail = prices[prices.index >= entry]
        if len(avail) < HOLDING_DAYS + 1:
            continue
        p0 = avail.iloc[0]
        pN = avail.iloc[HOLDING_DAYS]
        raw = (pN - p0) / p0
        pos = POS.get(rating, 0.0)
        pnl = raw * pos

        strat_total *= 1 + pnl
        if pnl > 0:
            strat_wins += 1
        naive_total *= 1 + raw
        if raw > 0:
            naive_wins += 1

        print(f"{date_str:12} {rating:12} {raw*100:+9.2f}% {pos:>8.1f}x {pnl*100:+9.2f}%")

    n = len(entries)
    print("-" * 60)
    print(f"Strategy compound: {(strat_total - 1) * 100:+8.1f}%   wins {strat_wins}/{n}")
    print(f"Naive (always Buy):{(naive_total - 1) * 100:+8.1f}%   wins {naive_wins}/{n}")
    print(f"Diff (alpha):      {(strat_total - naive_total) * 100:+8.1f}pp")


if __name__ == "__main__":
    main()
