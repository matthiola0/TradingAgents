"""Strategy V1: BTC-Confluence — implementable trading strategy backtest.

Uses memory-log signals only (no new LLM calls). Tests:
- 2-month confluence filter for full position
- Stop loss at -15%
- Drawdown brake at -25% from portfolio peak
- 0.1% per-trade fee (Binance spot)

Compared against:
- Naive Buy-and-hold every month
- Plain Buy=1.0 / OW=0.5 / Hold=0 mapping (the unfiltered baseline)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

LOG = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"
TICKER = "BTC-USD"
HOLDING_DAYS = 20  # monthly cadence — exit at next month's signal
FEE = 0.001  # 0.1% Binance spot
STOP_LOSS = -0.15
DRAWDOWN_BRAKE = -0.25
DRAWDOWN_HALT_PERIODS = 1


@dataclass
class Trade:
    date: str
    rating: str
    target_pos: float        # what the strategy wants
    actual_pos: float        # what it executed (may be 0 due to brake/stop)
    raw_return: float        # market return over holding period
    realized_pnl: float      # what the position actually earned (incl. stop loss / fee)
    stop_loss_hit: bool
    on_brake: bool


def load_btc_monthly() -> list[tuple[str, str]]:
    """Return [(date, rating), ...] for BTC monthly entries from memory log."""
    text = LOG.read_text(encoding="utf-8")
    # Match BTC-USD monthly entries (skip weekly cohorts)
    pattern = re.compile(r"\[(\d{4}-\d{2}-\d{2}) \| BTC-USD \| (\w+) \|")
    entries = pattern.findall(text)
    # Group by year-month and keep only first Monday-ish entry per month
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


def get_intraperiod_min(prices: pd.Series, entry_date: str, holding_days: int) -> Optional[float]:
    """Worst drawdown observed during holding period (used for stop-loss check)."""
    entry = pd.Timestamp(entry_date)
    avail = prices[prices.index >= entry]
    if len(avail) < 2:
        return None
    p0 = avail.iloc[0]
    period = avail.iloc[1: holding_days + 1]
    if period.empty:
        return None
    return float((period.min() - p0) / p0)


def determine_target_position(history: list[str]) -> tuple[float, str]:
    """Apply confluence filter. Returns (target_position, reason).

    history[-1] is the latest rating, history[-2] is the prior month's rating.
    """
    if not history:
        return 0.0, "no signal"
    latest = history[-1]
    prior = history[-2] if len(history) >= 2 else None

    if latest == "Buy" and prior == "Buy":
        return 1.0, "2-month Buy confluence"
    if latest == "Buy":
        return 0.5, "single-month Buy (no prior confluence)"
    if latest == "Overweight":
        return 0.5, "Overweight"
    return 0.0, f"flat ({latest})"


def run_strategy(
    entries: list[tuple[str, str]], prices: pd.Series, *,
    use_confluence: bool, use_stop: bool, use_brake: bool, use_fee: bool,
) -> tuple[list[Trade], float, float]:
    """Run the strategy. Returns (trades, total_return, max_drawdown)."""
    portfolio = 1.0
    peak = 1.0
    brake_until_idx = -1

    trades: list[Trade] = []
    history: list[str] = []

    for i, (date, rating) in enumerate(entries):
        history.append(rating)

        # Determine target position
        if use_confluence:
            target, _ = determine_target_position(history)
        else:
            target = {"Buy": 1.0, "Overweight": 0.5}.get(rating, 0.0)

        # Drawdown brake check
        on_brake = use_brake and i < brake_until_idx
        actual = 0.0 if on_brake else target

        # Get realized return
        raw = get_holding_return(prices, date, HOLDING_DAYS)
        if raw is None:
            continue

        # Stop-loss check (intraperiod)
        stop_hit = False
        if use_stop and actual > 0:
            min_ret = get_intraperiod_min(prices, date, HOLDING_DAYS)
            if min_ret is not None and min_ret <= STOP_LOSS:
                stop_hit = True
                # Realized: stopped out at -15%
                realized = STOP_LOSS * actual
            else:
                realized = raw * actual
        else:
            realized = raw * actual

        # Apply fee on round-trip (entry + exit) on the position size
        if use_fee and actual > 0:
            realized -= 2 * FEE * actual

        portfolio *= (1 + realized)
        peak = max(peak, portfolio)
        drawdown = portfolio / peak - 1
        if use_brake and drawdown <= DRAWDOWN_BRAKE and not on_brake:
            brake_until_idx = i + 1 + DRAWDOWN_HALT_PERIODS
            # Reset peak to current value so the same brake doesn't re-fire
            # immediately on next period (the bug in the prior version).
            peak = portfolio

        trades.append(Trade(
            date=date, rating=rating, target_pos=target, actual_pos=actual,
            raw_return=raw, realized_pnl=realized, stop_loss_hit=stop_hit, on_brake=on_brake,
        ))

    if not trades:
        return [], 0.0, 0.0

    # Compute max drawdown from equity curve
    equity = [1.0]
    for t in trades:
        equity.append(equity[-1] * (1 + t.realized_pnl))
    equity_s = pd.Series(equity)
    max_dd = float((equity_s / equity_s.cummax() - 1).min())

    return trades, portfolio - 1, max_dd


def naive_baseline(entries: list[tuple[str, str]], prices: pd.Series) -> tuple[float, float]:
    """Buy and hold every month — what you'd get blindly long."""
    portfolio = 1.0
    equity = [1.0]
    for date, _ in entries:
        raw = get_holding_return(prices, date, HOLDING_DAYS)
        if raw is None:
            continue
        portfolio *= (1 + raw)
        equity.append(portfolio)
    equity_s = pd.Series(equity)
    max_dd = float((equity_s / equity_s.cummax() - 1).min())
    return portfolio - 1, max_dd


def fmt_table(label: str, total_ret: float, max_dd: float, trades: list[Trade] | None = None) -> str:
    line = f"{label:<40} total={total_ret*100:+8.1f}%   max_dd={max_dd*100:+6.1f}%"
    if trades:
        n = len(trades)
        wins = sum(1 for t in trades if t.realized_pnl > 0)
        zeros = sum(1 for t in trades if t.actual_pos == 0)
        stops = sum(1 for t in trades if t.stop_loss_hit)
        line += f"   N={n}  win={wins}/{n-zeros}  stops={stops}  flat={zeros}"
    return line


def main() -> None:
    entries = load_btc_monthly()
    print(f"BTC monthly cohort: {len(entries)} entries from {entries[0][0]} to {entries[-1][0]}")
    print()

    hist = yf.Ticker(TICKER).history(start="2017-12-15", end="2026-03-01")
    hist.index = hist.index.tz_localize(None)
    prices = hist["Close"]

    # Naive baseline
    naive_ret, naive_dd = naive_baseline(entries, prices)
    print("=" * 95)
    print(fmt_table("Naive Buy&Hold every month (1.0x always)", naive_ret, naive_dd))

    # Plain mapping (no filter)
    trades, ret, dd = run_strategy(entries, prices,
        use_confluence=False, use_stop=False, use_brake=False, use_fee=False)
    print(fmt_table("Plain Buy=1.0/OW=0.5/Hold=0 (no fees)", ret, dd, trades))

    # + fees only
    trades, ret, dd = run_strategy(entries, prices,
        use_confluence=False, use_stop=False, use_brake=False, use_fee=True)
    print(fmt_table("  + 0.1% fee per side", ret, dd, trades))

    # + confluence
    trades, ret, dd = run_strategy(entries, prices,
        use_confluence=True, use_stop=False, use_brake=False, use_fee=True)
    print(fmt_table("  + 2-month Buy confluence", ret, dd, trades))

    # + stop loss
    trades, ret, dd = run_strategy(entries, prices,
        use_confluence=True, use_stop=True, use_brake=False, use_fee=True)
    print(fmt_table("  + stop loss -15%", ret, dd, trades))

    # + drawdown brake (full strategy V1)
    trades, ret, dd = run_strategy(entries, prices,
        use_confluence=True, use_stop=True, use_brake=True, use_fee=True)
    print(fmt_table("Strategy V1 (full, all rules on)", ret, dd, trades))
    print("=" * 95)
    print()

    # Per-trade detail of full strategy
    print("Per-trade detail (Strategy V1):")
    print(f"{'date':12} {'rating':10} {'target':>8} {'actual':>8} {'raw':>9} {'realized':>9}  notes")
    for t in trades:
        notes = []
        if t.stop_loss_hit:
            notes.append("STOP")
        if t.on_brake:
            notes.append("BRAKE")
        notes_str = " ".join(notes)
        print(f"{t.date:12} {t.rating:<10} {t.target_pos:>7.2f}x {t.actual_pos:>7.2f}x "
              f"{t.raw_return*100:>+7.2f}% {t.realized_pnl*100:>+7.2f}%  {notes_str}")


if __name__ == "__main__":
    main()
