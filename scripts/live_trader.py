"""Live trading runner for BTC + SOL on Binance using framework signals.

Reads the latest two ratings per ticker from memory log, computes target
positions via Strategy V1 (confluence + stop loss + brake), and submits
real orders to Binance Spot.

DEFAULT MODE IS DRY RUN. Set --live to enable real orders.

Usage:
    # Generate signals first (separate cron job)
    python scripts/run_backtest.py --ticker BTC-USD --start <today> --end <today> --frequency monthly
    python scripts/run_backtest.py --ticker SOL-USD --start <today> --end <today> --frequency monthly

    # Then run trader (dry run)
    python scripts/live_trader.py

    # Live (after paper validation)
    python scripts/live_trader.py --live

Requires:
    pip install python-binance
    BINANCE_API_KEY, BINANCE_API_SECRET in env (trade-only scope, no withdraw)

Risk caps (safety):
- Min order USD 10 (Binance LOT_SIZE filter)
- Max single order = 50% of portfolio (sanity)
- Stop-limit placed automatically after entry on V1 stop loss line (-15%)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ============================================================================
# CONFIG
# ============================================================================

UNIVERSE = [
    # (signal_ticker, binance_symbol, weight)
    ("BTC-USD", "BTCUSDT", 0.60),
    ("SOL-USD", "SOLUSDT", 0.40),
]
PORTFOLIO_FLOOR_USD = 10  # min trade size on Binance
MAX_SINGLE_ORDER_FRAC = 0.50  # never trade > 50% of portfolio in one go
STATE_PATH = Path.home() / ".tradingagents" / "live_state.json"
LOG = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"

# Strategy V1
V1_STOP = -0.15
V1_BRAKE = -0.25

logger = logging.getLogger("live_trader")


# ============================================================================
# STATE & SIGNALS
# ============================================================================

def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"positions": {}, "peak": {}, "brake_until": {},
            "rating_history": {}, "last_run": None}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def load_recent_ratings(ticker: str, n: int = 2) -> list[tuple[str, str]]:
    """Last n (date, rating) pairs for ticker, latest last."""
    if not LOG.exists():
        return []
    text = LOG.read_text(encoding="utf-8")
    pattern = re.compile(rf"\[(\d{{4}}-\d{{2}}-\d{{2}}) \| {re.escape(ticker)} \| (\w+) \|")
    return pattern.findall(text)[-n:]


def v1_target(history: list[str]) -> tuple[float, str]:
    if not history:
        return 0.0, "no signal"
    latest = history[-1]
    prior = history[-2] if len(history) >= 2 else None
    if latest == "Buy" and prior == "Buy":
        return 1.0, "2-month Buy confluence"
    if latest == "Buy":
        return 0.5, "single-month Buy"
    if latest == "Overweight":
        return 0.5, "Overweight"
    return 0.0, f"flat ({latest})"


# ============================================================================
# BROKER ADAPTER
# ============================================================================

class BinanceBroker:
    """Thin wrapper around python-binance Spot client."""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        if dry_run:
            self.client = None
            return
        from binance.client import Client
        api_key = os.environ.get("BINANCE_API_KEY")
        api_secret = os.environ.get("BINANCE_API_SECRET")
        if not (api_key and api_secret):
            raise RuntimeError("BINANCE_API_KEY/BINANCE_API_SECRET env vars required for live mode.")
        self.client = Client(api_key, api_secret)

    def get_price(self, symbol: str) -> float:
        if self.dry_run:
            import yfinance as yf
            yfsym = symbol.replace("USDT", "-USD")
            try:
                return float(yf.Ticker(yfsym).history(period="2d")["Close"].iloc[-1])
            except Exception:
                return 0.0
        ticker = self.client.get_symbol_ticker(symbol=symbol)
        return float(ticker["price"])

    def get_balance_usd(self) -> float:
        """Return USDT balance + value of held base assets in USDT."""
        if self.dry_run:
            return 0.0  # dry run uses state file, not exchange balance
        account = self.client.get_account()
        usdt = 0.0
        positions = 0.0
        for b in account["balances"]:
            free = float(b["free"]) + float(b["locked"])
            if b["asset"] == "USDT":
                usdt += free
            else:
                # Skip if zero
                if free == 0:
                    continue
                # Try price USDT pair
                try:
                    px = self.get_price(f"{b['asset']}USDT")
                    positions += free * px
                except Exception:
                    pass
        return usdt + positions

    def get_position_qty(self, symbol: str) -> float:
        """Get free base asset quantity for symbol (e.g. BTC for BTCUSDT)."""
        if self.dry_run:
            return 0.0
        base = symbol.replace("USDT", "")
        for b in self.client.get_account()["balances"]:
            if b["asset"] == base:
                return float(b["free"])
        return 0.0

    def place_market(self, symbol: str, qty: float, side: str) -> dict:
        """Place market order. side = 'BUY' or 'SELL'. qty in base asset units."""
        if self.dry_run:
            return {"status": "DRY_RUN", "symbol": symbol, "side": side, "qty": qty}
        # Round qty to symbol's stepSize
        info = self.client.get_symbol_info(symbol)
        step_size = float(next(f["stepSize"] for f in info["filters"] if f["filterType"] == "LOT_SIZE"))
        qty = round(qty / step_size) * step_size
        precision = max(0, len(str(step_size).split(".")[-1].rstrip("0")))
        qty = round(qty, precision)
        return self.client.order_market(symbol=symbol, side=side, quantity=qty)

    def place_stop_limit(self, symbol: str, qty: float, stop_price: float, limit_price: float) -> dict:
        """Place stop-limit sell order at -15% from entry (V1 stop loss)."""
        if self.dry_run:
            return {"status": "DRY_RUN_STOP", "symbol": symbol, "qty": qty,
                    "stop": stop_price, "limit": limit_price}
        info = self.client.get_symbol_info(symbol)
        step_size = float(next(f["stepSize"] for f in info["filters"] if f["filterType"] == "LOT_SIZE"))
        tick_size = float(next(f["tickSize"] for f in info["filters"] if f["filterType"] == "PRICE_FILTER"))
        qty = round(qty / step_size) * step_size
        stop_price = round(stop_price / tick_size) * tick_size
        limit_price = round(limit_price / tick_size) * tick_size
        return self.client.create_order(
            symbol=symbol, side="SELL", type="STOP_LOSS_LIMIT",
            timeInForce="GTC", quantity=qty,
            stopPrice=stop_price, price=limit_price,
        )


# ============================================================================
# ORCHESTRATOR
# ============================================================================

@dataclass
class OrderPlan:
    signal_ticker: str
    binance_symbol: str
    side: str
    delta_qty: float
    delta_usd: float
    target_pct: float
    actual_pct: float
    rating: str
    notes: str
    entry_price: float
    stop_price: float


def plan_orders(state: dict, broker: BinanceBroker, portfolio_usd: float) -> list[OrderPlan]:
    today = datetime.now(timezone.utc).date().isoformat()
    plans: list[OrderPlan] = []

    for sig_ticker, bin_symbol, weight in UNIVERSE:
        ratings = load_recent_ratings(sig_ticker, n=2)
        if not ratings:
            logger.warning(f"No signals for {sig_ticker}; skipping")
            continue

        target_frac, reason = v1_target([r for _, r in ratings])

        # Drawdown brake
        leg_value = state.get("positions", {}).get(bin_symbol, 0.0)
        leg_peak = state.get("peak", {}).get(bin_symbol, 0.0)
        on_brake = today < state.get("brake_until", {}).get(bin_symbol, "1900-01-01")
        if leg_peak > 0:
            leg_dd = leg_value / leg_peak - 1
            if leg_dd <= V1_BRAKE and not on_brake:
                on_brake = True
                # Brake until end of next month
                next_month_iso = (datetime.now(timezone.utc).replace(day=28).isoformat()[:10])
                state.setdefault("brake_until", {})[bin_symbol] = next_month_iso
                state["peak"][bin_symbol] = leg_value
                reason += f" + BRAKE FIRED (leg dd {leg_dd*100:+.1f}%)"

        actual_frac = 0.0 if on_brake else target_frac

        # Translate to USD
        target_usd = actual_frac * weight * portfolio_usd
        current_usd = state.get("positions", {}).get(bin_symbol, 0.0)
        delta_usd = target_usd - current_usd

        # Skip dust
        if abs(delta_usd) < PORTFOLIO_FLOOR_USD:
            continue

        # Cap single-order size
        max_order = MAX_SINGLE_ORDER_FRAC * portfolio_usd
        if abs(delta_usd) > max_order:
            logger.warning(f"{bin_symbol} delta ${delta_usd:.2f} exceeds cap ${max_order:.2f}; clamping")
            delta_usd = max_order if delta_usd > 0 else -max_order

        price = broker.get_price(bin_symbol)
        if price <= 0:
            logger.error(f"Failed to fetch price for {bin_symbol}")
            continue
        delta_qty = delta_usd / price

        plans.append(OrderPlan(
            signal_ticker=sig_ticker, binance_symbol=bin_symbol,
            side="BUY" if delta_usd > 0 else "SELL",
            delta_qty=abs(delta_qty), delta_usd=delta_usd,
            target_pct=actual_frac * weight, actual_pct=current_usd / max(portfolio_usd, 1),
            rating=ratings[-1][1], notes=reason,
            entry_price=price, stop_price=price * (1 + V1_STOP),
        ))

    return plans


def execute_plans(plans: list[OrderPlan], broker: BinanceBroker, state: dict) -> None:
    for p in plans:
        logger.info(f"  {p.side} {p.binance_symbol}  qty {p.delta_qty:.6f}  "
                    f"${p.delta_usd:+.2f}  ({p.notes})")
        try:
            order = broker.place_market(p.binance_symbol, p.delta_qty, p.side)
            logger.info(f"    market order: {order.get('status', 'unknown')}")
        except Exception as e:
            logger.error(f"    FAILED: {e}")
            continue

        # Place stop-limit only on BUY (reduces risk on entered position)
        if p.side == "BUY":
            try:
                stop_order = broker.place_stop_limit(
                    p.binance_symbol, p.delta_qty,
                    stop_price=p.stop_price,
                    limit_price=p.stop_price * 0.99,  # 1% buffer
                )
                logger.info(f"    stop-limit @ ${p.stop_price:.2f}: {stop_order.get('status', 'unknown')}")
            except Exception as e:
                logger.warning(f"    stop-limit failed: {e}")

        # Update state
        positions = state.setdefault("positions", {})
        positions[p.binance_symbol] = positions.get(p.binance_symbol, 0.0) + p.delta_usd
        peak = state.setdefault("peak", {})
        peak[p.binance_symbol] = max(peak.get(p.binance_symbol, 0), positions[p.binance_symbol])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="Place real orders. Default is dry run.")
    parser.add_argument("--portfolio-usd", type=float, default=1000.0,
                        help="Total portfolio NAV in USD (used in dry run; live mode reads from Binance).")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    broker = BinanceBroker(dry_run=not args.live)
    state = load_state()

    if args.live:
        nav = broker.get_balance_usd()
        logger.info(f"LIVE mode  Binance NAV ${nav:.2f}")
    else:
        nav = args.portfolio_usd
        logger.info(f"DRY RUN  paper NAV ${nav:.2f}")

    plans = plan_orders(state, broker, nav)
    if not plans:
        logger.info("No rebalancing needed")
        return 0

    logger.info(f"Planned {len(plans)} order(s):")
    execute_plans(plans, broker, state)

    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    logger.info(f"State saved to {STATE_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
