"""Compare ETH-USD 2023 weekly results: pre-prompt-A baseline vs current memory log.

Reads:
  - ~/.tradingagents/baselines/eth_2023_pre_prompt_a.json (the archived
    entries from before the prompt change)
  - ~/.tradingagents/memory/trading_memory.md (entries from the re-run
    with the asset-aware crypto-calibration prompt)

Reports per-week rating diff plus the headline strategy/dumb-50%/de-risk
metrics for both.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import yfinance as yf

POS = {"Buy": 1.0, "Overweight": 0.5, "Hold": 0.0, "Underweight": -0.5, "Sell": -1.0}
HOLDING_DAYS = 5

LOG_PATH = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"
BASELINE_PATH = Path.home() / ".tradingagents" / "baselines" / "eth_2023_pre_prompt_a.json"


def load_current_eth_2023():
    text = LOG_PATH.read_text(encoding="utf-8")
    pattern = re.compile(r"\[(2023-\d{2}-\d{2}) \| ETH-USD \| (\w+) \|")
    return [{"date": d, "rating": r} for d, r in pattern.findall(text)]


def load_baseline_eth_2023():
    if not BASELINE_PATH.exists():
        return []
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return [{"date": e["date"], "rating": e["rating"]} for e in payload["entries"]]


def compute_metrics(entries):
    if not entries:
        return None
    hist = yf.Ticker("ETH-USD").history(start="2022-12-15", end="2024-03-01")
    hist.index = hist.index.tz_localize(None)
    prices = hist["Close"]

    rows = []
    for e in entries:
        entry = pd.Timestamp(e["date"])
        avail = prices[prices.index >= entry]
        if len(avail) < HOLDING_DAYS + 1:
            continue
        raw = (avail.iloc[HOLDING_DAYS] - avail.iloc[0]) / avail.iloc[0]
        pos = POS.get(e["rating"], 0.0)
        rows.append({
            "date": e["date"], "rating": e["rating"],
            "raw": raw, "position": pos, "pnl": raw * pos,
        })
    df = pd.DataFrame(rows)

    naive = (1 + df["raw"]).prod() - 1
    strat = (1 + df["pnl"]).prod() - 1
    dumb = (1 + df["raw"] * 0.5).prod() - 1
    de_risk = df[df["position"] < 1.0]
    if len(de_risk) > 0:
        correct = int((de_risk["raw"] < 0).sum())
        precision = correct / len(de_risk) * 100
    else:
        correct = 0
        precision = float("nan")
    base_rate = (df["raw"] < 0).mean() * 100
    return {
        "n": len(df),
        "naive": naive,
        "strat": strat,
        "dumb": dumb,
        "true_signal": (strat - dumb) * 100,
        "alpha_vs_buy": (strat - naive) * 100,
        "de_risk_n": len(de_risk),
        "de_risk_correct": correct,
        "precision": precision,
        "base_rate": base_rate,
        "lift": precision - base_rate if not pd.isna(precision) else float("nan"),
        "rating_counts": df["rating"].value_counts().to_dict(),
        "buy_mean": df[df["rating"] == "Buy"]["raw"].mean() if (df["rating"] == "Buy").any() else float("nan"),
        "ow_mean": df[df["rating"] == "Overweight"]["raw"].mean() if (df["rating"] == "Overweight").any() else float("nan"),
        "df": df,
    }


def fmt(m):
    if m is None:
        return "(no data)"
    rcs = " / ".join(f"{c}{r[0]}" for r, c in m["rating_counts"].items())
    return (
        f"  N={m['n']}  ratings: {rcs}\n"
        f"  Strategy:    {m['strat']*100:+7.1f}%\n"
        f"  Naive Buy:   {m['naive']*100:+7.1f}%   alpha vs Buy: {m['alpha_vs_buy']:+5.1f}pp\n"
        f"  Dumb 50%:    {m['dumb']*100:+7.1f}%   true signal:  {m['true_signal']:+5.1f}pp\n"
        f"  De-risk:     {m['de_risk_correct']}/{m['de_risk_n']} = {m['precision']:.0f}%  "
        f"base rate {m['base_rate']:.0f}%  lift: {m['lift']:+.0f}pp\n"
        f"  Buy weeks mean +5d ret: {m['buy_mean']*100:+5.2f}%   "
        f"OW weeks mean +5d ret: {m['ow_mean']*100:+5.2f}%"
    )


def main() -> None:
    base = load_baseline_eth_2023()
    curr = load_current_eth_2023()

    print("=" * 78)
    print("ETH-USD 2023 — pre-prompt-A baseline vs post-prompt-A re-run")
    print("=" * 78)

    bm = compute_metrics(base)
    cm = compute_metrics(curr)

    print()
    print("BASELINE (equity-grade prompt):")
    print(fmt(bm))
    print()
    print("POST PROMPT-A (asset-aware crypto calibration):")
    print(fmt(cm))

    if bm and cm and bm["n"] == cm["n"]:
        # Per-week diff
        bd = {e["date"]: e["rating"] for e in base}
        cd = {e["date"]: e["rating"] for e in curr}
        changed = [(d, bd[d], cd[d]) for d in sorted(set(bd) & set(cd)) if bd[d] != cd[d]]
        print()
        print(f"Per-week rating changes ({len(changed)}/{bm['n']}):")
        for d, b, c in changed:
            print(f"  {d}  {b:>10}  ->  {c}")


if __name__ == "__main__":
    main()
