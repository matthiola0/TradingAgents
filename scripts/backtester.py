"""Pure-analysis backtester for TradingAgents decisions.

No LLM calls happen here — this module only:

1. Loads decisions from the persistent memory log
   (``~/.tradingagents/memory/trading_memory.md`` by default).
2. Re-fetches realised holding-period returns from yfinance.
3. Maps the 5-tier rating to a position size and computes an equity curve.
4. Reports total return, win rate, Sharpe, and max drawdown.

This separation lets you re-run analysis with different position-sizing or
holding-period assumptions without re-running the (expensive) LLM pipeline.

Usage:

    from scripts.backtester import Backtester
    bt = Backtester(ticker="NVDA", holding_days=5)
    df = bt.build_trades()
    print(bt.metrics(df))
    bt.equity_curve(df).plot()
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.default_config import DEFAULT_CONFIG


# 5-tier rating -> long/short position. Adjust to taste — these are the most
# direct interpretation: Buy = full long, Sell = full short, Hold = flat.
DEFAULT_POSITION_MAP: Dict[str, float] = {
    "Buy": 1.0,
    "Overweight": 0.5,
    "Hold": 0.0,
    "Underweight": -0.5,
    "Sell": -1.0,
}


def _pct_str_to_float(value: Optional[str]) -> Optional[float]:
    """Convert '+5.3%' / '-1.2%' (memory log format) to 0.053 / -0.012."""
    if value is None:
        return None
    s = str(value).strip().rstrip("%")
    if not s or s in {"n/a", "pending"}:
        return None
    try:
        return float(s) / 100.0
    except ValueError:
        return None


@dataclass
class Backtester:
    """Read decisions out of the memory log and turn them into a P&L curve.

    Attributes:
        ticker: Single ticker to backtest. Pass ``None`` for all tickers.
        holding_days: How many trading days to hold each position.
        position_map: Rating -> position size mapping. Override to test
            alternative sizing schemes (e.g. long-only by mapping Sell->0).
        benchmark: Ticker used to compute alpha. Defaults to SPY.
        memory_log_path: Override for the memory log file. Defaults to the
            project default (``~/.tradingagents/memory/trading_memory.md``).
    """

    ticker: Optional[str] = None
    holding_days: int = 5
    position_map: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_POSITION_MAP))
    benchmark: str = "SPY"
    memory_log_path: Optional[str] = None

    def __post_init__(self) -> None:
        cfg = DEFAULT_CONFIG.copy()
        if self.memory_log_path:
            cfg["memory_log_path"] = self.memory_log_path
        self._log = TradingMemoryLog(cfg)

    # ----- entry-point: full pipeline -----

    def run(self) -> Dict[str, object]:
        """Build trades and return a dict of {trades, equity_curve, metrics, baseline}."""
        trades = self.build_trades()
        if trades.empty:
            return {"trades": trades, "equity_curve": pd.Series(dtype=float),
                    "metrics": {}, "baseline": pd.Series(dtype=float)}
        curve = self.equity_curve(trades)
        baseline = self.buy_and_hold_curve(trades)
        return {
            "trades": trades,
            "equity_curve": curve,
            "metrics": self.metrics(trades, curve),
            "baseline": baseline,
        }

    # ----- step 1: load decisions from the memory log -----

    def build_trades(self) -> pd.DataFrame:
        """Return a DataFrame of decisions filtered to the chosen ticker.

        Columns: date, ticker, rating, position, log_raw_return,
        log_alpha_return, holding_days_logged.

        Rows where no rating could be parsed are dropped.
        """
        rows = []
        for entry in self._log.load_entries():
            if self.ticker and entry["ticker"] != self.ticker:
                continue
            rating = entry.get("rating")
            position = self.position_map.get(rating)
            if position is None:
                continue
            rows.append({
                "date": entry["date"],
                "ticker": entry["ticker"],
                "rating": rating,
                "position": position,
                "log_raw_return": _pct_str_to_float(entry.get("raw")),
                "log_alpha_return": _pct_str_to_float(entry.get("alpha")),
                "holding_days_logged": entry.get("holding"),
                "pending": bool(entry.get("pending")),
            })
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df

    # ----- step 2: re-fetch realised returns -----

    def attach_realised_returns(self, trades: pd.DataFrame) -> pd.DataFrame:
        """Re-fetch holding-period returns from yfinance, adding raw+alpha cols.

        Trusts the user-supplied ``holding_days`` — does not reuse the value
        baked into the memory log, since you may want to backtest a different
        holding period than the framework's default 5 days.
        """
        if trades.empty:
            return trades
        trades = trades.copy()
        raw, alpha, actual_days = [], [], []
        for _, row in trades.iterrows():
            r, a, n = self._fetch_return(row["ticker"], row["date"])
            raw.append(r)
            alpha.append(a)
            actual_days.append(n)
        trades["raw_return"] = raw
        trades["alpha_return"] = alpha
        trades["actual_holding_days"] = actual_days
        trades["trade_pnl"] = trades["raw_return"] * trades["position"]
        return trades

    def _fetch_return(self, ticker: str, entry_date: pd.Timestamp):
        end = (entry_date + pd.Timedelta(days=self.holding_days + 7)).strftime("%Y-%m-%d")
        start = entry_date.strftime("%Y-%m-%d")
        try:
            stock = yf.Ticker(ticker).history(start=start, end=end)
            bench = yf.Ticker(self.benchmark).history(start=start, end=end)
        except Exception:
            return None, None, None
        if len(stock) < 2 or len(bench) < 2:
            return None, None, None
        n = min(self.holding_days, len(stock) - 1, len(bench) - 1)
        raw = (stock["Close"].iloc[n] - stock["Close"].iloc[0]) / stock["Close"].iloc[0]
        bench_ret = (bench["Close"].iloc[n] - bench["Close"].iloc[0]) / bench["Close"].iloc[0]
        return float(raw), float(raw - bench_ret), int(n)

    # ----- step 3: equity curve -----

    def equity_curve(self, trades: pd.DataFrame) -> pd.Series:
        """Compounded equity curve assuming each trade is independent.

        Each rating becomes one trade; trades are *not* re-balanced or stacked
        — the curve compounds (1 + trade_pnl) chronologically. This matches
        how a discretionary trader would treat each rating as its own bet.
        """
        if "trade_pnl" not in trades.columns:
            trades = self.attach_realised_returns(trades)
        rets = trades.dropna(subset=["trade_pnl"]).set_index("date")["trade_pnl"]
        if rets.empty:
            return pd.Series(dtype=float)
        return (1.0 + rets).cumprod()

    def buy_and_hold_curve(self, trades: pd.DataFrame) -> pd.Series:
        """Same-period buy-and-hold of the underlying as a baseline."""
        if trades.empty:
            return pd.Series(dtype=float)
        ticker = trades["ticker"].iloc[0]
        start = trades["date"].min().strftime("%Y-%m-%d")
        end = (trades["date"].max() + pd.Timedelta(days=self.holding_days + 7)).strftime("%Y-%m-%d")
        try:
            df = yf.Ticker(ticker).history(start=start, end=end)
        except Exception:
            return pd.Series(dtype=float)
        if df.empty:
            return pd.Series(dtype=float)
        return (df["Close"] / df["Close"].iloc[0])

    # ----- step 4: metrics -----

    def metrics(self, trades: pd.DataFrame, curve: Optional[pd.Series] = None) -> Dict[str, float]:
        """Compute summary stats on the equity curve.

        Sharpe is annualised under the assumption trades happen weekly
        (52 periods/year). If you change frequency, override ``periods_per_year``
        when scaling externally.
        """
        if curve is None:
            curve = self.equity_curve(trades)
        if curve.empty:
            return {}
        rets = curve.pct_change().dropna()
        wins = trades.dropna(subset=["trade_pnl"])["trade_pnl"]
        sharpe = (rets.mean() / rets.std() * math.sqrt(52)) if rets.std() else 0.0
        peak = curve.cummax()
        drawdown = (curve / peak - 1.0).min()

        return {
            "n_trades": int(len(wins)),
            "n_pending": int((trades["pending"]).sum()) if "pending" in trades else 0,
            "total_return": float(curve.iloc[-1] - 1.0),
            "win_rate": float((wins > 0).mean()) if len(wins) else 0.0,
            "avg_trade_pnl": float(wins.mean()) if len(wins) else 0.0,
            "sharpe_weekly_ann": float(sharpe),
            "max_drawdown": float(drawdown),
            "rating_distribution": trades["rating"].value_counts().to_dict(),
        }


# Convenience: use as a script.
def _cli() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Backtest TradingAgents memory log.")
    parser.add_argument("--ticker", default=None,
                        help="Single ticker to backtest. Default: all tickers.")
    parser.add_argument("--holding-days", type=int, default=5)
    parser.add_argument("--memory-log-path", default=None)
    parser.add_argument("--csv", default=None,
                        help="Optional path to dump the trades dataframe to CSV.")
    args = parser.parse_args()

    bt = Backtester(
        ticker=args.ticker,
        holding_days=args.holding_days,
        memory_log_path=args.memory_log_path,
    )

    trades = bt.build_trades()
    if trades.empty:
        print("No trades found in memory log. "
              "Run scripts/run_backtest.py first to populate it.")
        return 1

    trades = bt.attach_realised_returns(trades)
    curve = bt.equity_curve(trades)
    stats = bt.metrics(trades, curve)
    baseline = bt.buy_and_hold_curve(trades)

    print()
    print(f"Trades: {len(trades)}  ({stats.get('n_pending', 0)} pending in memory log)")
    print(f"Period: {trades['date'].min().date()} -> {trades['date'].max().date()}")
    print()
    print("Rating distribution:")
    for rating, n in stats.get("rating_distribution", {}).items():
        print(f"  {rating:<13} {n}")
    print()
    print("Performance:")
    print(f"  Total return        {stats['total_return']:+.2%}")
    print(f"  Win rate            {stats['win_rate']:.1%}")
    print(f"  Avg trade P&L       {stats['avg_trade_pnl']:+.2%}")
    print(f"  Sharpe (weekly,ann) {stats['sharpe_weekly_ann']:.2f}")
    print(f"  Max drawdown        {stats['max_drawdown']:.2%}")
    if not baseline.empty:
        bh_return = float(baseline.iloc[-1] - 1.0)
        print(f"  Buy-and-hold        {bh_return:+.2%}  (baseline)")

    if args.csv:
        trades.to_csv(args.csv, index=False)
        print(f"\nTrades dumped to {args.csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
