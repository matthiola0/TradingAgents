# Strategy V1 — Crypto-Confluence

A concrete, mechanically-implementable trading strategy built on top of the
TradingAgents framework's market-analyst signal. Designed against 8 full
years of BTC monthly data (2018-2025) and validated cross-asset on SOL
(4 years) and ETH (4 years). Stop-loss centric — works on assets with
crypto-grade volatility, **does not transfer to equities**.

## Backtest result

### Single-asset on BTC (8-year base case)

```
                                         8-year ret    Max DD
Naive Buy & hold every month                  +227%       -81%
Plain Buy=1.0 / OW=0.5 / Hold=0 (with fees)   +581%       -62%
  + 2-month Buy confluence filter              +356%       -57%
  + Stop loss at -15%                         +1095%       -44%
Strategy V1 (confluence + stop + brake + fee) +1425%       -37%
```

CAGR ≈ 40% vs naive ~16%; max drawdown roughly halved.

### Cross-asset validation

Same V1 rules applied to other tickers in the memory log:

| Asset | Years | Naive total | V1 total | Naive DD | V1 DD | V1 CAGR | V1 beats naive? |
|-------|------:|------------:|---------:|---------:|------:|--------:|:---------------:|
| BTC-USD | 8 | +227% | +1425% | -81% | -37% | ~40% | ✓ |
| SOL-USD | 4 | +44% | +611% | -92% | -41% | ~63% | ✓ |
| AVAX-USD | 4 | -41% | **+169%** | -87% | -30% | ~28% | ✓✓ +210pp |
| DOGE-USD | 4 | -56% | -17% | -88% | -62% | ~-5% | ✓ +39pp |
| ETH-USD | 4 | +28% | +59% | -76% | -39% | ~12% | ✓ (modest) |
| BNB-USD | 4 | +99% | +77% | -67% | -33% | ~15% | **✗ -22pp** |
| NVDA | 6.5 | **+1695%** | +752% | -64% | -37% | ~38% | **✗** |

**Refined: V1 needs fat-tail volatility to work.** Across 6 crypto
assets and 1 equity, V1 wins big on assets with frequent -30%+ months
(BTC, SOL, AVAX, DOGE), modestly on borderline cases (ETH), and **fails
on lower-volatility utility assets (BNB)** — same failure mode as NVDA.

BNB is the surprising case: as the 4th-largest crypto by market cap,
one might expect V1 to work. But BNB 2022-2025 was a steady +99% with
relatively shallow drawdowns. The model issued 35 Overweight calls
out of 48 (73%, vs ~25% on BTC), and confluence + stop loss cut
profitable runs short. BNB acts more like an equity than a fat-tail
crypto.

The pattern is clear:
- **V1 works**: BTC, SOL, AVAX (all had -50%+ drawdowns and recoveries)
- **V1 fails**: BNB, NVDA (steady uptrend, smaller drawdowns)

Use V1 for high-vol crypto majors. Use V2 (the no-stop-loss equity
strategy) for low-vol assets, including stable utility tokens like BNB.

## Why each rule is in there

| Rule | Why | Backtest impact |
|------|-----|-----------------|
| Universe = crypto majors (BTC + SOL) | 8-year BTC + 4-year SOL data; matches the strategy's stop-loss-centric design | NVDA case shows applying V1 to equities loses to naive |
| Monthly cadence | Matches the backtest data we have; trader convenience | — |
| 2-month Buy confluence | Reduces entry on single-month bullish noise | Alone: -225pp. With stop+brake: positive contribution |
| Stop loss -15% | Caps the catastrophic-month damage that backtester showed | +514pp — the single largest alpha source |
| Drawdown brake -25% | Pauses strategy 1 month after big losses (recovery period) | +330pp on top of stop loss |
| 0.1% per-trade fee | Realistic Binance spot fee | -109pp drag, factored in |
| Long-only | Framework never produced Sell ratings (0/290) | No short logic to validate |

## Position rules

Every month, on the first Monday's close, read the latest TradingAgents
rating for BTC-USD. Map to target portfolio fraction:

| Latest rating | Prior month's rating | Target position |
|--------------|---------------------|----------------:|
| Buy | Buy | **100%** (full conviction) |
| Buy | anything else | **50%** (single-Buy probe) |
| Overweight | any | **50%** (default half) |
| Hold | any | **0%** (sit in cash / stable) |
| Underweight | any | **0%** (would be short, but never seen) |
| Sell | any | **0%** (likewise) |

## Risk caps

### Stop loss
After entering a position, place a stop-limit order at **-15% from entry
price**. If hit during the holding period, exit immediately. Realised
trade P&L is capped at -15% × position size (minus slippage).

Re-enter only on the **next Buy rating** the following month — no
mid-period re-entry.

### Drawdown brake
After every monthly close, compute portfolio peak-to-current drawdown.

If drawdown ≤ **-25%**:
1. Halt strategy: target position = 0% for the next 1 month regardless
   of rating.
2. Reset peak to the current portfolio value (so the brake doesn't
   re-fire repeatedly while still under the original peak).
3. Resume normal rules on month +2.

Brake fired 1× across 8-year backtest (after 2018-11 stop loss). Saved
the strategy from a stretch of mid-2018 losses. Without brake reset
the strategy permanently locks out — verify your implementation handles
this correctly (the original V1 prototype had this bug).

## Execution

### Timing

Run the LLM signal on **Sunday evening** (US time) using
`propagate("BTC-USD", <Sunday-date>)`. This gives the model BTC OHLCV
through Sunday close.

Place orders **Monday at market open** (00:00 UTC for crypto). Use a
market order on Binance / OKX spot — for the typical position sizes
this strategy targets (<$1M BTC), slippage is < 0.05%.

Place the stop-limit order immediately after entry, with stop price
= entry price × 0.85 and limit price = entry × 0.84 (1% buffer).

### Position sizing

```
target_value = portfolio_equity_usd * target_fraction
target_btc   = target_value / btc_price
delta_btc    = target_btc - current_btc

if abs(delta_btc) * btc_price > 50:   # ignore dust
    place_market_order("BTC", delta_btc)
```

Use mark-to-market portfolio equity (so the strategy auto-sizes up as
it grows and down after losses).

### Cost structure

- Anthropic LLM: subscription via Claude Code OAuth (covered)
- Binance spot fee: 0.1% per side = 0.2% round trip
- Average yearly turnover at full Strategy V1: ~70% of NAV
- Annual fee drag: ~0.14% of NAV

## Reproducing the backtest

```powershell
python scripts\strategy_v1.py
```

Expected output: 8-year monthly trades for BTC, with each row showing
target vs actual position, raw market return, realised P&L (after stop
loss / fees), and `STOP` / `BRAKE` markers when those rules fired.

## Implementation checklist

- [ ] Open Binance spot account + create API key with trading-only scope
- [ ] Set up environment: `CLAUDE_CODE_OAUTH_TOKEN`, `BINANCE_API_KEY`,
      `BINANCE_API_SECRET`, ticker symbol "BTCUSDT"
- [ ] Write a thin `broker_adapter.py` exposing:
      `get_balance()`, `get_position("BTC")`, `place_market("BTC", delta)`,
      `place_stop_limit(...)`
- [ ] Write `weekly_runner.py`:
      1. Sunday 23:00 UTC: call `propagate("BTC-USD", today)`
      2. Read latest 2 ratings from memory log
      3. Determine target position via the table above
      4. Monday 00:01 UTC: place orders
      5. Set stop-limit
      6. Log to local file for monitoring
- [ ] Run **paper mode for 4 weeks** matching real-time signals to a
      paper account, verify P&L matches backtest expectations within 1%
- [ ] Hard cap: never exceed 50% of total liquid net worth in this
      strategy. Treat the +1425% backtest as upper bound, not target —
      the actual realised number after slippage / black swans will be
      lower.

## Caveats

1. **8 years is one BTC cycle.** It includes 2018 ICO bust, 2020 COVID,
   2021 retail mania, 2022 LUNA/FTX, 2023-24 ETF rally, 2025 plateau.
   Results may not generalize to fundamentally different crypto regimes.
2. **Stop loss is modelled at intraperiod-min daily close.** Real
   stop-limit fills depend on how violent the move is. Add 0.5% extra
   slippage to be conservative — the alpha barely budges.
3. **No tax / no funding cost.** Adjust for your jurisdiction.
4. **The framework may stop being usable.** OAuth could break, the
   model could be deprecated, the prompt could regress. Have a
   fallback (e.g. switch to plain Buy=1.0 / OW=0.5 / Hold=0 if signal
   pipeline fails).

## What's next

- **Add NVDA leg** to diversify (6 years of NVDA data shows 5/7
  positive cohorts — second best ticker after BTC)
- **Re-test with prompt-A** for crypto-aware calibration to see if it
  changes signal quality (it would re-run BTC, expensive)
- **Walk-forward optimization** of the stop-loss threshold (-10% vs
  -15% vs -20%) on rolling 5-year windows
- **Position sizing refinement** based on the rating's executive_summary
  prose (currently ignored — it sometimes contains "scale in 25-50%"
  hints we don't use)
