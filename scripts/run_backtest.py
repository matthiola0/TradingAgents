"""Drive a TradingAgents backtest by looping ``propagate()`` over a date range.

This script handles only the *data-collection* step — it calls the LLM
pipeline once per (ticker, date) and persists the decisions to the memory
log. After it finishes, run ``scripts/backtester.py`` to compute P&L.

Why split it: LLM calls are expensive and slow. You want a one-shot
collection pass; then you can re-analyse the same decisions under
different position-sizing or holding-period assumptions for free.

Resilience:
- ``checkpoint_enabled`` is on by default, so a crash inside any single
  ``propagate()`` resumes from the last successful node.
- The memory log's idempotency guard ensures re-running a (ticker, date)
  that already has a pending entry is a no-op.

Usage:

    # collect weekly decisions for NVDA across H1 2024 with Haiku
    python scripts/run_backtest.py --ticker NVDA --start 2024-01-01 --end 2024-06-30

    # multi-ticker, monthly, faster
    python scripts/run_backtest.py --tickers NVDA,AAPL,MSFT --frequency monthly \\
        --start 2024-01-01 --end 2024-12-31

After collection finishes:

    python scripts/backtester.py --ticker NVDA
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from datetime import date, timedelta
from typing import Iterable, List

from dotenv import load_dotenv

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

logger = logging.getLogger("backtest")
load_dotenv()


# ---------------------------------------------------------------------------
# Date generators
# ---------------------------------------------------------------------------

def _weekly(start: date, end: date) -> Iterable[date]:
    """Every Monday between start and end (inclusive)."""
    d = start
    while d <= end:
        if d.weekday() == 0:  # Monday
            yield d
        d += timedelta(days=1)


def _monthly(start: date, end: date) -> Iterable[date]:
    """First Monday of each month between start and end."""
    seen = set()
    d = start
    while d <= end:
        key = (d.year, d.month)
        if d.weekday() == 0 and key not in seen:
            seen.add(key)
            yield d
        d += timedelta(days=1)


def _daily(start: date, end: date) -> Iterable[date]:
    """Every weekday between start and end."""
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


_FREQUENCIES = {"weekly": _weekly, "monthly": _monthly, "daily": _daily}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def parse_tickers(args: argparse.Namespace) -> List[str]:
    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if args.ticker:
        return [args.ticker.upper()]
    raise SystemExit("Pass --ticker or --tickers.")


def parse_iso_date(s: str) -> date:
    return date.fromisoformat(s)


def build_config(args: argparse.Namespace) -> dict:
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = args.provider
    config["deep_think_llm"] = args.deep_model
    config["quick_think_llm"] = args.quick_model
    config["max_debate_rounds"] = args.debate_rounds
    config["max_risk_discuss_rounds"] = args.risk_rounds
    config["checkpoint_enabled"] = not args.no_checkpoint
    config["data_vendors"] = {
        "core_stock_apis": args.vendor,
        "technical_indicators": args.vendor,
        "fundamental_data": args.vendor,
        "news_data": args.vendor,
    }
    return config


def run(args: argparse.Namespace) -> int:
    tickers = parse_tickers(args)
    start = parse_iso_date(args.start)
    end = parse_iso_date(args.end)
    if end < start:
        raise SystemExit("--end must be >= --start")

    gen = _FREQUENCIES[args.frequency]
    dates = list(gen(start, end))

    config = build_config(args)
    analysts = [a.strip() for a in args.analysts.split(",") if a.strip()]

    print(f"Backtest plan: {len(tickers)} ticker(s) x {len(dates)} dates "
          f"= {len(tickers) * len(dates)} propagations")
    print(f"  tickers:   {', '.join(tickers)}")
    print(f"  range:     {start} -> {end}  ({args.frequency})")
    print(f"  provider:  {args.provider}  deep={args.deep_model}  quick={args.quick_model}")
    print(f"  analysts:  {analysts}  debate={args.debate_rounds}  risk={args.risk_rounds}")
    print(f"  checkpoint:{config['checkpoint_enabled']}  vendor={args.vendor}")
    print()

    if args.dry_run:
        print("DRY RUN — exiting without invoking the graph.")
        for t in tickers:
            for d in dates:
                print(f"  would propagate({t}, {d.isoformat()})")
        return 0

    ta = TradingAgentsGraph(
        selected_analysts=analysts,
        debug=args.debug,
        config=config,
    )

    n_total = len(tickers) * len(dates)
    n_done = 0
    n_failed = 0

    for t in tickers:
        for d in dates:
            n_done += 1
            iso = d.isoformat()
            print(f"[{n_done}/{n_total}] {t} {iso} ...", end=" ", flush=True)
            try:
                _, decision = ta.propagate(t, iso)
                print(decision)
            except KeyboardInterrupt:
                print("\nInterrupted by user.")
                return 130
            except Exception as exc:  # noqa: BLE001 — backtest must never crash silently
                n_failed += 1
                print(f"FAILED: {exc}")
                if args.verbose:
                    traceback.print_exc()

    print()
    print(f"Done. {n_done - n_failed}/{n_done} succeeded, {n_failed} failed.")
    print("Now run:  python scripts/backtester.py "
          f"--ticker {tickers[0]} --holding-days {args.holding_days}")
    return 0 if n_failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)

    g = p.add_argument_group("instruments")
    g.add_argument("--ticker", help="Single ticker, e.g. NVDA.")
    g.add_argument("--tickers", help="Comma-separated tickers, e.g. NVDA,AAPL,MSFT.")

    g = p.add_argument_group("date range")
    g.add_argument("--start", required=True, help="ISO date YYYY-MM-DD")
    g.add_argument("--end", required=True, help="ISO date YYYY-MM-DD")
    g.add_argument("--frequency", default="weekly", choices=list(_FREQUENCIES))

    g = p.add_argument_group("LLM")
    g.add_argument("--provider", default="anthropic")
    g.add_argument("--deep-model", default="claude-haiku-4-5-20251001")
    g.add_argument("--quick-model", default="claude-haiku-4-5-20251001")

    g = p.add_argument_group("graph")
    g.add_argument("--analysts", default="market",
                   help="Comma-separated subset of: market,social,news,fundamentals")
    g.add_argument("--debate-rounds", type=int, default=0)
    g.add_argument("--risk-rounds", type=int, default=0)
    g.add_argument("--vendor", default="yfinance",
                   help="Data vendor for all categories. Options: yfinance, alpha_vantage")
    g.add_argument("--no-checkpoint", action="store_true",
                   help="Disable LangGraph SQLite checkpointing.")

    g = p.add_argument_group("backtester pass-through")
    g.add_argument("--holding-days", type=int, default=5,
                   help="Used in the 'now run scripts/backtester.py' hint at the end.")

    g = p.add_argument_group("misc")
    g.add_argument("--debug", action="store_true",
                   help="Stream agent messages to stdout (slower, more output).")
    g.add_argument("--verbose", action="store_true", help="Print full tracebacks on failure.")
    g.add_argument("--dry-run", action="store_true",
                   help="List the (ticker, date) pairs that would be processed and exit.")

    args = p.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
