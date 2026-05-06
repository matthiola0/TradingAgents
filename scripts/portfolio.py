"""Multi-asset portfolio: BTC (Strategy V1) + NVDA (Strategy V2).

Combines the two asset-class-tuned strategies into a single 50/50 weighted
portfolio that rebalances monthly. Tests whether the combined Sharpe is
better than either leg alone.

Coverage: BTC monthly 2018-2025 (96 entries) + NVDA monthly 2018-2024 H1
(78 entries). Aligns to common dates and rebalances 50/50 each month.

Run:
    python scripts/portfolio.py
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

# Strategy V1 (BTC): confluence + stop loss + brake
V1_STOP = -0.15
V1_BRAKE = -0.25

# Strategy V2 (NVDA): no stop, no confluence, wider brake
V2_BRAKE = -0.30
V2_POS_MAP = {"Buy": 1.0, "Overweight": 0.7, "Hold": 0.0,
              "Underweight": 0.0, "Sell": 0.0}


def load_monthly(ticker: str) -> dict[str, str]:
    text = LOG.read_text(encoding="utf-8")
    pattern = re.compile(rf"\[(\d{{4}}-\d{{2}}-\d{{2}}) \| {re.escape(ticker)} \| (\w+) \|")
    entries = pattern.findall(text)
    by_ym = {}
    for date, rating in sorted(entries):
        ym = date[:7]
        if ym not in by_ym:
            by_ym[ym] = (date, rating)
    return by_ym  # ym -> (date, rating)


def get_holding_return(prices: pd.Series, entry_date: str, holding_days: int) -> Optional[float]:
    entry = pd.Timestamp(entry_date)
    avail = prices[prices.index >= entry]
    if len(avail) < holding_days + 1:
        return None
    return float((avail.iloc[holding_days] - avail.iloc[0]) / avail.iloc[0])


def get_intraperiod_min(prices: pd.Series, entry_date: str, holding_days: int) -> Optional[float]:
    entry = pd.Timestamp(entry_date)
    avail = prices[prices.index >= entry]
    if len(avail) < 2:
        return None
    p0 = avail.iloc[0]
    period = avail.iloc[1: holding_days + 1]
    if period.empty:
        return None
    return float((period.min() - p0) / p0)


def btc_v1_position(history: list[str]) -> float:
    """Strategy V1 confluence rule for BTC."""
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


def nvda_v2_position(rating: str) -> float:
    """Strategy V2 mapping for NVDA."""
    return V2_POS_MAP.get(rating, 0.0)


def main() -> None:
    btc = load_monthly("BTC-USD")
    nvda = load_monthly("NVDA")
    common_yms = sorted(set(btc.keys()) & set(nvda.keys()))
    print(f"BTC monthly: {len(btc)}    NVDA monthly: {len(nvda)}    common months: {len(common_yms)}")

    btc_hist = yf.Ticker("BTC-USD").history(start="2017-12-15", end="2026-03-01")
    btc_hist.index = btc_hist.index.tz_localize(None)
    btc_prices = btc_hist["Close"]

    nvda_hist = yf.Ticker("NVDA").history(start="2017-12-15", end="2026-03-01")
    nvda_hist.index = nvda_hist.index.tz_localize(None)
    nvda_prices = nvda_hist["Close"]

    # Run portfolio: each leg gets 50% allocation; rebalance every month
    btc_history: list[str] = []
    btc_brake_until = -1
    nvda_brake_until = -1

    btc_leg = 1.0      # leg-level NAV (capital * V1 sub-strategy)
    nvda_leg = 1.0
    btc_peak = 1.0
    nvda_peak = 1.0

    portfolio_equity = 1.0
    portfolio_peak = 1.0
    monthly_returns = []

    print()
    print(f"{'date':10} {'btc':>5} {'nvda':>5} {'btc_pos':>8} {'nvda_pos':>9} "
          f"{'btc_pnl':>9} {'nvda_pnl':>9} {'port_pnl':>9} {'port_NAV':>9}")
    print("-" * 95)

    for i, ym in enumerate(common_yms):
        btc_date, btc_rating = btc[ym]
        nvda_date, nvda_rating = nvda[ym]

        btc_history.append(btc_rating)

        # BTC V1 logic
        btc_target = btc_v1_position(btc_history)
        btc_on_brake = i < btc_brake_until
        btc_actual = 0.0 if btc_on_brake else btc_target

        # NVDA V2 logic
        nvda_target = nvda_v2_position(nvda_rating)
        nvda_on_brake = i < nvda_brake_until
        nvda_actual = 0.0 if nvda_on_brake else nvda_target

        # Compute realized returns
        btc_raw = get_holding_return(btc_prices, btc_date, HOLDING_DAYS)
        nvda_raw = get_holding_return(nvda_prices, nvda_date, HOLDING_DAYS)
        if btc_raw is None or nvda_raw is None:
            continue

        # BTC V1 stop loss check
        if btc_actual > 0:
            btc_min = get_intraperiod_min(btc_prices, btc_date, HOLDING_DAYS)
            if btc_min is not None and btc_min <= V1_STOP:
                btc_realized = V1_STOP * btc_actual
            else:
                btc_realized = btc_raw * btc_actual
        else:
            btc_realized = 0.0

        # NVDA V2 (no stop loss)
        nvda_realized = nvda_raw * nvda_actual if nvda_actual > 0 else 0.0

        # Fees
        if btc_actual > 0:
            btc_realized -= 2 * FEE * btc_actual
        if nvda_actual > 0:
            nvda_realized -= 2 * FEE * nvda_actual

        # Update leg NAVs (rebalance back to 50/50 of total at start of period)
        # Realised portfolio return = average of leg returns (50/50)
        port_pnl = 0.5 * btc_realized + 0.5 * nvda_realized
        portfolio_equity *= (1 + port_pnl)
        portfolio_peak = max(portfolio_peak, portfolio_equity)
        monthly_returns.append(port_pnl)

        # Update leg pseudo-tracking for brake check
        btc_leg *= (1 + btc_realized)
        nvda_leg *= (1 + nvda_realized)
        btc_peak = max(btc_peak, btc_leg)
        nvda_peak = max(nvda_peak, nvda_leg)

        # Per-leg drawdown brake
        btc_dd = btc_leg / btc_peak - 1
        if btc_dd <= V1_BRAKE and not btc_on_brake:
            btc_brake_until = i + 2
            btc_peak = btc_leg

        nvda_dd = nvda_leg / nvda_peak - 1
        if nvda_dd <= V2_BRAKE and not nvda_on_brake:
            nvda_brake_until = i + 2
            nvda_peak = nvda_leg

        if i % 6 == 0 or i == len(common_yms) - 1:  # print every 6 months for brevity
            print(f"{btc_date:10} {btc_rating[0]:>5} {nvda_rating[0]:>5} {btc_actual:>7.2f}x {nvda_actual:>8.2f}x "
                  f"{btc_realized*100:>+7.2f}% {nvda_realized*100:>+7.2f}% {port_pnl*100:>+7.2f}% {portfolio_equity:>8.3f}")

    if not monthly_returns:
        print("No data")
        return

    # Compute metrics
    mr = pd.Series(monthly_returns)
    final_ret = portfolio_equity - 1
    eq = pd.Series([1.0] + [(1 + r) for r in monthly_returns]).cumprod()
    max_dd = float((eq / eq.cummax() - 1).min())
    sharpe = mr.mean() / mr.std() * (12 ** 0.5) if mr.std() > 0 else 0
    n_years = len(monthly_returns) / 12
    cagr = (1 + final_ret) ** (1 / n_years) - 1 if n_years > 0 else 0
    win_months = (mr > 0).sum()

    # Naive 50/50 baseline (no signal, hold both 50/50)
    naive_pnls = []
    for ym in common_yms:
        btc_date, _ = btc[ym]
        nvda_date, _ = nvda[ym]
        b = get_holding_return(btc_prices, btc_date, HOLDING_DAYS)
        n = get_holding_return(nvda_prices, nvda_date, HOLDING_DAYS)
        if b is not None and n is not None:
            naive_pnls.append(0.5 * b + 0.5 * n)
    naive_eq = pd.Series([1.0] + [(1 + r) for r in naive_pnls]).cumprod()
    naive_ret = float(naive_eq.iloc[-1] - 1)
    naive_dd = float((naive_eq / naive_eq.cummax() - 1).min())
    naive_cagr = (1 + naive_ret) ** (1 / n_years) - 1 if n_years > 0 else 0

    print()
    print("=" * 60)
    print(f"Naive 50/50 BTC + NVDA")
    print(f"  Total return:    {naive_ret*100:+.1f}%")
    print(f"  CAGR:            {naive_cagr*100:+.1f}%")
    print(f"  Max drawdown:    {naive_dd*100:+.1f}%")
    print()
    print(f"Strategy V1+V2 portfolio (50/50 BTC + NVDA, rebalanced monthly)")
    print(f"  Total return:    {final_ret*100:+.1f}%")
    print(f"  CAGR:            {cagr*100:+.1f}%")
    print(f"  Max drawdown:    {max_dd*100:+.1f}%")
    print(f"  Sharpe (annual): {sharpe:.2f}")
    print(f"  Win months:      {win_months}/{len(monthly_returns)} = {win_months/len(monthly_returns)*100:.0f}%")
    print(f"  Years:           {n_years:.1f}")


if __name__ == "__main__":
    main()
