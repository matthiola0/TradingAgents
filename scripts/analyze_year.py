"""Per-(ticker, year) breakdown — generalised version of analyze_2022.py.

Usage:
    python scripts/analyze_year.py BTC-USD 2023
    python scripts/analyze_year.py NVDA 2024
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

POS = {"Buy": 1.0, "Overweight": 0.5, "Hold": 0.0, "Underweight": -0.5, "Sell": -1.0}


def median_gap_days(dates: list[str]) -> float:
    if len(dates) < 2:
        return float("nan")
    ds = sorted(pd.to_datetime(dates))
    gaps = [(ds[i + 1] - ds[i]).days for i in range(len(ds) - 1)]
    gaps.sort()
    return gaps[len(gaps) // 2]


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: analyze_year.py TICKER YEAR")
        sys.exit(2)
    ticker = sys.argv[1].upper()
    year = int(sys.argv[2])

    log_path = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"
    text = log_path.read_text(encoding="utf-8")

    pattern = re.compile(rf"\[({year}-\d{{2}}-\d{{2}}) \| {re.escape(ticker)} \| (\w+) \|")
    entries = pattern.findall(text)
    print(f"{year} {ticker} entries: {len(entries)}")

    if not entries:
        sys.exit(1)

    gap = median_gap_days([d for d, _ in entries])
    holding_days = 5 if gap < 14 else 20
    cadence = "weekly" if gap < 14 else "monthly"
    print(f"  cadence: {cadence}  holding_days: {holding_days}")

    hist = yf.Ticker(ticker).history(start=f"{year - 1}-12-15", end=f"{year + 1}-03-01")
    hist.index = hist.index.tz_localize(None)
    prices = hist["Close"]

    print()
    print(f"{'date':12} {'rating':12} {'raw_ret':>10} {'position':>9} {'trade_pnl':>10}")
    print("-" * 60)

    strat_total = 1.0
    naive_total = 1.0
    dumb_total = 1.0
    de_risk_correct = 0
    de_risk_n = 0

    for date_str, rating in entries:
        entry = pd.Timestamp(date_str)
        avail = prices[prices.index >= entry]
        if len(avail) < holding_days + 1:
            continue
        raw = (avail.iloc[holding_days] - avail.iloc[0]) / avail.iloc[0]
        pos = POS.get(rating, 0.0)
        pnl = raw * pos
        strat_total *= 1 + pnl
        naive_total *= 1 + raw
        dumb_total *= 1 + raw * 0.5
        if pos < 1.0:
            de_risk_n += 1
            if raw < 0:
                de_risk_correct += 1
        print(f"{date_str:12} {rating:12} {raw*100:+9.2f}% {pos:>8.1f}x {pnl*100:+9.2f}%")

    n = len(entries)
    print("-" * 60)
    print(f"Strategy:      {(strat_total - 1) * 100:+8.1f}%")
    print(f"Naive Buy:     {(naive_total - 1) * 100:+8.1f}%   alpha vs Buy:  {(strat_total - naive_total) * 100:+6.1f}pp")
    print(f"Dumb 50%:      {(dumb_total - 1) * 100:+8.1f}%   true signal:   {(strat_total - dumb_total) * 100:+6.1f}pp")
    if de_risk_n > 0:
        base_rate = sum(1 for d, _ in entries if (
            (lambda p=prices, e=pd.Timestamp(d): (
                p[p.index >= e].iloc[holding_days] - p[p.index >= e].iloc[0]
            ) / p[p.index >= e].iloc[0])() < 0
        )) / n * 100
        print(f"De-risk:       {de_risk_correct}/{de_risk_n} = {de_risk_correct/de_risk_n*100:.0f}%   "
              f"base rate {base_rate:.0f}%   lift: {de_risk_correct/de_risk_n*100 - base_rate:+.0f}pp")


if __name__ == "__main__":
    main()
