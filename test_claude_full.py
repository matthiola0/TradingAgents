"""End-to-end smoke test: drive a full TradingAgents pipeline with Claude OAuth.

Minimal config — single analyst, zero debate rounds, both think slots on
Haiku — so this finishes in a few minutes and stays well under any
Claude Pro / Max rate limit.

Run from the repo root inside the `tradingagents` conda env:

    conda activate tradingagents
    python test_claude_full.py

Expected:
- A stream of agent messages in the terminal.
- A final 5-tier rating (Buy / Overweight / Hold / Underweight / Sell).
- New files under ~/.tradingagents/logs/NVDA/ and ~/.tradingagents/memory/.

This file is intentionally NOT committed (see .gitignore guidance in the
docs). Delete or .gitignore-add it after you're done verifying.
"""

from __future__ import annotations

from dotenv import load_dotenv

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

load_dotenv()


def main() -> None:
    config = DEFAULT_CONFIG.copy()

    # Provider: Claude via Claude Code OAuth (no API key needed when
    # ~/.claude/.credentials.json exists). To force the API-key path
    # instead, set ANTHROPIC_API_KEY or TRADINGAGENTS_ANTHROPIC_AUTH=api_key.
    config["llm_provider"] = "anthropic"

    # Both slots on Haiku to minimise tokens for this smoke run.
    # Once verified, you can swap deep_think_llm to claude-opus-4-7.
    config["deep_think_llm"] = "claude-haiku-4-5-20251001"
    config["quick_think_llm"] = "claude-haiku-4-5-20251001"

    # Skip the bull/bear and risk-team debates entirely so we exercise the
    # graph topology without burning tokens on multi-round arguments.
    config["max_debate_rounds"] = 0
    config["max_risk_discuss_rounds"] = 0

    # yfinance vendor for everything — no extra API keys required.
    config["data_vendors"] = {
        "core_stock_apis": "yfinance",
        "technical_indicators": "yfinance",
        "fundamental_data": "yfinance",
        "news_data": "yfinance",
    }

    # Only run the Market analyst. Add "social", "news", "fundamentals" once
    # the smoke run passes if you want a richer report.
    ta = TradingAgentsGraph(
        selected_analysts=["market"],
        debug=True,
        config=config,
    )

    _, decision = ta.propagate("NVDA", "2024-05-10")

    print("=" * 60)
    print("DECISION:", decision)


if __name__ == "__main__":
    main()
