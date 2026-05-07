"""End-to-end weekly automation: generate signals -> execute trades.

Designed for cron / Task Scheduler. Runs both legs of the BTC + SOL
portfolio with full config (market+news+fundamentals analysts,
debate=1, risk=1). Then calls live_trader.py.

Use --live to actually place Binance orders (default is dry run).

Usage (Sunday 23:00 UTC):
    python scripts/weekly_runner.py
    # or for real money:
    python scripts/weekly_runner.py --live
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

TICKERS = ["BTC-USD", "SOL-USD"]
SIGNAL_RETRIES = 3
RETRY_DELAY_SEC = 60


def first_monday_of_current_month(today) -> str:
    """Return the first Monday of the month containing `today`, ISO format.

    The framework was backtested with monthly first-Monday cadence; live
    trading should target the same date so signals align with backtest data.
    If today is BEFORE the first Monday of this month, fall back to the
    first Monday of LAST month so we always have a target.
    """
    from datetime import date, timedelta
    # Walk forward from day 1 to find first Monday
    first = today.replace(day=1)
    while first.weekday() != 0:
        first += timedelta(days=1)
    if first > today:
        # Roll back to previous month
        prev_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        first = prev_month
        while first.weekday() != 0:
            first += timedelta(days=1)
    return first.isoformat()


def generate_signal(ticker: str, today_iso: str, config: str = "full") -> bool:
    """Run propagate for ticker on today's date. Returns True on success."""
    for attempt in range(1, SIGNAL_RETRIES + 1):
        print(f"\n[{datetime.now(timezone.utc).isoformat()}] Generating signal for {ticker} (attempt {attempt})")
        rc = subprocess.run([
            PYTHON, str(REPO / "scripts" / "run_backtest.py"),
            "--ticker", ticker,
            "--start", today_iso, "--end", today_iso,
            "--frequency", "monthly",
            "--config", config,
        ], cwd=str(REPO)).returncode
        if rc == 0:
            return True
        print(f"  Failed (rc={rc}); retrying in {RETRY_DELAY_SEC}s...")
        time.sleep(RETRY_DELAY_SEC)
    print(f"  Giving up on {ticker} after {SIGNAL_RETRIES} attempts.")
    return False


def execute_trader(live: bool, portfolio_usd: float = None) -> int:
    args = [PYTHON, str(REPO / "scripts" / "live_trader.py")]
    if live:
        args.append("--live")
    if portfolio_usd is not None:
        args.extend(["--portfolio-usd", str(portfolio_usd)])
    print(f"\n[{datetime.now(timezone.utc).isoformat()}] Calling live_trader.py "
          f"({'LIVE' if live else 'DRY RUN'})")
    return subprocess.run(args, cwd=str(REPO)).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="Place real orders (default: dry run)")
    ap.add_argument("--config", choices=["minimal", "full"], default="full",
                    help="Signal generation config (default: full)")
    ap.add_argument("--portfolio-usd", type=float, default=1000.0,
                    help="Paper portfolio NAV (ignored in live mode)")
    args = ap.parse_args()

    today_obj = datetime.now(timezone.utc).date()
    today = today_obj.isoformat()
    target = first_monday_of_current_month(today_obj)
    print(f"=== Weekly run on {today} (UTC) ===")
    print(f"Target signal date: {target} (first Monday of current month)")
    print(f"Tickers: {TICKERS}")
    print(f"Signal config: {args.config}")
    print(f"Mode: {'LIVE' if args.live else 'DRY RUN'}")

    n_ok = 0
    for t in TICKERS:
        if generate_signal(t, target, args.config):
            n_ok += 1
    print(f"\nSignal generation: {n_ok}/{len(TICKERS)} succeeded")
    if n_ok == 0:
        print("All signals failed — skipping trader.")
        return 1

    rc = execute_trader(args.live, args.portfolio_usd if not args.live else None)
    return rc


if __name__ == "__main__":
    sys.exit(main())
