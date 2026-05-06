"""Generate the dashboard data files from the memory log.

Outputs:
  web/data.json          — main: all tickers, all cadences, per-trade metrics
                            including strategy NAV, naive NAV, position, P&L,
                            stop / brake flags, summary text
  web/reports/<T>.json   — per-ticker: full LLM reports keyed by date
                            (loaded on demand when user clicks a point)

Re-run any time the memory log gets new entries.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

LOG = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"
LOGS_DIR = Path.home() / ".tradingagents" / "logs"
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
REPORTS_DIR = WEB_DIR / "reports"

FEE = 0.001
V1_STOP = -0.15
V1_BRAKE = -0.25
V2_BRAKE = -0.30
V2_POS = {"Buy": 1.0, "Overweight": 0.7, "Hold": 0.0,
          "Underweight": 0.0, "Sell": 0.0}

CRYPTO_SUFFIXES = ("-USD", "-USDT", "-BTC", "-ETH")


def is_crypto(ticker: str) -> bool:
    return any(ticker.upper().endswith(s) for s in CRYPTO_SUFFIXES)


def load_all_entries() -> dict[str, list[tuple[str, str]]]:
    """Return ticker -> sorted [(date, rating)]."""
    text = LOG.read_text(encoding="utf-8")
    pattern = re.compile(r"\[(\d{4}-\d{2}-\d{2}) \| ([A-Za-z0-9.\-]+) \| (\w+) \|")
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for date, ticker, rating in pattern.findall(text):
        out[ticker].append((date, rating))
    for ticker in out:
        out[ticker].sort()
    return dict(out)


def split_by_cadence(entries: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """Bucket entries by 'monthly' (one per year-month) and 'weekly' (the rest).

    Strategy: take all unique year-months — those are 'monthly' (one entry per
    month). If a year-month has multiple entries, they are 'weekly' samples
    within that month. We classify the FULL ticker as monthly-or-weekly based
    on median date gap.
    """
    if len(entries) < 2:
        return {"monthly": entries[:]} if entries else {}
    dates = [pd.Timestamp(d) for d, _ in entries]
    gaps = sorted((dates[i + 1] - dates[i]).days for i in range(len(dates) - 1))
    median_gap = gaps[len(gaps) // 2]
    cadence = "weekly" if median_gap < 14 else "monthly"

    if cadence == "monthly":
        return {"monthly": entries}

    # Weekly cohort: separate the monthly (first-week) entries from the
    # within-month weekly entries by looking at year-month uniqueness.
    by_ym: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for date, rating in entries:
        by_ym[date[:7]].append((date, rating))

    monthly: list[tuple[str, str]] = []
    weekly: list[tuple[str, str]] = []
    for ym in sorted(by_ym):
        items = by_ym[ym]
        # First entry of each month → monthly; rest → weekly
        monthly.append(items[0])
        weekly.extend(items)  # weekly contains everything for that ticker
    out = {}
    if len(monthly) >= 2:
        out["monthly"] = monthly
    if len(weekly) > len(monthly):
        out["weekly"] = weekly
    return out


def fetch_prices(ticker: str, start_year: int) -> Optional[pd.Series]:
    try:
        h = yf.Ticker(ticker).history(start=f"{start_year - 1}-12-15", end="2026-03-01")
        if h.empty:
            return None
        h.index = h.index.tz_localize(None)
        return h["Close"]
    except Exception as exc:
        print(f"  yfinance fetch failed for {ticker}: {exc}")
        return None


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


def get_holding_return(prices: pd.Series, entry_date: str, days: int) -> Optional[float]:
    entry = pd.Timestamp(entry_date)
    avail = prices[prices.index >= entry]
    if len(avail) < days + 1:
        return None
    return float((avail.iloc[days] - avail.iloc[0]) / avail.iloc[0])


def v1_target(history: list[str]) -> tuple[float, str]:
    if not history:
        return 0.0, "no signal"
    latest = history[-1]
    prior = history[-2] if len(history) >= 2 else None
    if latest == "Buy" and prior == "Buy":
        return 1.0, "Buy×2 confluence"
    if latest == "Buy":
        return 0.5, "Buy (single)"
    if latest == "Overweight":
        return 0.5, "Overweight"
    return 0.0, latest


def v2_target(rating: str) -> tuple[float, str]:
    pos = V2_POS.get(rating, 0.0)
    return pos, f"V2 {rating}"


def run_strategy_for_cadence(ticker: str, entries: list[tuple[str, str]],
                              cadence: str, prices: pd.Series) -> Optional[dict]:
    """Run V1 (crypto) or V2 (equity) and produce the dashboard data trace."""
    if not entries:
        return None
    asset_class = "crypto" if is_crypto(ticker) else "equity"
    holding_days = 5 if cadence == "weekly" else 20
    brake_threshold = V1_BRAKE if asset_class == "crypto" else V2_BRAKE

    history: list[str] = []
    leg_value = 1.0
    leg_peak = 1.0
    brake_until_idx = -1
    naive_nav = 1.0
    v1_nav = 1.0
    v1_peak = 1.0

    rows = []
    for i, (date, rating) in enumerate(entries):
        history.append(rating)
        if asset_class == "crypto":
            target, target_reason = v1_target(history)
        else:
            target, target_reason = v2_target(rating)

        on_brake = i < brake_until_idx
        actual = 0.0 if on_brake else target

        raw = get_holding_return(prices, date, holding_days)
        if raw is None:
            continue

        # Stop loss only for crypto V1
        stop_hit = False
        realized = raw * actual
        if asset_class == "crypto" and actual > 0:
            min_ret = get_intraperiod_min(prices, date, holding_days)
            if min_ret is not None and min_ret <= V1_STOP:
                realized = V1_STOP * actual
                stop_hit = True
        if actual > 0:
            realized -= 2 * FEE * actual

        # NAVs
        v1_nav *= (1 + realized)
        naive_nav *= (1 + raw)

        # Per-leg drawdown brake
        leg_value *= (1 + realized)
        leg_peak = max(leg_peak, leg_value)
        leg_dd = leg_value / leg_peak - 1
        if leg_dd <= brake_threshold and not on_brake:
            brake_until_idx = i + 2
            leg_peak = leg_value
            target_reason += " · BRAKE FIRED"

        # Get price at entry date
        entry_ts = pd.Timestamp(date)
        avail = prices[prices.index >= entry_ts]
        price = float(avail.iloc[0]) if len(avail) > 0 else None

        # Compose summary
        summary_parts = [target_reason]
        if stop_hit:
            summary_parts.append("STOP LOSS HIT (-15%)")
        if on_brake:
            summary_parts.append("on brake (period skipped)")

        rows.append({
            "date": date,
            "price": price,
            "rating": rating,
            "target_pos": round(target, 3),
            "actual_pos": round(actual, 3),
            "raw_return": round(raw, 4),
            "realized_pnl": round(realized, 4),
            "stop_hit": stop_hit,
            "brake_active": on_brake,
            "v1_equity": round(v1_nav, 4),
            "naive_equity": round(naive_nav, 4),
            "summary": " · ".join(summary_parts),
        })

    if not rows:
        return None

    # Compute metadata
    final_strat = rows[-1]["v1_equity"]
    final_naive = rows[-1]["naive_equity"]
    n_years = (pd.Timestamp(rows[-1]["date"]) - pd.Timestamp(rows[0]["date"])).days / 365.25
    cagr = (final_strat ** (1 / n_years) - 1) if n_years > 0 else 0
    naive_cagr = (final_naive ** (1 / n_years) - 1) if n_years > 0 else 0

    # Max DD
    eq = pd.Series([1.0] + [r["v1_equity"] for r in rows])
    naive_eq = pd.Series([1.0] + [r["naive_equity"] for r in rows])
    max_dd = float((eq / eq.cummax() - 1).min())
    naive_dd = float((naive_eq / naive_eq.cummax() - 1).min())

    n = len(rows)
    n_buy = sum(1 for r in rows if r["rating"] == "Buy")
    n_ow = sum(1 for r in rows if r["rating"] == "Overweight")
    n_hold = sum(1 for r in rows if r["rating"] == "Hold")
    stops = sum(1 for r in rows if r["stop_hit"])
    brakes = sum(1 for r in rows if r["brake_active"])

    metadata = {
        "asset_class": asset_class,
        "cadence": cadence,
        "strategy_label": "V1 (crypto)" if asset_class == "crypto" else "V2 (equity)",
        "n_trades": n,
        "period": f"{rows[0]['date']} to {rows[-1]['date']}",
        "n_years": round(n_years, 2),
        "naive_total_ret_pct": round((final_naive - 1) * 100, 1),
        "naive_cagr_pct": round(naive_cagr * 100, 1),
        "naive_max_dd_pct": round(naive_dd * 100, 1),
        "v1_total_ret_pct": round((final_strat - 1) * 100, 1),
        "v1_cagr_pct": round(cagr * 100, 1),
        "v1_max_dd_pct": round(max_dd * 100, 1),
        "rating_counts": {"Buy": n_buy, "Overweight": n_ow, "Hold": n_hold},
        "stops": stops,
        "brakes": brakes,
    }
    return {"metadata": metadata, "data": rows}


def collect_per_ticker_reports(ticker: str) -> dict:
    """Read the saved per-run JSON state files and pack into one dict keyed by date."""
    ticker_dir = LOGS_DIR / ticker / "TradingAgentsStrategy_logs"
    if not ticker_dir.exists():
        return {}
    out = {}
    for f in sorted(ticker_dir.glob("full_states_log_*.json")):
        date = f.stem.replace("full_states_log_", "")
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        # Only keep the prose / decision fields — debate histories are huge
        out[date] = {
            "market_report": payload.get("market_report", "") or "",
            "sentiment_report": payload.get("sentiment_report", "") or "",
            "news_report": payload.get("news_report", "") or "",
            "fundamentals_report": payload.get("fundamentals_report", "") or "",
            "investment_plan": payload.get("investment_plan", "") or "",
            "trader_investment_plan": payload.get("trader_investment_plan", "") or "",
            "final_trade_decision": payload.get("final_trade_decision", "") or "",
        }
    return out


def main() -> None:
    print("Building dashboard data...")
    WEB_DIR.mkdir(exist_ok=True)
    REPORTS_DIR.mkdir(exist_ok=True)

    all_entries = load_all_entries()
    print(f"Found {len(all_entries)} tickers in memory log")

    out = {"tickers": {}}

    for ticker in sorted(all_entries):
        entries = all_entries[ticker]
        print(f"\n{ticker}  ({len(entries)} entries)")
        cadence_buckets = split_by_cadence(entries)
        if not cadence_buckets:
            print("  no cadence detected, skipping")
            continue

        start_year = int(entries[0][0][:4])
        prices = fetch_prices(ticker, start_year)
        if prices is None:
            print("  no price data, skipping")
            continue

        ticker_data = {
            "asset_class": "crypto" if is_crypto(ticker) else "equity",
            "frequencies": [],
        }
        for cadence, bucket in cadence_buckets.items():
            print(f"  {cadence}: {len(bucket)} entries")
            result = run_strategy_for_cadence(ticker, bucket, cadence, prices)
            if result is None:
                continue
            ticker_data["frequencies"].append(cadence)
            ticker_data[cadence] = result

        if not ticker_data["frequencies"]:
            continue

        out["tickers"][ticker] = ticker_data

        # Build the per-ticker reports file (loaded on demand)
        reports = collect_per_ticker_reports(ticker)
        report_path = REPORTS_DIR / f"{ticker.replace('/', '_')}.json"
        report_path.write_text(json.dumps(reports), encoding="utf-8")
        print(f"  reports: {len(reports)} entries -> {report_path.name}")

    main_path = WEB_DIR / "data.json"
    main_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    main_size_kb = main_path.stat().st_size / 1024
    print(f"\nWrote {main_path}  ({main_size_kb:.1f} KB)")
    print(f"Wrote {len(out['tickers'])} ticker reports to {REPORTS_DIR}")


if __name__ == "__main__":
    main()
