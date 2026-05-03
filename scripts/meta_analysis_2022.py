"""Combined 2022 alpha analysis across NVDA, TSLA, AAPL, META.

Aggregates the per-ticker numbers from analyze_2022.py and reports:
- per-ticker strategy vs naive returns
- pooled equal-weight portfolio (rebalance monthly across 4 stocks)
- rating distribution and which months the framework de-risked

Usage:
    python scripts/meta_analysis_2022.py
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pandas as pd
import yfinance as yf

POS = {"Buy": 1.0, "Overweight": 0.5, "Hold": 0.0, "Underweight": -0.5, "Sell": -1.0}
HOLDING_DAYS = 20
TICKERS = ["NVDA", "TSLA", "AAPL", "META"]


def per_ticker(text: str, ticker: str):
    pattern = re.compile(rf"\[(2022-\d{{2}}-\d{{2}}) \| {re.escape(ticker)} \| (\w+) \|")
    entries = pattern.findall(text)
    hist = yf.Ticker(ticker).history(start="2022-01-01", end="2023-02-15")
    hist.index = hist.index.tz_localize(None)
    prices = hist["Close"]

    rows = []
    for date_str, rating in entries:
        entry = pd.Timestamp(date_str)
        avail = prices[prices.index >= entry]
        if len(avail) < HOLDING_DAYS + 1:
            continue
        raw = (avail.iloc[HOLDING_DAYS] - avail.iloc[0]) / avail.iloc[0]
        pos = POS.get(rating, 0.0)
        rows.append({
            "date": date_str,
            "ticker": ticker,
            "rating": rating,
            "raw": raw,
            "position": pos,
            "pnl": raw * pos,
        })
    return pd.DataFrame(rows)


def main() -> None:
    log_path = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"
    text = log_path.read_text(encoding="utf-8")

    all_rows = pd.concat([per_ticker(text, t) for t in TICKERS], ignore_index=True)

    print("=" * 78)
    print("2022 BACKTEST: TradingAgents (market analyst, 0 debate, 0 risk) vs naive Buy")
    print("=" * 78)
    print()

    # Per-ticker compound returns
    print(f"{'ticker':8} {'naive_buy':>12} {'strategy':>12} {'alpha':>10}  {'wins':>6}  ratings")
    print("-" * 78)
    for t in TICKERS:
        sub = all_rows[all_rows["ticker"] == t]
        naive = (1 + sub["raw"]).prod() - 1
        strat = (1 + sub["pnl"]).prod() - 1
        wins = int((sub["pnl"] > 0).sum())
        n = len(sub)
        rating_counts = sub["rating"].value_counts()
        rating_str = " / ".join(f"{c}{r[0]}" for r, c in rating_counts.items())
        print(
            f"{t:8} {naive*100:>+11.1f}% {strat*100:>+11.1f}% {(strat-naive)*100:>+9.1f}pp  "
            f"{wins}/{n:<4}  {rating_str}"
        )

    # Pooled equal-weight portfolio
    naive_pool = all_rows.groupby("date")["raw"].mean()
    strat_pool = all_rows.groupby("date")["pnl"].mean()
    naive_total = (1 + naive_pool).prod() - 1
    strat_total = (1 + strat_pool).prod() - 1

    print()
    print("Equal-weight 4-stock portfolio (rebalance monthly):")
    print(f"  Naive every-month Buy:     {naive_total*100:+.1f}%")
    print(f"  TradingAgents (rated pos): {strat_total*100:+.1f}%")
    print(f"  Alpha:                     {(strat_total-naive_total)*100:+.1f}pp")

    # Rating distribution
    print()
    print("Rating distribution (N=48):")
    for rating, count in all_rows["rating"].value_counts().items():
        print(f"  {rating:<12} {count:>3}  ({count/len(all_rows)*100:>4.1f}%)")

    # The hits — which months did the framework correctly de-risk?
    print()
    print("De-risking calls (Overweight/Hold) vs what the market did:")
    de_risk = all_rows[all_rows["position"] < 1.0].copy()
    de_risk["correct"] = de_risk["raw"] < 0
    correct = int(de_risk["correct"].sum())
    print(
        f"  {correct}/{len(de_risk)} de-risk calls landed on negative-return months "
        f"({correct/len(de_risk)*100:.0f}% precision)"
    )
    print(f"  Mean raw return on de-risked months: {de_risk['raw'].mean()*100:+.2f}%")
    full = all_rows[all_rows["position"] >= 1.0]
    print(f"  Mean raw return on full-position (Buy) months: {full['raw'].mean()*100:+.2f}%")


if __name__ == "__main__":
    main()
