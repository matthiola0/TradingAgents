"""Archive existing ETH-USD 2023 memory-log entries so we can re-run with the
new asset-aware crypto-calibration prompt and compare against the baseline.

What it does:
  1. Read ~/.tradingagents/memory/trading_memory.md
  2. Extract every ETH-USD 2023 entry (date, rating, full block) into
     ~/.tradingagents/baselines/eth_2023_pre_prompt_a.json
  3. Rewrite trading_memory.md with those entries removed
  4. Print a summary

After running this, ``run_backtest.py`` will see the 2023 ETH dates as
missing and re-propagate them through the new prompt. The companion
``compare_eth_prompts.py`` script can then diff the two rating sequences.

Run once before the prompt-A re-run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

LOG_PATH = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"
BASELINE_DIR = Path.home() / ".tradingagents" / "baselines"
BASELINE_PATH = BASELINE_DIR / "eth_2023_pre_prompt_a.json"

SEPARATOR = "\n\n<!-- ENTRY_END -->\n\n"
TARGET_TICKER = "ETH-USD"
TARGET_YEAR_PREFIX = "2023-"


def main() -> None:
    if not LOG_PATH.exists():
        print(f"No memory log at {LOG_PATH}")
        return

    raw = LOG_PATH.read_text(encoding="utf-8")
    blocks = raw.split(SEPARATOR)

    archived: list[dict] = []
    kept_blocks: list[str] = []

    tag_re = re.compile(r"^\[(\d{4}-\d{2}-\d{2}) \| ([A-Z0-9.\-]+) \| (\w+) \|")

    for block in blocks:
        stripped = block.strip()
        if not stripped:
            kept_blocks.append(block)
            continue
        first_line = stripped.splitlines()[0].strip()
        m = tag_re.match(first_line)
        if not m:
            kept_blocks.append(block)
            continue
        date, ticker, rating = m.group(1), m.group(2), m.group(3)
        if ticker == TARGET_TICKER and date.startswith(TARGET_YEAR_PREFIX):
            archived.append({
                "date": date,
                "ticker": ticker,
                "rating": rating,
                "tag_line": first_line,
                "block": block,
            })
        else:
            kept_blocks.append(block)

    if not archived:
        print(f"No {TARGET_TICKER} {TARGET_YEAR_PREFIX[:-1]} entries found in {LOG_PATH}")
        return

    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps({"ticker": TARGET_TICKER, "year": 2023, "entries": archived}, indent=2),
        encoding="utf-8",
    )

    new_text = SEPARATOR.join(kept_blocks)
    LOG_PATH.write_text(new_text, encoding="utf-8")

    print(f"Archived {len(archived)} entries to: {BASELINE_PATH}")
    print(f"Removed those entries from: {LOG_PATH}")
    print()
    rating_counts: dict[str, int] = {}
    for e in archived:
        rating_counts[e["rating"]] = rating_counts.get(e["rating"], 0) + 1
    print("Baseline rating distribution:")
    for r, c in sorted(rating_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {r:<12} {c}")
    print()
    print("Next: re-run with the new prompt:")
    print("  python scripts/run_backtest.py --ticker ETH-USD --start 2023-01-01 --end 2023-12-31 --frequency weekly")
    print("Then compare with: python scripts/compare_eth_prompts.py")


if __name__ == "__main__":
    main()
