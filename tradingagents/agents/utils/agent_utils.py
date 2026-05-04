from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Only applied to user-facing agents (analysts, portfolio manager).
    Internal debate agents stay in English for reasoning quality.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def build_instrument_context(ticker: str) -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    return (
        f"The instrument to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`)."
    )


# Crypto pairs settle to USD (or stable coins / BTC / ETH) on yfinance and
# major exchanges. Detecting the suffix is enough to switch the technical-
# indicator calibration; the framework's per-cohort backtest study found
# that the same RSI/MACD thresholds calibrated for equities mistime crypto
# badly (see docs/RESEARCH_2022.md, "ETH inverted-signal root cause").
_CRYPTO_SUFFIXES = ("-USD", "-USDT", "-BTC", "-ETH")


def _is_crypto_ticker(ticker: str) -> bool:
    upper = ticker.upper()
    return any(upper.endswith(suf) for suf in _CRYPTO_SUFFIXES)


def build_technical_calibration_context(ticker: str) -> str:
    """Return asset-class-specific calibration guidance for technical analysts.

    The default RSI 70/30, MACD-crossover-as-trend-reversal heuristics in
    the market analyst prompt assume equity-grade volatility (~30-40%
    annualised). Crypto trades at 60-100% annualised vol, so the same
    indicator setup that wins ~70% of the time on stocks wins ~50% on
    crypto with much wider tails. This helper returns extra text the
    market analyst should respect when the ticker is a crypto pair, and
    an empty string otherwise.
    """
    if not _is_crypto_ticker(ticker):
        return ""
    return (
        " IMPORTANT — crypto-asset calibration: this ticker is a crypto pair. "
        "Crypto realised volatility is roughly 2-3x equity volatility, which "
        "invalidates the default equity-grade thresholds for the indicators "
        "above. Apply the following adjustments before recommending a "
        "directional position:\n"
        "  - RSI thresholds widen to 20 (oversold) and 80 (overbought). "
        "RSI 65-70 is normal mid-trend, not 'approaching overbought'.\n"
        "  - A single MACD crossover or RSI divergence is not enough. "
        "Require confluence of at least 3 independent indicators (e.g. "
        "MACD direction + price vs 50-SMA + Bollinger position) before "
        "issuing a Buy.\n"
        "  - 'Volatility compression' setups produce both directions on "
        "crypto with roughly equal probability. Treat as a coin flip, not "
        "a directional bias.\n"
        "  - When in doubt, prefer Hold over Overweight. Reserve Overweight "
        "for setups with active negative-skew warning signs (e.g. failed "
        "breakout, distribution volume), not for ordinary pullbacks within "
        "an uptrend.\n"
        "  - Reserve Buy for setups with at least 3-indicator confluence "
        "and no overbought RSI warning. A 'recovery bounce' off a recent "
        "low without confluence is not a Buy on crypto.\n"
        "These adjustments materially reduce the false-positive rate that "
        "the underlying indicator suite produces on crypto."
    )


def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages


        
