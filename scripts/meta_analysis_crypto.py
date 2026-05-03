"""Compare 2022 alpha: stocks vs crypto.

Asks whether the framework's de-risking signal generalises beyond US
equities to BTC/ETH.

Usage:
    python scripts/meta_analysis_crypto.py
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import yfinance as yf

POS = {"Buy": 1.0, "Overweight": 0.5, "Hold": 0.0, "Underweight": -0.5, "Sell": -1.0}
HOLDING_DAYS = 20
STOCKS = ["NVDA", "TSLA", "AAPL", "META"]
CRYPTOS = ["BTC-USD", "ETH-USD"]


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
        rows.append({"date": date_str, "ticker": ticker, "rating": rating,
                     "raw": raw, "position": pos, "pnl": raw * pos})
    return pd.DataFrame(rows)


def report(df: pd.DataFrame, label: str) -> None:
    print(f"\n{label}")
    print("-" * 70)
    print(f"{'ticker':10} {'naive':>10} {'strategy':>10} {'alpha':>10}  ratings")
    for t in df["ticker"].unique():
        sub = df[df["ticker"] == t]
        naive = (1 + sub["raw"]).prod() - 1
        strat = (1 + sub["pnl"]).prod() - 1
        rc = sub["rating"].value_counts()
        rstr = " / ".join(f"{c}{r[0]}" for r, c in rc.items())
        print(f"{t:10} {naive*100:>+9.1f}% {strat*100:>+9.1f}% {(strat-naive)*100:>+8.1f}pp  {rstr}")
    naive_pool = df.groupby("date")["raw"].mean()
    strat_pool = df.groupby("date")["pnl"].mean()
    nt = (1 + naive_pool).prod() - 1
    st = (1 + strat_pool).prod() - 1
    print(f"{'POOL':10} {nt*100:>+9.1f}% {st*100:>+9.1f}% {(st-nt)*100:>+8.1f}pp")
    de_risk = df[df["position"] < 1.0]
    correct = int((de_risk["raw"] < 0).sum())
    n = len(de_risk)
    base_neg_rate = (df["raw"] < 0).mean() * 100
    lift = correct / n * 100 - base_neg_rate
    print(f"  De-risk precision: {correct}/{n} = {correct/n*100:.0f}%  "
          f"(base rate: {base_neg_rate:.0f}%)  lift: {lift:+.0f}pp")
    # Dumb-half-position baseline: every month at 0.5x. Strategy must beat
    # this to claim it's actually picking when to de-risk vs always being cautious.
    dumb_pool = df.groupby("date")["raw"].mean() * 0.5
    sp = df.groupby("date")["pnl"].mean()
    dumb = (1 + dumb_pool).prod() - 1
    strat_pool = (1 + sp).prod() - 1
    edge = (strat_pool - dumb) * 100
    print(f"  Strategy vs dumb-50%-position-always: {strat_pool*100:+.1f}% "
          f"vs {dumb*100:+.1f}% = {edge:+.1f}pp (this is the true signal alpha)")


def main() -> None:
    log_path = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"
    text = log_path.read_text(encoding="utf-8")
    stocks_df = pd.concat([per_ticker(text, t) for t in STOCKS], ignore_index=True)
    crypto_df = pd.concat([per_ticker(text, t) for t in CRYPTOS], ignore_index=True)

    print("=" * 70)
    print("2022 BACKTEST: STOCKS vs CRYPTO")
    print("=" * 70)
    report(stocks_df, "STOCKS — NVDA / TSLA / AAPL / META (N=48)")
    report(crypto_df, "CRYPTO — BTC-USD / ETH-USD (N=24)")

    print()
    print("Combined 6-asset equal-weight portfolio:")
    all_df = pd.concat([stocks_df, crypto_df], ignore_index=True)
    np = all_df.groupby("date")["raw"].mean()
    sp = all_df.groupby("date")["pnl"].mean()
    print(f"  Naive every-month Buy: {((1+np).prod()-1)*100:+.1f}%")
    print(f"  TradingAgents:         {((1+sp).prod()-1)*100:+.1f}%")
    print(f"  Alpha:                 {((1+sp).prod()-(1+np).prod())*100:+.1f}pp")


if __name__ == "__main__":
    main()
