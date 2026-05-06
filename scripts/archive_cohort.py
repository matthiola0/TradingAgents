"""Archive a (ticker, year) cohort from the memory log so it can be re-run
with a different config and compared.

Removes the entries from the main log and saves them to
~/.tradingagents/baselines/<ticker>_<year>_<label>.json so the next
backtest run won't skip them via the idempotency guard.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

LOG = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"
BASE = Path.home() / ".tradingagents" / "baselines"
SEPARATOR = "\n\n<!-- ENTRY_END -->\n\n"


def main() -> int:
    if len(sys.argv) < 4:
        print("usage: archive_cohort.py TICKER YEAR LABEL")
        print("e.g.   archive_cohort.py BTC-USD 2022 minimal")
        return 2
    ticker, year, label = sys.argv[1], sys.argv[2], sys.argv[3]
    raw = LOG.read_text(encoding="utf-8")
    blocks = raw.split(SEPARATOR)

    archived = []
    kept = []
    tag_re = re.compile(rf"^\[(\d{{4}}-\d{{2}}-\d{{2}}) \| {re.escape(ticker)} \| (\w+) \|")
    for block in blocks:
        s = block.strip()
        if not s:
            kept.append(block)
            continue
        first = s.splitlines()[0].strip()
        m = tag_re.match(first)
        if not m or not m.group(1).startswith(year + "-"):
            kept.append(block)
            continue
        archived.append({
            "date": m.group(1),
            "rating": m.group(2),
            "tag_line": first,
            "block": block,
        })

    if not archived:
        print(f"No {ticker} {year} entries found.")
        return 1

    BASE.mkdir(parents=True, exist_ok=True)
    out_path = BASE / f"{ticker}_{year}_{label}.json"
    out_path.write_text(json.dumps({"ticker": ticker, "year": int(year),
                                     "label": label, "entries": archived},
                                     indent=2), encoding="utf-8")
    LOG.write_text(SEPARATOR.join(kept), encoding="utf-8")
    rating_counts = {}
    for e in archived:
        rating_counts[e["rating"]] = rating_counts.get(e["rating"], 0) + 1
    print(f"Archived {len(archived)} entries to {out_path}")
    print(f"  Ratings: {rating_counts}")
    print("Memory log entries removed; next backtest will re-run them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
