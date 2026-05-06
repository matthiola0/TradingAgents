"""Compare BTC 2022 monthly under two TradingAgents configs:
  Minimal: market only, debate=0, risk=0  (archived)
  Full:    3 analysts (market+news+fundamentals), debate=1, risk=1

Uses the BTC monthly return series from yfinance (with retry) and applies
the V1 strategy mapping to both rating sequences side by side.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
import yfinance as yf

LOG = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"
MIN_PATH = Path.home() / ".tradingagents" / "baselines" / "BTC-USD_2022_minimal.json"

# V1 mapping (no shorts): UW and Sell both go to 0
POS = {"Buy": 1.0, "Overweight": 0.5, "Hold": 0.0,
       "Underweight": 0.0, "Sell": 0.0}
# Aggressive variant — would V1 with shorts help?
POS_SHORT = {"Buy": 1.0, "Overweight": 0.5, "Hold": 0.0,
             "Underweight": -0.5, "Sell": -1.0}


def fetch_btc_with_retry():
    last_exc = None
    for attempt in range(5):
        try:
            h = yf.Ticker("BTC-USD").history(start="2021-12-15", end="2023-02-15")
            if not h.empty:
                h.index = h.index.tz_localize(None)
                return h["Close"]
        except Exception as e:
            last_exc = e
        time.sleep(2 ** attempt)
    raise RuntimeError(f"yfinance kept failing: {last_exc}")


def load_full_config_ratings():
    text = LOG.read_text(encoding="utf-8")
    pat = re.compile(r"\[(2022-\d{2}-\d{2}) \| BTC-USD \| (\w+) \|")
    return pat.findall(text)


def main():
    prices = fetch_btc_with_retry()
    print(f"BTC price series: {len(prices)} rows")

    minimal_data = json.loads(MIN_PATH.read_text(encoding="utf-8"))
    minimal = [(e["date"], e["rating"]) for e in minimal_data["entries"]]
    full = load_full_config_ratings()
    print(f"\nMinimal config: {len(minimal)} entries")
    print(f"Full config:    {len(full)} entries")

    rows = []
    for (date, mr), (_, fr) in zip(minimal, full):
        ts = __import__("pandas").Timestamp(date)
        avail = prices[prices.index >= ts]
        if len(avail) < 21:
            continue
        raw = float((avail.iloc[20] - avail.iloc[0]) / avail.iloc[0])
        rows.append((date, mr, fr, raw))

    print("\n{:12} {:>12} {:>15} {:>10}".format("date", "minimal", "full", "raw_20d"))
    print("-" * 55)
    for date, mr, fr, raw in rows:
        marker = "  ←DIFF" if mr != fr else ""
        print(f"{date:12} {mr:>12} {fr:>15} {raw*100:>+9.1f}%{marker}")

    # Compute strategy returns
    def compute_total(ratings_seq, raws, pos_map):
        nav = 1.0
        for r, raw in zip(ratings_seq, raws):
            pos = pos_map.get(r, 0.0)
            nav *= (1 + pos * raw)
        return nav - 1

    raws = [r for _, _, _, r in rows]
    minimal_ratings = [m for _, m, _, _ in rows]
    full_ratings = [f for _, _, f, _ in rows]

    print("\n" + "=" * 55)
    naive = (1 + (prices[prices.index >= __import__("pandas").Timestamp(rows[-1][0])].iloc[20] / prices[prices.index >= __import__("pandas").Timestamp(rows[0][0])].iloc[0]) - 1) - 1
    naive_compound = 1.0
    for r in raws:
        naive_compound *= (1 + r)
    print(f"Naive every-month Buy:   {(naive_compound - 1) * 100:+7.1f}%")

    print(f"Minimal V1 (UW=0):       {compute_total(minimal_ratings, raws, POS) * 100:+7.1f}%")
    print(f"Full V1 (UW=0):          {compute_total(full_ratings, raws, POS) * 100:+7.1f}%")
    print(f"Full V1 SHORT (UW=-0.5): {compute_total(full_ratings, raws, POS_SHORT) * 100:+7.1f}%")

    # Rating distribution comparison
    from collections import Counter
    print("\nRating distribution:")
    print(f"  Minimal: {dict(Counter(minimal_ratings))}")
    print(f"  Full:    {dict(Counter(full_ratings))}")


if __name__ == "__main__":
    main()
