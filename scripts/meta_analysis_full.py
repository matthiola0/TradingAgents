"""All-data alpha analysis across every (year, ticker) cohort in the memory log.

Reads every entry, groups by ticker, infers cadence (weekly vs monthly) from
median date gap, computes:
- naive always-Buy P&L
- TradingAgents rated-position P&L
- always-50% baseline P&L
- de-risk precision and lift over base rate

Key column is `signal_alpha` = strategy vs always-50%. Positive = the model
adds value beyond default caution. Negative = the model is actively wrong.

Usage:
    python scripts/meta_analysis_full.py
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pandas as pd
import yfinance as yf

POS = {"Buy": 1.0, "Overweight": 0.5, "Hold": 0.0, "Underweight": -0.5, "Sell": -1.0}


def load_entries(text: str):
    """Yield (date, ticker, rating) tuples for every memory-log entry."""
    pattern = re.compile(r"\[(\d{4}-\d{2}-\d{2}) \| ([A-Z0-9.\-]+) \| (\w+) \|")
    return pattern.findall(text)


def per_ticker_year(entries, ticker: str, year: int, holding_days: int):
    rows = []
    hist = yf.Ticker(ticker).history(start=f"{year - 1}-12-15", end=f"{year + 1}-03-01")
    if hist.empty:
        return pd.DataFrame()
    hist.index = hist.index.tz_localize(None)
    prices = hist["Close"]
    for date_str, t, rating in entries:
        if t != ticker or not date_str.startswith(str(year)):
            continue
        entry = pd.Timestamp(date_str)
        avail = prices[prices.index >= entry]
        if len(avail) < holding_days + 1:
            continue
        raw = (avail.iloc[holding_days] - avail.iloc[0]) / avail.iloc[0]
        pos = POS.get(rating, 0.0)
        rows.append({
            "date": date_str, "ticker": ticker, "year": year,
            "rating": rating, "raw": raw, "position": pos, "pnl": raw * pos,
        })
    return pd.DataFrame(rows)


def median_gap_days(dates: list[str]) -> float:
    if len(dates) < 2:
        return float("nan")
    ds = sorted(pd.to_datetime(dates))
    gaps = [(ds[i + 1] - ds[i]).days for i in range(len(ds) - 1)]
    gaps.sort()
    return gaps[len(gaps) // 2]


def main() -> None:
    log_path = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"
    text = log_path.read_text(encoding="utf-8")
    entries = list(load_entries(text))

    # Group by (ticker, year)
    cohorts = defaultdict(list)
    for date, t, rating in entries:
        year = int(date.split("-")[0])
        cohorts[(t, year)].append(date)

    print("=" * 100)
    print("ALL COHORTS — naive Buy vs strategy vs always-50% baseline")
    print("=" * 100)
    print(f"{'ticker':10} {'yr':>5} {'N':>4} {'cad':>6} "
          f"{'naive':>8} {'strategy':>9} {'dumb50%':>9} "
          f"{'vs_buy':>8} {'true_sig':>9}  {'derisk':>10}")
    print("-" * 100)

    for (ticker, year) in sorted(cohorts):
        gap = median_gap_days(cohorts[(ticker, year)])
        cadence = "weekly" if gap < 14 else "monthly"
        holding_days = 5 if cadence == "weekly" else 20
        df = per_ticker_year(entries, ticker, year, holding_days)
        if df.empty:
            continue
        naive = (1 + df["raw"]).prod() - 1
        strat = (1 + df["pnl"]).prod() - 1
        dumb = (1 + df["raw"] * 0.5).prod() - 1
        vs_buy = (strat - naive) * 100
        true_sig = (strat - dumb) * 100
        de_risk = df[df["position"] < 1.0]
        if len(de_risk) > 0:
            correct = int((de_risk["raw"] < 0).sum())
            derisk_str = f"{correct}/{len(de_risk)}={correct/len(de_risk)*100:.0f}%"
        else:
            derisk_str = "n/a"
        print(f"{ticker:10} {year:>5d} {len(df):>4d} {cadence:>6} "
              f"{naive*100:>+7.1f}% {strat*100:>+8.1f}% {dumb*100:>+8.1f}% "
              f"{vs_buy:>+7.1f}pp {true_sig:>+8.1f}pp  {derisk_str:>10}")

    # Aggregate true-signal alpha by regime (negative-naive vs positive-naive years)
    print()
    print("=" * 100)
    print("REGIME SUMMARY: when is the framework's signal actually positive?")
    print("=" * 100)

    bear_alphas = []
    bull_alphas = []
    for (ticker, year) in sorted(cohorts):
        gap = median_gap_days(cohorts[(ticker, year)])
        holding_days = 5 if gap < 14 else 20
        df = per_ticker_year(entries, ticker, year, holding_days)
        if df.empty:
            continue
        naive = (1 + df["raw"]).prod() - 1
        strat = (1 + df["pnl"]).prod() - 1
        dumb = (1 + df["raw"] * 0.5).prod() - 1
        true_sig_pp = (strat - dumb) * 100
        (bear_alphas if naive < 0 else bull_alphas).append((ticker, year, true_sig_pp, naive))

    print()
    print("BEAR-REGIME COHORTS (naive Buy < 0):")
    for t, y, sig, naive in bear_alphas:
        print(f"  {t:10} {y}  naive={naive*100:+6.1f}%  true_signal={sig:+6.2f}pp")
    if bear_alphas:
        avg = sum(s for _, _, s, _ in bear_alphas) / len(bear_alphas)
        print(f"  {'AVG':10} {'':>4}  {'':<13}  true_signal={avg:+6.2f}pp")

    print()
    print("BULL-REGIME COHORTS (naive Buy >= 0):")
    for t, y, sig, naive in bull_alphas:
        print(f"  {t:10} {y}  naive={naive*100:+6.1f}%  true_signal={sig:+6.2f}pp")
    if bull_alphas:
        avg = sum(s for _, _, s, _ in bull_alphas) / len(bull_alphas)
        print(f"  {'AVG':10} {'':>4}  {'':<13}  true_signal={avg:+6.2f}pp")


if __name__ == "__main__":
    main()
