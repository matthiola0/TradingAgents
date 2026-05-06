"""Paper trading runner — connects framework signal to a Binance-style broker.

Reads the latest two ratings per ticker from the memory log (so a propagate
must have run before execution). Computes target position via Strategy V1
for crypto / V2 for equities. Compares to current position and prints the
delta orders that would be placed.

This script is paper / dry-run by design: it never sends real orders. The
order plan is printed; you can wire it to a real broker by replacing the
`place_order` and `get_positions` functions.

Run AFTER signals have been generated:

    # Daily 23:00 UTC: regenerate signals
    python scripts/run_backtest.py --ticker BTC-USD --start <today> --end <today> --frequency monthly

    # Daily 00:01 UTC next day: execute
    python scripts/paper_trader.py
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Configuration
PORTFOLIO_USD = 10_000.0  # paper portfolio NAV
LOG = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"
PAPER_STATE = Path.home() / ".tradingagents" / "paper_state.json"

# Universe with per-asset strategy and target weight in the portfolio
# Weights must sum to <= 1.0
UNIVERSE = [
    # ticker, asset_class, weight
    ("BTC-USD",  "crypto", 0.30),  # 30% to BTC (Strategy V1)
    ("SOL-USD",  "crypto", 0.15),  # 15% to SOL (V1)
    ("AVAX-USD", "crypto", 0.10),  # 10% to AVAX (V1)
    ("NVDA",     "equity", 0.30),  # 30% to NVDA (V2)
    ("CASH",     "cash",   0.15),  # 15% always cash buffer
]

# Strategy V1 (crypto): confluence + stop loss + brake
V1_STOP = -0.15
V1_BRAKE = -0.25
# Strategy V2 (equity): wider brake, no stop, OW=0.7
V2_BRAKE = -0.30
V2_POS_MAP = {"Buy": 1.0, "Overweight": 0.7, "Hold": 0.0,
              "Underweight": 0.0, "Sell": 0.0}


@dataclass
class Order:
    ticker: str
    side: str         # buy / sell / hold
    delta_qty: float  # base-asset units (BTC, NVDA shares)
    delta_usd: float
    target_pct: float
    actual_pct: float
    rating: str
    notes: str


def load_recent_ratings(ticker: str, n: int = 2) -> list[tuple[str, str]]:
    """Return last n (date, rating) pairs for ticker, latest last."""
    if not LOG.exists():
        return []
    text = LOG.read_text(encoding="utf-8")
    pattern = re.compile(rf"\[(\d{{4}}-\d{{2}}-\d{{2}}) \| {re.escape(ticker)} \| (\w+) \|")
    entries = pattern.findall(text)
    return entries[-n:] if entries else []


def load_paper_state() -> dict:
    if PAPER_STATE.exists():
        return json.loads(PAPER_STATE.read_text(encoding="utf-8"))
    return {
        "positions": {},          # ticker -> usd_value
        "peak": {},               # ticker -> peak NAV (for brake)
        "brake_until": {},        # ticker -> ISO date
        "last_run": None,
    }


def save_paper_state(state: dict) -> None:
    PAPER_STATE.parent.mkdir(parents=True, exist_ok=True)
    PAPER_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def crypto_v1_target(ratings: list[tuple[str, str]]) -> tuple[float, str]:
    """Strategy V1 confluence rule. Returns (target_fraction, reason)."""
    if not ratings:
        return 0.0, "no signal"
    latest = ratings[-1][1]
    prior = ratings[-2][1] if len(ratings) >= 2 else None
    if latest == "Buy" and prior == "Buy":
        return 1.0, "2-month Buy confluence"
    if latest == "Buy":
        return 0.5, "single-month Buy"
    if latest == "Overweight":
        return 0.5, "Overweight"
    if latest == "Hold":
        return 0.0, "Hold (cash)"
    return 0.0, f"flat ({latest})"


def equity_v2_target(ratings: list[tuple[str, str]]) -> tuple[float, str]:
    """Strategy V2 mapping for equities."""
    if not ratings:
        return 0.0, "no signal"
    latest = ratings[-1][1]
    pos = V2_POS_MAP.get(latest, 0.0)
    return pos, f"V2 mapping for {latest}"


# ----- Broker adapter (paper) -----

def get_market_price(ticker: str) -> float:
    """Get current market price. Replace with broker API when going live."""
    import yfinance as yf
    if ticker == "CASH":
        return 1.0
    try:
        return float(yf.Ticker(ticker).history(period="2d")["Close"].iloc[-1])
    except Exception:
        return 0.0


def get_positions(state: dict) -> dict[str, float]:
    """Return current USD value of each ticker. Paper version reads state file."""
    return dict(state.get("positions") or {})


def place_order(order: Order, dry_run: bool = True) -> bool:
    """Place a trade. dry_run=True (default) just prints. Replace for live."""
    if dry_run:
        print(f"  [PAPER] {order.side.upper():5} {order.ticker:10} "
              f"qty {order.delta_qty:+10.4f}  ${order.delta_usd:+10.2f}  "
              f"({order.notes})")
        return True
    raise NotImplementedError("Wire up your broker SDK before going live.")


# ----- Main runner -----

def compute_orders(state: dict) -> list[Order]:
    """Plan orders for one rebalance cycle."""
    today = datetime.now(timezone.utc).date().isoformat()
    nav = sum(state.get("positions", {}).values()) or PORTFOLIO_USD
    print(f"Paper run on {today}   NAV ${nav:.2f}\n")

    orders: list[Order] = []
    for ticker, asset_class, weight in UNIVERSE:
        if ticker == "CASH":
            continue

        ratings = load_recent_ratings(ticker, n=2)
        if asset_class == "crypto":
            sub_target, reason = crypto_v1_target(ratings)
            brake_dd = V1_BRAKE
        else:
            sub_target, reason = equity_v2_target(ratings)
            brake_dd = V2_BRAKE

        # Drawdown brake — only check if we have an existing peak (i.e. ever had a position)
        leg_value = state.get("positions", {}).get(ticker, 0.0)
        leg_peak = state.get("peak", {}).get(ticker, 0.0)
        on_brake = today < state.get("brake_until", {}).get(ticker, "1900-01-01")
        leg_dd = ((leg_value / leg_peak) - 1) if leg_peak > 0 else 0.0
        if leg_peak > 0 and leg_dd <= brake_dd and not on_brake:
            on_brake = True
            state.setdefault("brake_until", {})[ticker] = (
                datetime.now(timezone.utc).date().replace(
                    day=min(28, datetime.now(timezone.utc).day)
                ).isoformat()
            )
            reason += f" + brake fired (dd {leg_dd*100:+.1f}%)"
        actual_target = 0.0 if on_brake else sub_target

        # Translate fraction to USD
        target_usd = actual_target * weight * nav
        current_usd = state.get("positions", {}).get(ticker, 0.0)
        delta_usd = target_usd - current_usd

        # Skip dust (< $20)
        if abs(delta_usd) < 20:
            continue

        price = get_market_price(ticker)
        if price <= 0:
            continue
        delta_qty = delta_usd / price

        side = "buy" if delta_usd > 0 else "sell"
        rating = ratings[-1][1] if ratings else "no_signal"
        target_pct = actual_target * weight
        actual_pct = current_usd / nav if nav > 0 else 0
        orders.append(Order(
            ticker=ticker, side=side,
            delta_qty=delta_qty, delta_usd=delta_usd,
            target_pct=target_pct, actual_pct=actual_pct,
            rating=rating, notes=reason,
        ))

    return orders


def main() -> None:
    state = load_paper_state()

    # Initialise positions if first run
    if not state.get("positions"):
        nav = PORTFOLIO_USD
        for ticker, _, weight in UNIVERSE:
            if ticker == "CASH":
                state.setdefault("cash", weight * nav)
            else:
                state.setdefault("positions", {})[ticker] = 0.0
        print(f"First run — initialising paper portfolio at ${nav:.2f}")

    print(f"Universe: {[(t, w) for t, _, w in UNIVERSE]}\n")

    orders = compute_orders(state)
    if not orders:
        print("No rebalancing needed.")
        return

    print(f"Planned orders ({len(orders)}):")
    for order in orders:
        place_order(order, dry_run=True)

    # Update paper state
    for order in orders:
        positions = state.setdefault("positions", {})
        positions[order.ticker] = positions.get(order.ticker, 0.0) + order.delta_usd
        # Track per-leg peak
        peak = state.setdefault("peak", {})
        peak[order.ticker] = max(peak.get(order.ticker, 0), positions[order.ticker])

    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_paper_state(state)
    print(f"\nPaper state saved to {PAPER_STATE}")


if __name__ == "__main__":
    main()
