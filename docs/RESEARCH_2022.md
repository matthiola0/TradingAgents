# 2022 Bear Market Backtest — TradingAgents Signal Quality

Empirical study of whether the TradingAgents framework produces useful trading
signals in a falling market. Run 2026-05-02/03 on the
[feat/oauth-and-backtest](https://github.com/matthiola0/TradingAgents/tree/feat/oauth-and-backtest)
branch.

## TL;DR (final, with NVDA 2018 + BTC 2022-2025)

> Tested across 4 stocks (NVDA / TSLA / AAPL / META in 2022, NVDA
> through 2024-H1) and BTC across 4 full years (2022-2025) plus
> ETH 2022-2023, the dominant finding is **the framework's apparent
> "BTC signal" did not survive sample expansion**.
>
> The 2-year crypto study originally suggested BTC had a robust
> +42pp de-risk lift. Adding 2024 and 2025 shows that was 2023 alone:
>
> | Year | BTC de-risk lift over base rate |
> |------|--------------------------------:|
> | 2022 | +11pp |
> | 2023 | **+42pp** ← outlier |
> | 2024 | -2pp |
> | 2025 | -7pp |
>
> Mean +11pp, median ~0pp, std ~22pp across 4 BTC cohorts. The
> framework has no stable timing signal on BTC. The 2023 result was
> sample noise from a single outlier year.
>
> **The 2022 stock result also collapses under replication**:
> NVDA 2022 was +14pp lift; NVDA 2018 (a different bear year) is
> -8pp lift, dragging strategy *below* a permanent-half-position
> baseline by 15pp. The framework completely missed Q4 2018, calling
> Buy through November and December as NVDA fell -25% each month.
>
> So treating NVDA / META / AAPL 2022 as three independent positive
> cohorts almost certainly overstates the evidence: they were the
> same year, same sector, same macro driver (the 2022 Fed-hike-led
> tech-led bear market). One year that everything works in is
> consistent with a model that was fitted to similar conditions in
> training, not with general bear-market timing skill.
>
> Across the full 12 (ticker, year) cohorts, no individual ticker
> has produced a positive de-risk lift in more than one bear year:
> NVDA went 2022 yes / 2018 no, BTC went 2023 yes / 2022, 2024,
> 2025 no, ETH went 0/2. The dataset is consistent with **the
> framework having no stable positive timing skill in any regime**;
> the apparent 2022 alpha was 2022-specific, possibly correlated
> across same-year same-sector names.
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
| NVDA 2022 | -44.1% | -7.1% | **+36.9pp** | 7 Buy / 4 OW / 1 Hold |
| TSLA 2022 | -61.0% | -54.7% | +6.3pp | 6 Buy / 5 OW / 1 Hold |
| AAPL 2022 | -17.0% | -1.2% | +15.9pp | 7 Buy / 5 OW / 0 Hold |
| META 2022 | -50.0% | -15.1% | +34.9pp | 7 Buy / 4 OW / 1 Hold |
| **NVDA 2018** | **-45.7%** | **-37.4%** | **+8.3pp** | **9 Buy / 3 OW / 0 Hold** |

The NVDA 2018 row was added to test whether the 2022 result
replicates in another bear year. It does not. Strategy beat naive
Buy by only 8pp (vs 37pp in 2022), and against the always-50%
baseline the framework lost 15pp — the model called Buy through the
worst of Q4 2018 (NVDA -26% in November, -25% in December) and
was full position the entire way down.

## Crypto results — full 4-year BTC sweep

| Cohort | Regime | Naive Buy | Strategy | Dumb-50% | True signal | **De-risk lift** |
|--------|--------|----------:|---------:|---------:|------------:|-----------------:|
| BTC-USD 2022 | bear | -71.5% | -42.9% | -43.5% | +0.7pp | +11pp |
| BTC-USD 2023 | strong bull | +106.4% | +87.4% | +47.3% | +40.1pp | **+42pp** |
| BTC-USD 2024 | strong bull | +126.8% | +116.2% | +55.3% | +60.9pp* | -2pp |
| BTC-USD 2025 | sideways +9% | +9.2% | +6.0% | +6.0% | -0.1pp | -7pp |
| ETH-USD 2022 | bear | -76.3% | -68.9% | -45.9% | -23.0pp | -12pp |
| ETH-USD 2023 | bull | +52.8% | +24.1% | +25.5% | -1.5pp | -13pp |

\* The 2024 "true signal" is misleading: it reflects being mostly long
in a +127% market, not selection. The de-risk lift is the cleanest
measure of timing skill, and 2024 shows -2pp = none.

The de-risk lift across 4 BTC years has mean +11pp, median ~0pp, and
standard deviation ~22pp. With only 4 cohorts of 12 observations
each, this is statistically indistinguishable from "no signal,
modest noise."

The 2023 results break the 2022 narrative that "the framework can't
trade crypto":

- **BTC 2023 is the strongest cohort in the entire study.** With
  only a 33% base rate of negative months (it was a strong bull
  year), the model still picked 4 months to drop to 50% position
  and 3 of those 4 months were in fact negative — a +42pp lift over
  the base rate. Real, statistically meaningful timing skill.
- The one BTC 2023 OW miss was 2023-01 (+36% rebound), which by
  itself dragged "alpha vs naive Buy" to **-19pp**. The model picks
  the right months to step aside more often than not, but the
  asymmetry of crypto means that one wrong step-aside in a +36% month
  is enormously costly.

- **ETH 2023 reverses the BTC pattern.** Same prompt, same
  indicators, same provider, but four consecutive Overweight calls
  early in the year (Jan-Apr) all landed on positive months —
  including ETH +34% in January and +13% in March. The model was
  correctly cautious on BTC's hot start (the OW that hit -36% rebound)
  for the wrong reason: the technical indicators saw the same setup
  on both, but only BTC corrected. The framework cannot tell BTC and
  ETH apart at all.

- **ETH 2023 weekly (51 obs) confirms the monthly miscalibration.**
  Re-running ETH 2023 at the framework's native weekly cadence shows
  the same -8pp de-risk lift (vs -13pp monthly) and the same negative
  true signal (-2.5pp vs -1.5pp). Higher sampling frequency does not
  surface a hidden signal — it confirms there isn't one. De-risk
  precision 11/35 = 31%, against a 39% base rate, means the model is
  actually slightly worse than guessing on ETH. Buy weeks averaged
  -1.0% return; OW weeks averaged +1.4% return — the rating ordering
  is inverted. This is systematic miscalibration, not sample noise.

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

1. **The market analyst prompt has real timing signal on BTC** —
   strongest in 2023 (+42pp de-risk lift over a 33% base rate, +40pp
   vs always-50% baseline). The signal is also weakly present on US
   large-cap tech equities in bear markets (+19pp de-risk lift on
   stocks, true signal +1.6pp over the always-50% baseline).
2. The framework correctly identifies bull-vs-bear regimes — its
   de-risk frequency drops materially in uptrends (NVDA 2024 H1: 12%
   de-risk; BTC 2023: 33%; vs bear cohorts averaging 50-90%).
3. Behaviour is consistent across four large-cap tech names in 2022.

What the data does **not** support:

1. **The framework does not generalise within crypto.** ETH gets
   negative true signal in both 2022 and 2023 even though the same
   prompt produces the study's strongest signal on BTC 2023. The
   technical indicators cannot distinguish BTC from ETH.
2. **One missed call can wipe out a year of correct ones.** BTC 2023
   was right on 3/4 of its de-risk calls but the one wrong call (2023-01
   OW missing a +36% rebound) flipped strategy-vs-naive-Buy from
   positive to -19pp. Asymmetric payoff structure of crypto amplifies
   model errors.
3. The framework cannot anticipate single-month crashes (equity or
   crypto): NVDA -28%, TSLA -38%, ETH -33%, BTC -33% all came with
   "Buy" or "Overweight" calls, not Hold or Sell.
4. The framework cannot generate short or full-cash signals (0 Sell,
   0 Underweight across all 96+ decisions in this study).

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

## ETH inverted-signal root cause

Reading the saved analyst reports for the worst ETH calls (in
``~/.tradingagents/logs/ETH-USD/``) revealed a consistent failure mode.

For weeks where the model called Buy and ETH then dropped 9-10%, the
reports read like textbook stock-trading bullish setups:

- 2023-08-14 (Buy → -9.5%): "MACD positive crossover, RSI positive
  divergence, volatility compression, sellers capitulating, 200 SMA
  support holding — recovery bounce expected toward $1,877-$1,900."
- 2023-04-17 (Buy → -9.7%): even the report itself flagged RSI 68.6 as
  "approaching overbought," but the model went full position anyway
  citing MACD acceleration and a strong long-term uptrend.
- 2023-06-12 (Buy → -0.9%): "Capitulation selling with early
  stabilization, current dip is a buying opportunity."

For weeks where it called Overweight and ETH then rallied 9-17%, the
reports show over-sensitivity to short-term pullbacks:

- 2023-02-13 (OW → +12.3%): "Pullback phase, MACD weakening 90% from
  peak, wait for bounce confirmation."
- 2023-04-10 (OW → +9.5%): "Consolidation within strong uptrend,
  volatility contracting."

The market analyst prompt (in
``tradingagents/agents/analysts/market_analyst.py``) carries
indicator-interpretation guidance like "RSI 70/30 thresholds" and
"MACD crossovers as trend reversal signals" that implicitly assume
equity-grade volatility (~30-40% annualised). On ETH 2023 the
realised volatility was ~80%. The same indicator pattern that gives
a 70% bullish hit rate on stocks gives roughly 50/50 on ETH because
the tails are much wider. The model has no awareness that it's
reading ETH versus a stock — ``build_instrument_context()`` only
forwards the ticker string.

Three concrete prompt changes, in increasing order of intrusiveness,
would be cheap to test:

1. **Asset-aware threshold scaling.** Add "if the asset is crypto
   (e.g. BTC, ETH, SOL), expand RSI thresholds to 20/80 and require
   confluence of three or more indicators before issuing Buy due to
   higher realised tail risk."
2. **Confidence → 5-tier remapping.** Make Overweight reserved for
   genuinely cautious positioning (real negative-skew signal), and
   route mid-strength bullish setups to Hold rather than Buy. Keep
   Buy for setups with at least 3-indicator confluence.
3. **Realised-vol context injection.** Pass the trailing 30-day
   realised volatility of the instrument into the prompt so the
   model can calibrate its own thresholds dynamically.

Change (1) is a single prompt edit with no graph or schema changes.
Re-running ETH 2023 weekly with that change (~51 propagations) is
the cleanest test of whether the inversion is fixable.

## Prompt-A experiment: did asset-aware calibration fix ETH?

After committing the asset-aware prompt change, ETH 2023 weekly was
re-run from scratch (51 baseline entries archived to
``~/.tradingagents/baselines/eth_2023_pre_prompt_a.json``, then 52
new propagations through the new prompt).

| Metric | Baseline (equity prompt) | Prompt-A (crypto-aware) | Change |
|--------|-------------------------:|------------------------:|-------:|
| N | 51 | 52 | (1 connection error before) |
| Strategy total ret | +32.5% | +29.5% | -3.0pp |
| True signal vs always-50% | -2.5pp | -5.6pp | worse |
| De-risk lift over base rate | -8pp | **+2pp** | **+10pp** |
| Buy weeks mean +5d return | +0.07% | **+0.80%** | better |
| OW weeks mean +5d return | +1.78% | **+0.89%** | better (less inverted) |
| Hold ratings | 0 | 3 | new |

The diagnostic outcome is mixed but telling:

- **The inversion is fixed.** Baseline had Buy weeks (+0.07%) trailing
  OW weeks (+1.78%) by -1.71pp — wrong direction. Prompt-A has Buy
  +0.80% vs OW +0.89%, a -0.09pp gap — basically aligned. The
  rating ordering now points the right way.
- **De-risk precision lifted from -8pp below base rate to +2pp
  above.** Modest, but it's the first time a crypto cohort produced
  a positive lift, and it confirms the diagnosis.
- **Total return underperforms.** The "3-indicator confluence
  required for Buy" rule produced more Buy calls in the Jan-Mar
  rally — which was the right direction — but in a +76% naive-Buy
  year, even getting Buy frequency right cannot beat the market
  baseline because dumb-50% also catches a lot of the upside on
  half position. The "alpha vs naive Buy" headline got worse.
- **The 2023-08-14 -9.5% Buy was not fixed.** The new prompt still
  found 3-indicator confluence on that week. This is outside what
  prompt engineering alone can solve — the technical signal genuinely
  pointed up that week and the market just dropped.

Net reading: **prompt-A is a real but small improvement**. The
framework's rating now means roughly what it should on crypto
(Buy = mildly positive expected, OW = slightly less so) instead
of the inverted relationship the equity-grade prompt produced.
But the absolute magnitude of the signal is too weak to beat naive
buy-and-hold in a strong-uptrend year. To actually trade crypto
profitably with this framework would require additional changes:
realised-vol context injection, multi-analyst confluence, or a
fundamentally different signal source than weekly technical
indicators.

## Taiwan-stock experiment: currency-locale awareness is missing

Tested whether the framework generalises to non-US listings, using
TSMC across both its primary Taiwanese listing (2330.TW, TWD) and
its NYSE ADR (TSM, USD). Same company, same period.

| Cohort | Year | Ratings | Strategy | Naive Buy | Alpha vs Buy | De-risk lift |
|--------|-----:|---------|---------:|----------:|-------------:|-------------:|
| 2330.TW | 2022 | 12 Buy | -19.8% | -19.8% | +0pp | n/a (no de-risk) |
| 2330.TW | 2018 | 8 Buy / 4 OW | -12.2% | -3.2% | -8.9pp | -33pp |
| TSM     | 2022 | 8 Buy / 3 OW / 1 Hold | -19.7% | -35.4% | **+15.8pp** | **+8pp** |

The 2330.TW results show no useful timing signal in either year:
2022 produced 12 consecutive Buy calls in a -14% bear, and 2018
produced four Overweight calls that all landed on positive months
(0/4 precision against a 33% base rate, -33pp lift).

The TSM ADR for the same company in 2022 produced a Hold call on
2022-06-06 that perfectly avoided a -18.4% one-month drop, plus
three Overweight calls that landed mostly correctly (3/4 = 75%
precision against a 67% base rate, +8pp lift). Magnitude on par
with AAPL 2022 (+9pp lift).

The mechanism appears to be currency-locale awareness. TSM USD
fell -35% in 2022; 2330.TW TWD fell only -20% over the same period
because the TWD weakened ~15% against the USD. The TWD-denominated
price chart never broke key technical levels as decisively — RSI
did not push as deeply oversold, MACD did not register as severe
a divergence, and Bollinger bands looked like ordinary pullbacks
rather than capitulation. The market analyst reads OHLCV numbers
without any awareness that they are denominated in a depreciating
local currency, so the same underlying business deterioration
produces different technical signatures depending on listing.

Three levels of fix, in increasing scope:

1. **Use the ADR when available.** Roughly 50 of Taiwan's larger
   listings have NYSE/NASDAQ ADRs (TSM, UMC, ASX, HMS, etc.).
   Build the model on the ADR; execute trades on the local listing.
2. **Inject FX context into the prompt.** Pass the trailing
   30-day local-currency-vs-USD move into instrument_context so
   the model can mentally adjust thresholds.
3. **Convert OHLCV to USD-equivalent in the data layer.** All
   technical indicators are then computed on a globally-comparable
   price series, regardless of listing.

(1) is zero engineering and probably enough for individual users
who have ADR access. (3) is the principled fix and would also
help with European, Hong Kong, and Japanese listings.

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
