"""Why does the framework give inverted Buy/OW signals on ETH?

Reads the saved analyst reports for ETH weeks where the model called Buy
and the market then dropped >5%, to see what reasoning the LLM produced
on those losing calls.
"""

from __future__ import annotations

import json
from pathlib import Path

# Worst 3 ETH "Buy" weeks from 2023 weekly run:
WORST = [
    ("2023-08-14", "Buy",        -9.47),
    ("2023-04-17", "Buy",        -9.73),
    ("2023-06-12", "Buy",         -0.88),  # mild, included for contrast
]

# Best 3 ETH "Overweight" weeks (where caution was wrong):
INVERTED = [
    ("2023-01-09", "Buy",        +17.34),  # full position correctly here
    ("2023-02-13", "Overweight", +12.25),  # half position missed it
    ("2023-04-10", "Overweight",  +9.48),  # half position missed it
]


def main() -> None:
    base = Path("C:/Users/Pan/.tradingagents/logs/ETH-USD/TradingAgentsStrategy_logs")
    for label, group in [("BUY-CALLS-THAT-LOST", WORST),
                         ("OW-CALLS-THAT-MISSED-RALLIES", INVERTED)]:
        print("=" * 80)
        print(label)
        print("=" * 80)
        for date, rating, ret in group:
            p = base / f"full_states_log_{date}.json"
            if not p.exists():
                print(f"\n--- {date} {rating} → {ret:+.2f}%   (no file)")
                continue
            s = json.loads(p.read_text(encoding="utf-8"))
            print(f"\n--- {date} {rating} → next-5d {ret:+.2f}%")
            report = (s.get("market_report") or "")
            # Get last 1200 chars: the conclusion / signal section is usually at the end.
            # Strip non-ASCII (e.g. ✓ U+2713) so cp950 console doesn't crash.
            ascii_safe = report[-1200:].encode("ascii", "ignore").decode("ascii")
            print(ascii_safe.strip())


if __name__ == "__main__":
    main()
