"""BTC + SOL 60/40 portfolio backtest — the recommended live trading config.

Both legs use Strategy V1 (confluence + stop loss + brake). Common
period: 2022-01 to 2025-12 (4 years, 48 monthly cohorts).

This is the pre-live validation: if you're going to run BTC+SOL with
real money, this is what it would have done historically.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

LOG = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"
HOLDING_DAYS = 20
FEE = 0.001
V1_STOP = -0.15
V1_BRAKE = -0.25

UNIVERSE = [
    ("BTC-USD", 0.60),
    ("SOL-USD", 0.40),
]


def load_monthly(ticker: str) -> dict[str, tuple[str, str]]:
    text = LOG.read_text(encoding="utf-8")
    pattern = re.compile(rf"\[(\d{{4}}-\d{{2}}-\d{{2}}) \| {re.escape(ticker)} \| (\w+) \|")
    entries = pattern.findall(text)
    by_ym: dict[str, tuple[str, str]] = {}
    for date, rating in sorted(entries):
        ym = date[:7]
        if ym not in by_ym:
            by_ym[ym] = (date, rating)
    return by_ym


def get_holding_return(prices: pd.Series, entry_date: str, days: int) -> Optional[float]:
    entry = pd.Timestamp(entry_date)
    avail = prices[prices.index >= entry]
    if len(avail) < days + 1:
        return None
    return float((avail.iloc[days] - avail.iloc[0]) / avail.iloc[0])


def get_intraperiod_min(prices: pd.Series, entry_date: str, days: int) -> Optional[float]:
    entry = pd.Timestamp(entry_date)
    avail = prices[prices.index >= entry]
    if len(avail) < 2:
        return None
    p0 = avail.iloc[0]
    period = avail.iloc[1: days + 1]
    if period.empty:
        return None
    return float((period.min() - p0) / p0)


def v1_target(history: list[str]) -> float:
    if not history:
        return 0.0
    latest = history[-1]
    prior = history[-2] if len(history) >= 2 else None
    if latest == "Buy" and prior == "Buy":
        return 1.0
    if latest == "Buy":
        return 0.5
    if latest == "Overweight":
        return 0.5
    return 0.0


def main() -> None:
    sig = {ticker: load_monthly(ticker) for ticker, _ in UNIVERSE}
    common_yms = sorted(set.intersection(*(set(s.keys()) for s in sig.values())))
    print(f"Common months: {len(common_yms)} ({common_yms[0]} -> {common_yms[-1]})")

    prices = {}
    for ticker, _ in UNIVERSE:
        h = yf.Ticker(ticker).history(start="2017-12-15", end="2026-03-01")
        h.index = h.index.tz_localize(None)
        prices[ticker] = h["Close"]

    history = {ticker: [] for ticker, _ in UNIVERSE}
    leg_value = {ticker: 1.0 for ticker, _ in UNIVERSE}
    leg_peak = {ticker: 1.0 for ticker, _ in UNIVERSE}
    brake_until = {ticker: -1 for ticker, _ in UNIVERSE}

    portfolio = 1.0
    monthly_returns = []

    print(f"\n{'date':10} {'NAV':>9} ", end="")
    for ticker, _ in UNIVERSE:
        print(f"{ticker[:6]:>8} ", end="")
    print(" notes")
    print("-" * 80)

    for i, ym in enumerate(common_yms):
        period_pnls = {}
        notes = []

        for ticker, weight in UNIVERSE:
            date, rating = sig[ticker][ym]
            history[ticker].append(rating)

            target = v1_target(history[ticker])
            on_brake = i < brake_until[ticker]
            actual = 0.0 if on_brake else target

            raw = get_holding_return(prices[ticker], date, HOLDING_DAYS)
            if raw is None:
                period_pnls[ticker] = 0.0
                continue

            realized = raw * actual
            stop_hit = False
            if actual > 0:
                min_ret = get_intraperiod_min(prices[ticker], date, HOLDING_DAYS)
                if min_ret is not None and min_ret <= V1_STOP:
                    realized = V1_STOP * actual
                    stop_hit = True

            if actual > 0:
                realized -= 2 * FEE * actual

            period_pnls[ticker] = weight * realized

            leg_value[ticker] *= (1 + realized)
            leg_peak[ticker] = max(leg_peak[ticker], leg_value[ticker])
            leg_dd = leg_value[ticker] / leg_peak[ticker] - 1
            if leg_dd <= V1_BRAKE and not on_brake:
                brake_until[ticker] = i + 2
                leg_peak[ticker] = leg_value[ticker]
                notes.append(f"{ticker[:3]}_BRAKE")
            if stop_hit:
                notes.append(f"{ticker[:3]}_STOP")
            if on_brake:
                notes.append(f"{ticker[:3]}_brake")

        port_pnl = sum(period_pnls.values())
        portfolio *= (1 + port_pnl)
        monthly_returns.append(port_pnl)

        if i % 6 == 0 or i == len(common_yms) - 1:
            row = f"{ym:10} {portfolio:>8.3f} "
            for ticker, _ in UNIVERSE:
                row += f"{period_pnls.get(ticker, 0)*100:>+7.2f}% "
            print(f"{row}  {' '.join(notes)}")

    mr = pd.Series(monthly_returns)
    final_ret = portfolio - 1
    eq = pd.Series([1.0] + [(1 + r) for r in monthly_returns]).cumprod()
    max_dd = float((eq / eq.cummax() - 1).min())
    sharpe = float(mr.mean() / mr.std() * (12 ** 0.5))
    n_years = len(monthly_returns) / 12
    cagr = (1 + final_ret) ** (1 / n_years) - 1
    win = int((mr > 0).sum())

    naive_returns = []
    for ym in common_yms:
        period = 0.0
        for ticker, weight in UNIVERSE:
            date, _ = sig[ticker][ym]
            r = get_holding_return(prices[ticker], date, HOLDING_DAYS)
            if r is None:
                continue
            period += weight * r
        naive_returns.append(period)
    naive_eq = pd.Series([1.0] + [(1 + r) for r in naive_returns]).cumprod()
    naive_ret = float(naive_eq.iloc[-1] - 1)
    naive_dd = float((naive_eq / naive_eq.cummax() - 1).min())
    naive_sharpe = float(pd.Series(naive_returns).mean() / pd.Series(naive_returns).std() * (12 ** 0.5))
    naive_cagr = (1 + naive_ret) ** (1 / n_years) - 1

    print("\n" + "=" * 60)
    print(f"BTC 60% + SOL 40% portfolio  ({n_years:.1f} years)")
    print()
    print(f"Naive weighted Buy&Hold:")
    print(f"  Total: {naive_ret*100:+8.1f}%   CAGR {naive_cagr*100:+5.1f}%   "
          f"DD {naive_dd*100:+6.1f}%   Sharpe {naive_sharpe:.2f}")
    print(f"Strategy V1 on both legs:")
    print(f"  Total: {final_ret*100:+8.1f}%   CAGR {cagr*100:+5.1f}%   "
          f"DD {max_dd*100:+6.1f}%   Sharpe {sharpe:.2f}")
    print(f"  Win months: {win}/{len(monthly_returns)} = {win/len(monthly_returns)*100:.0f}%")


if __name__ == "__main__":
    main()
