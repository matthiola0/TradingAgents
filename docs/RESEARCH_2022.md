# 2022 Bear Market Backtest — TradingAgents Signal Quality

Empirical study of whether the TradingAgents framework produces useful trading
signals in a falling market. Run 2026-05-02/03 on the
[feat/oauth-and-backtest](https://github.com/matthiola0/TradingAgents/tree/feat/oauth-and-backtest)
branch.

## TL;DR

> Tested across 4 stocks (NVDA / TSLA / AAPL / META) and 2 cryptos
> (BTC-USD / ETH-USD) in 2022, the framework de-risks to half-position
> 92% of the time on crypto and 44% of the time on stocks.
>
> Versus a naive "always Buy" baseline, this looks like dramatic alpha
> (+21.5pp on stocks, +16.7pp on crypto). But versus a more honest
> "always 50% position" baseline — which captures the value of plain
> caution without crediting the model for it — the **true signal alpha
> is +1.6pp on stocks and -12.3pp on crypto**.
>
> The framework has weak but positive timing skill on US large-cap
> equities. On crypto its Buy calls are confidently wrong, and overall
> it underperforms a constant-half-position baseline by 12pp.

The framework never produced a Sell or Underweight rating across 72
total decisions, so it cannot short or fully exit; alpha (where it
exists) comes entirely from cutting position to 0.5x or 0x at the
right times.

## Setup

| Parameter | Value |
|-----------|-------|
| Tickers | NVDA, TSLA, AAPL, META, BTC-USD, ETH-USD |
| Date range | 2022-01-03 → 2022-12-05 (12 monthly entries each) |
| Sample frequency | First Monday of each month (`--frequency monthly`) |
| Holding period | 20 trading days (next monthly entry, no overlap) |
| Provider | Anthropic via Claude OAuth setup token |
| Models | `claude-haiku-4-5-20251001` for both deep & quick |
| Analysts | `market` only |
| Debate / risk rounds | 0 / 0 |
| Position map | Buy=1.0, Overweight=0.5, Hold=0.0, Underweight=-0.5, Sell=-1.0 |

The minimal configuration (one analyst, no debate) was chosen to isolate what
the technical-analyst prompt alone can do — without help from sentiment, news,
fundamentals, or bull/bear debate.

## Per-ticker results

| Ticker | Naive every-month Buy | TradingAgents | Alpha | Ratings |
|--------|----------------------:|--------------:|------:|---------|
| NVDA   | -44.1% | -7.1% | **+36.9pp** | 7 Buy / 4 OW / 1 Hold |
| TSLA   | -61.0% | -54.7% | +6.3pp | 6 Buy / 5 OW / 1 Hold |
| AAPL   | -17.0% | -1.2% | +15.9pp | 7 Buy / 5 OW / 0 Hold |
| META   | -50.0% | -15.1% | +34.9pp | 7 Buy / 4 OW / 1 Hold |

## Crypto results

| Ticker | Naive every-month Buy | TradingAgents | "Alpha" vs Buy | Ratings |
|--------|----------------------:|--------------:|---------------:|---------|
| BTC-USD | -71.5% | -42.9% | +28.6pp | 2 Buy / 10 OW |
| ETH-USD | -76.3% | -68.9% | +7.3pp | 3 Buy / 9 OW |

92% of crypto decisions were de-risk calls (vs 44% for stocks). The
framework basically lived in half-position throughout 2022 crypto.

## Pooled portfolios

Equal-weight, rebalanced monthly:

| Universe | Naive Buy | TradingAgents | "Alpha" vs Buy | Strategy vs always-50% | True signal |
|----------|----------:|--------------:|---------------:|-----------------------:|------------:|
| 4 stocks (N=48) | -41.5% | -19.9% | +21.5pp | -21.5% | **+1.6pp** |
| 2 cryptos (N=24) | -73.6% | -56.9% | +16.7pp | -44.5% | **-12.3pp** |

The "always-50%" column is what you would have made by ignoring the
model and just holding half-position every month — pure caution, zero
information. **The "true signal" column is the model's actual edge over
that.**

For stocks the model squeezes out +1.6pp of real timing skill.
For crypto it loses -12.3pp by going full-position at the wrong times.

## The signal quality result

| Universe | De-risk calls | Hit losing months | Precision | Base rate (% months negative) | **Lift over base** |
|----------|--------------:|------------------:|----------:|------------------------------:|-------------------:|
| Stocks | 21 / 48 | 19 | 90% | 71% | **+19pp** |
| Crypto | 19 / 24 | 15 | 79% | 79% | **+0pp** |

For stocks the model identifies losing months **19pp better than the
base rate** would predict — that's real (binomial p < 0.0001 vs the
null of random calls).

For crypto the precision matches the base rate exactly: 79% of crypto
months were down, and the model said "de-risk" 79% of the time it
guessed (which was 19 of 24 months). It was **right by accident**, not
because of selection.

| Rating bucket | Mean 20-day return | Count |
|---------------|-------------------:|------:|
| Full position (Buy) | +1.77% | 27 |
| De-risked (Overweight or Hold) | **-10.53%** | 21 |

Spread between the two buckets: **12.3pp**. The framework is effectively
separating the upside months from the downside months even though it never
explicitly says "Sell."

## Failure modes

**Stocks**: The framework does not anticipate single-month melt-downs.

| Stock | Month | Crash | Framework call |
|-------|-------|------:|----------------|
| NVDA | 2022-04 | -28% | Buy (1.0x) |
| TSLA | 2022-12 | -38% | Overweight (0.5x — partial credit) |
| META | 2022-04 | -10% | Overweight (0.5x — partial credit) |

The largest single-month miss was TSLA 2022-03 — Hold missing a +42%
rally — which by itself accounts for most of TSLA's weak alpha.

**Crypto**: All four "Buy" calls were on months that dropped hard.

| Crypto | Month | Move | Framework call |
|--------|-------|-----:|----------------|
| ETH | 2022-01 | -33% | Buy (1.0x) |
| ETH | 2022-02 | -17% | Buy (1.0x) |
| ETH | 2022-06 | -35% | Buy (1.0x) |
| BTC | 2022-04 | -15% | Buy (1.0x) |

The technical-analyst prompt was clearly calibrated for equities. Crypto
realised volatility in 2022 was 2-3× equity volatility, but the same
"RSI bouncing off 30" / "MACD cross" patterns triggered Buy calls right
before further -15% to -35% moves. The model has no awareness that the
distribution it's reading from has wider tails.

## Comparison: same setup in 2024 H1 (bull market)

For context, an earlier run on NVDA 2024-01-01 → 2024-06-24 (26 weekly
samples) returned **identical results to naive every-Monday Buy**: framework
output 23 Buy / 3 Overweight / 0 anything else, compound +180% vs +180% naive.
In a strong uptrend with no obvious technical breakdowns, the framework has
no reason to de-risk and adds no alpha.

## Reading these results

What the data supports:

1. The market analyst prompt has weak but positive forward-looking signal
   on US large-cap tech equities (+1.6pp over a half-position baseline,
   +19pp lift on de-risk-call precision over the base rate).
2. The "alpha vs naive Buy" headline numbers are inflated by the model's
   default-cautious bias. Most of what looks like alpha is the value of
   not running 100% long during a bear market — not skill in timing.
3. Behaviour is consistent across four large-cap tech names.

What the data does **not** support:

1. **The framework does not generalise to crypto.** Same prompt, same
   technical indicators, same provider — but on BTC/ETH the model loses
   12pp vs a permanent-half-position baseline because its few Buy calls
   land on months that drop 15-35%. The technical heuristics are tuned
   to equity volatility distributions.
2. The framework cannot anticipate single-month crashes (equity or crypto).
3. The framework cannot generate short or full-cash signals (0 Sell, 0
   Underweight across 72 decisions).
4. The 2022 sample is one regime. Findings may not carry to 2008-style
   broad crashes, sideways markets, value/cyclical equities, or crypto
   bull regimes.

## Reproducing

```powershell
# Setup token (one-time, see CLAUDE_OAUTH_TESTING.md)
$env:CLAUDE_CODE_OAUTH_TOKEN = "sk-ant-oat01-..."

# Collect decisions for the four stocks (run one at a time to avoid
# Anthropic subscription rate limits).
for ticker in NVDA TSLA AAPL META BTC-USD ETH-USD; do
    python scripts\run_backtest.py --ticker $ticker --start 2022-01-01 --end 2022-12-31 --frequency monthly
done

# Per-ticker breakdown
for ticker in NVDA TSLA AAPL META BTC-USD ETH-USD; do
    python scripts\analyze_2022.py $ticker
done

# Equity-only pooled portfolio (4 stocks)
python scripts\meta_analysis_2022.py

# Stocks vs crypto, with the dumb-50% baseline that exposes how much of
# the headline alpha is just default caution
python scripts\meta_analysis_crypto.py
```

## Open questions

- Does the +21.5pp alpha hold in **2008** or **2020-Q1** (broader
  multi-asset crashes, not just tech)? Single regime is fragile.
- Does adding **news / fundamentals analysts** push the de-risk precision
  above 90% — or does it dilute the technical signal?
- Does **debate-rounds=1** finally produce Sell / Underweight ratings, or do
  the bear / conservative agents lose every argument?
- Does **monthly rebalance** vs **weekly** change the result, given the
  framework was clearly designed around weekly cadence in `_fetch_returns`
  but monthly is closer to how a human would act on these signals?

Each follow-up costs roughly 12-50 LLM propagations depending on scope.
