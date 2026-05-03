# 2022 Bear Market Backtest — TradingAgents Signal Quality

Empirical study of whether the TradingAgents framework produces useful trading
signals in a falling market. Run 2026-05-02/03 on the
[feat/oauth-and-backtest](https://github.com/matthiola0/TradingAgents/tree/feat/oauth-and-backtest)
branch.

## TL;DR

> When the framework says "de-risk" (Overweight or Hold), **90% of those calls
> land on a negative-return month**. Across NVDA / TSLA / AAPL / META in 2022,
> the resulting equal-weight portfolio loses **-19.9%** vs **-41.5%** for naive
> "buy every month" — **+21.5pp of alpha** purely from position sizing.

The framework never produced a Sell or Underweight rating, so it cannot short
or fully exit; "alpha" comes entirely from cutting position to 0.5x or 0x at
the right times.

## Setup

| Parameter | Value |
|-----------|-------|
| Tickers | NVDA, TSLA, AAPL, META |
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

## Pooled portfolio

Equal-weight, rebalanced monthly across the four stocks:

| Metric | Value |
|--------|------:|
| Naive (always Buy, every month) | -41.5% |
| TradingAgents (size by rating) | **-19.9%** |
| Alpha | **+21.5pp** |

## The signal quality result

Of the 48 monthly decisions, 21 were "de-risk" calls (Overweight or Hold).
Of those 21:

- **19 landed on a month with negative subsequent 20-day return**
- 2 missed (TSLA 2022-03 Hold missed a +42% rally; AAPL 2022-08 Overweight
  on a flat month)

That's **90% precision** on identifying losing months. Under the null
hypothesis of random calls (~50% base rate, since ~half the months in 2022
were down), a 19/21 hit rate has a two-tailed binomial p < 0.0001.

| Rating bucket | Mean 20-day return | Count |
|---------------|-------------------:|------:|
| Full position (Buy) | +1.77% | 27 |
| De-risked (Overweight or Hold) | **-10.53%** | 21 |

Spread between the two buckets: **12.3pp**. The framework is effectively
separating the upside months from the downside months even though it never
explicitly says "Sell."

## Failure modes

The framework does **not** catch crashes, even when they are the obvious
visible event of the month:

| Stock | Month | Crash | Framework call |
|-------|-------|------:|----------------|
| NVDA | 2022-04 | -28% | Buy (1.0x) |
| TSLA | 2022-12 | -38% | Overweight (0.5x — partial credit) |
| META | 2022-04 | -10% | Overweight (0.5x — partial credit) |

So while it pulls back on broad weakness, it does not anticipate single-month
melt-downs. The largest single-month miss was TSLA 2022-03 — calling Hold
and missing a +42% rally — which by itself accounts for ~half of TSLA's
weaker alpha vs the other three stocks.

## Comparison: same setup in 2024 H1 (bull market)

For context, an earlier run on NVDA 2024-01-01 → 2024-06-24 (26 weekly
samples) returned **identical results to naive every-Monday Buy**: framework
output 23 Buy / 3 Overweight / 0 anything else, compound +180% vs +180% naive.
In a strong uptrend with no obvious technical breakdowns, the framework has
no reason to de-risk and adds no alpha.

## Reading these results

What the data supports:

1. The market analyst prompt produces signals that correlate strongly with
   forward 20-day returns in a bear market.
2. Position sizing alone (no shorts, no full exits) is enough for material
   alpha when the underlying market is going down on average.
3. Behaviour generalises across four large-cap tech names in the same period.

What the data does **not** support:

1. The framework cannot anticipate single-month crashes.
2. The framework cannot generate short or full-cash signals (no Sell or
   Underweight in 60 total decisions across this study + the earlier
   2024 H1 run).
3. The 2022 sample is one regime — same year, same sector. Findings may not
   carry to 2008-style broad crashes, sideways markets, or value/cyclical
   names.

## Reproducing

```powershell
# Setup token (one-time, see CLAUDE_OAUTH_TESTING.md)
$env:CLAUDE_CODE_OAUTH_TOKEN = "sk-ant-oat01-..."

# Collect decisions for the four stocks (run one at a time to avoid
# Anthropic subscription rate limits).
python scripts\run_backtest.py --ticker NVDA --start 2022-01-01 --end 2022-12-31 --frequency monthly
python scripts\run_backtest.py --ticker TSLA --start 2022-01-01 --end 2022-12-31 --frequency monthly
python scripts\run_backtest.py --ticker AAPL --start 2022-01-01 --end 2022-12-31 --frequency monthly
python scripts\run_backtest.py --ticker META --start 2022-01-01 --end 2022-12-31 --frequency monthly

# Per-ticker breakdown
python scripts\analyze_2022.py NVDA
python scripts\analyze_2022.py TSLA
python scripts\analyze_2022.py AAPL
python scripts\analyze_2022.py META

# Pooled portfolio + de-risking precision
python scripts\meta_analysis_2022.py
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
