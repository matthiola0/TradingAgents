"""Compare BTC 2024 monthly under minimal vs full TradingAgents config."""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path
import pandas as pd
import yfinance as yf

LOG = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"
MIN_PATH = Path.home() / ".tradingagents" / "baselines" / "BTC-USD_2024_minimal.json"

POS = {"Buy": 1.0, "Overweight": 0.5, "Hold": 0.0,
       "Underweight": 0.0, "Sell": 0.0}
POS_SHORT = {"Buy": 1.0, "Overweight": 0.5, "Hold": 0.0,
             "Underweight": -0.5, "Sell": -1.0}


def fetch_btc_with_retry():
    last_exc = None
    for attempt in range(5):
        try:
            h = yf.Ticker("BTC-USD").history(start="2023-12-15", end="2025-02-15")
            if not h.empty:
                h.index = h.index.tz_localize(None)
                return h["Close"]
        except Exception as e:
            last_exc = e
        time.sleep(2 ** attempt)
    raise RuntimeError(f"yfinance failed: {last_exc}")


def load_full_2024():
    text = LOG.read_text(encoding="utf-8")
    pat = re.compile(r"\[(2024-\d{2}-\d{2}) \| BTC-USD \| (\w+) \|")
    return pat.findall(text)


def main():
    prices = fetch_btc_with_retry()
    minimal = [(e["date"], e["rating"]) for e in json.loads(MIN_PATH.read_text(encoding="utf-8"))["entries"]]
    full = load_full_2024()
    print(f"Minimal: {len(minimal)} entries; Full: {len(full)} entries")

    rows = []
    for (d, mr), (_, fr) in zip(minimal, full):
        ts = pd.Timestamp(d)
        avail = prices[prices.index >= ts]
        if len(avail) < 21:
            continue
        raw = float((avail.iloc[20] - avail.iloc[0]) / avail.iloc[0])
        rows.append((d, mr, fr, raw))

    print(f"\n{'date':12} {'minimal':>12} {'full':>15} {'raw_20d':>10}")
    print("-" * 55)
    for d, mr, fr, raw in rows:
        diff = "  *" if mr != fr else ""
        print(f"{d:12} {mr:>12} {fr:>15} {raw*100:>+9.1f}%{diff}")

    def total(ratings, raws, m):
        n = 1.0
        for r, raw in zip(ratings, raws):
            n *= (1 + m.get(r, 0.0) * raw)
        return n - 1

    raws = [r for *_, r in rows]
    minr = [m for _, m, _, _ in rows]
    fullr = [f for _, _, f, _ in rows]

    naive = 1.0
    for r in raws:
        naive *= (1 + r)

    print("\n" + "=" * 55)
    print(f"Naive every-month Buy:        {(naive - 1) * 100:+7.1f}%")
    print(f"Minimal V1 (UW=0):            {total(minr, raws, POS) * 100:+7.1f}%")
    print(f"Full V1 (UW=0):               {total(fullr, raws, POS) * 100:+7.1f}%")
    print(f"Full V1 SHORT (UW=-0.5):      {total(fullr, raws, POS_SHORT) * 100:+7.1f}%")

    print("\nRating distribution:")
    print(f"  Minimal: {dict(Counter(minr))}")
    print(f"  Full:    {dict(Counter(fullr))}")


if __name__ == "__main__":
    main()
