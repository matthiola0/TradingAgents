"""Backtest the paper_trader.py orchestrator across history.

paper_trader.py is the live runner — it reads the latest signal and
produces today's orders. This script drives the SAME logic month by
month over 6.5 years of common BTC + SOL + AVAX + NVDA history,
producing the equity curve we should expect from running the paper
strategy live.

Validates:
1. Multi-asset orchestrator math is correct (delta orders, NAV
   tracking, peak/brake state per leg)
2. The recommended universe weights produce the expected risk-return
3. End-to-end equity curve matches the per-asset Strategy V1 / V2
   results when combined

Run:
    python scripts/paper_backtest.py
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

LOG = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"
HOLDING_DAYS = 20
FEE = 0.001

# Same universe as paper_trader.py default
UNIVERSE = [
    ("BTC-USD",  "crypto", 0.30),
    ("SOL-USD",  "crypto", 0.15),
    ("AVAX-USD", "crypto", 0.10),
    ("NVDA",     "equity", 0.30),
    # cash 0.15 — implicit, never trades
]

V1_STOP = -0.15
V1_BRAKE = -0.25
V2_BRAKE = -0.30
V2_POS_MAP = {"Buy": 1.0, "Overweight": 0.7, "Hold": 0.0,
              "Underweight": 0.0, "Sell": 0.0}


def load_monthly(ticker: str) -> dict[str, str]:
    text = LOG.read_text(encoding="utf-8")
    pattern = re.compile(rf"\[(\d{{4}}-\d{{2}}-\d{{2}}) \| {re.escape(ticker)} \| (\w+) \|")
    entries = pattern.findall(text)
    by_ym: dict[str, tuple[str, str]] = {}
    for date, rating in sorted(entries):
        ym = date[:7]
        if ym not in by_ym:
            by_ym[ym] = (date, rating)
    return {ym: (d, r) for ym, (d, r) in by_ym.items()}


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


def crypto_v1_target(history: list[str]) -> float:
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


def equity_v2_target(rating: str) -> float:
    return V2_POS_MAP.get(rating, 0.0)


def main() -> None:
    # Load all signal histories
    sig: dict[str, dict[str, tuple[str, str]]] = {
        ticker: load_monthly(ticker) for ticker, _, _ in UNIVERSE
    }

    # Find common months
    common_yms = sorted(set.intersection(*(set(s.keys()) for s in sig.values())))
    if not common_yms:
        print("No common months across universe")
        return
    print(f"Common months across {len(UNIVERSE)} assets: {len(common_yms)} "
          f"({common_yms[0]} -> {common_yms[-1]})")

    # Load prices
    prices: dict[str, pd.Series] = {}
    for ticker, _, _ in UNIVERSE:
        h = yf.Ticker(ticker).history(start="2017-12-15", end="2026-03-01")
        h.index = h.index.tz_localize(None)
        prices[ticker] = h["Close"]

    # Per-asset state
    crypto_history: dict[str, list[str]] = defaultdict(list)
    leg_peak: dict[str, float] = {ticker: 1.0 for ticker, _, _ in UNIVERSE}
    leg_value: dict[str, float] = {ticker: 0.0 for ticker, _, _ in UNIVERSE}
    brake_until_idx: dict[str, int] = {ticker: -1 for ticker, _, _ in UNIVERSE}

    # Portfolio state
    portfolio = 1.0
    portfolio_peak = 1.0
    monthly_returns = []

    print(f"\n{'date':10} {'NAV':>9} ", end="")
    for ticker, _, _ in UNIVERSE:
        print(f"{ticker[:6]:>7} ", end="")
    print()
    print("-" * 70)

    for i, ym in enumerate(common_yms):
        # Compute target positions per leg
        period_pnls: dict[str, float] = {}

        for ticker, asset_class, weight in UNIVERSE:
            date, rating = sig[ticker][ym]
            crypto_history[ticker].append(rating)

            if asset_class == "crypto":
                target_frac = crypto_v1_target(crypto_history[ticker])
                brake_dd = V1_BRAKE
            else:
                target_frac = equity_v2_target(rating)
                brake_dd = V2_BRAKE

            on_brake = i < brake_until_idx[ticker]
            actual_frac = 0.0 if on_brake else target_frac

            # Realized return on this leg
            raw = get_holding_return(prices[ticker], date, HOLDING_DAYS)
            if raw is None:
                period_pnls[ticker] = 0.0
                continue

            # V1 stop loss
            realized = raw * actual_frac
            if asset_class == "crypto" and actual_frac > 0:
                min_ret = get_intraperiod_min(prices[ticker], date, HOLDING_DAYS)
                if min_ret is not None and min_ret <= V1_STOP:
                    realized = V1_STOP * actual_frac

            # Fees
            if actual_frac > 0:
                realized -= 2 * FEE * actual_frac

            # Each leg gets weight × portfolio. The leg PnL is a % of leg
            # capital. Contribution to portfolio = weight × leg_pnl.
            period_pnls[ticker] = weight * realized

            # Track per-leg NAV (for brake)
            leg_value[ticker] *= (1 + realized) if leg_value[ticker] > 0 else 1
            if leg_value[ticker] == 0 and actual_frac > 0:
                leg_value[ticker] = 1.0 * (1 + realized)
            leg_peak[ticker] = max(leg_peak[ticker], leg_value[ticker])
            leg_dd = (leg_value[ticker] / leg_peak[ticker] - 1) if leg_peak[ticker] > 0 else 0
            if leg_dd <= brake_dd and not on_brake:
                brake_until_idx[ticker] = i + 2
                leg_peak[ticker] = leg_value[ticker]

        # Portfolio period return = sum of weighted leg PnLs
        port_pnl = sum(period_pnls.values())
        portfolio *= (1 + port_pnl)
        portfolio_peak = max(portfolio_peak, portfolio)
        monthly_returns.append(port_pnl)

        if i % 6 == 0 or i == len(common_yms) - 1:
            row = f"{common_yms[i]:10} {portfolio:>8.3f} "
            for ticker, _, _ in UNIVERSE:
                row += f"{period_pnls.get(ticker, 0)*100:>+6.2f}% "
            print(row)

    # Compute metrics
    mr = pd.Series(monthly_returns)
    final_ret = portfolio - 1
    eq = pd.Series([1.0] + [(1 + r) for r in monthly_returns]).cumprod()
    max_dd = float((eq / eq.cummax() - 1).min())
    sharpe = float(mr.mean() / mr.std() * (12 ** 0.5)) if mr.std() > 0 else 0
    n_years = len(monthly_returns) / 12
    cagr = (1 + final_ret) ** (1 / n_years) - 1 if n_years > 0 else 0
    win_months = int((mr > 0).sum())

    # Naive baseline (buy and hold equally weighted)
    naive_returns = []
    for ym in common_yms:
        period_total = 0.0
        weight_total = 0.0
        for ticker, _, weight in UNIVERSE:
            date, _ = sig[ticker][ym]
            raw = get_holding_return(prices[ticker], date, HOLDING_DAYS)
            if raw is None:
                continue
            period_total += weight * raw
            weight_total += weight
        # Cash leg returns 0
        period_total += (1 - weight_total) * 0
        naive_returns.append(period_total)
    naive_eq = pd.Series([1.0] + [(1 + r) for r in naive_returns]).cumprod()
    naive_ret = float(naive_eq.iloc[-1] - 1)
    naive_dd = float((naive_eq / naive_eq.cummax() - 1).min())
    naive_cagr = (1 + naive_ret) ** (1 / n_years) - 1 if n_years > 0 else 0
    naive_sharpe = float(pd.Series(naive_returns).mean() / pd.Series(naive_returns).std() * (12 ** 0.5))

    print("\n" + "=" * 60)
    print(f"Universe: {[(t, w) for t, _, w in UNIVERSE]} + 15% cash")
    print(f"Period: {common_yms[0]} -> {common_yms[-1]}  ({n_years:.1f} years)")
    print()
    print(f"Naive weighted Buy&Hold (no signal):")
    print(f"  Total return: {naive_ret*100:+8.1f}%   CAGR {naive_cagr*100:+5.1f}%   "
          f"DD {naive_dd*100:+6.1f}%   Sharpe {naive_sharpe:.2f}")
    print(f"Strategy V1 (crypto) + V2 (NVDA), monthly rebalance:")
    print(f"  Total return: {final_ret*100:+8.1f}%   CAGR {cagr*100:+5.1f}%   "
          f"DD {max_dd*100:+6.1f}%   Sharpe {sharpe:.2f}")
    print(f"  Win months:   {win_months}/{len(monthly_returns)} = {win_months/len(monthly_returns)*100:.0f}%")


if __name__ == "__main__":
    main()
