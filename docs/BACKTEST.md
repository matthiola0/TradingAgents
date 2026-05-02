# Backtest 手冊

把 TradingAgents 的決策跑成可量化的策略，分兩個獨立步驟：

1. **採樣** — `scripts/run_backtest.py` 在指定日期範圍內呼叫 `propagate()`，把決策寫入 memory log
2. **評估** — `scripts/backtester.py` 讀 memory log、抓實際報酬、算 P&L

兩步驟分開的原因：LLM 呼叫貴又慢，採樣只跑一次；之後可以無限次重新評估（換倉位映射、換持有天數），不用再花 LLM 錢。

---

## 為什麼能 backtest

| 機制 | 出處 |
|------|------|
| 所有資料工具吃 `curr_date` 並 filter 未來資料 | [stockstats_utils.py:85](../tradingagents/dataflows/stockstats_utils.py#L85) |
| Decision 落盤到 markdown log | [memory.py:31](../tradingagents/agents/utils/memory.py#L31) |
| 自動算實際 5 日報酬 + SPY alpha | [trading_graph.py:190](../tradingagents/graph/trading_graph.py#L190) |
| LangGraph SQLite checkpoint，跑壞能續跑 | [checkpointer.py](../tradingagents/graph/checkpointer.py) |

所以歷史日期跑 `propagate("NVDA", "2024-05-10")` 不會看到 2024-05-10 之後的資料。

---

## 0. 前置

確認你已經完成：

```powershell
conda activate tradingagents
tradingagents claude-auth status      # Inference scope: yes
python test_claude_full.py            # 至少跑通一次
```

---

## Step 1：採樣（呼叫 LLM 寫入 memory log）

### 最小例子：NVDA 半年週頻

```powershell
python scripts/run_backtest.py --ticker NVDA --start 2024-01-01 --end 2024-06-30
```

預設：
- `--frequency weekly`（每週一）= 26 個樣本
- `--analysts market`（只跑 Market analyst）
- `--debate-rounds 0`、`--risk-rounds 0`（沒有辯論）
- `--provider anthropic`（用你的 Claude OAuth）
- `--deep-model claude-haiku-4-5-20251001`、`--quick-model` 同上
- 開 checkpoint

每次 propagate 大概 30-60 秒（Haiku + 單 analyst + 0 rounds），半年週頻 = 約 15-30 分鐘。

### 先 dry-run 看計畫

```powershell
python scripts/run_backtest.py --ticker NVDA --start 2024-01-01 --end 2024-06-30 --dry-run
```

會印出每個會跑的 `(ticker, date)` 對，不打 LLM。確認日期數量、看會不會打爆 rate limit。

### 多 ticker 月頻

```powershell
python scripts/run_backtest.py --tickers NVDA,AAPL,MSFT,GOOGL `
  --start 2024-01-01 --end 2024-12-31 --frequency monthly
```

3 ticker × 12 月 = 36 次 propagate，比週頻便宜 4 倍。

### 加上其他 analyst（成本上升）

```powershell
python scripts/run_backtest.py --ticker NVDA --start 2024-01-01 --end 2024-06-30 `
  --analysts market,fundamentals --debate-rounds 1 --risk-rounds 1
```

採樣中斷了？再跑同一行就好——memory log 有 idempotency guard，已寫過 pending entry 不會重做；checkpoint 也會從上次失敗節點繼續。

---

## Step 2：評估（不打 LLM）

採樣完跑：

```powershell
python scripts/backtester.py --ticker NVDA
```

期望輸出：

```
Trades: 26  (8 pending in memory log)
Period: 2024-01-01 -> 2024-06-30

Rating distribution:
  Buy            12
  Overweight     7
  Hold           4
  Underweight    2
  Sell           1

Performance:
  Total return        +18.4%
  Win rate            61.5%
  Avg trade P&L       +0.7%
  Sharpe (weekly,ann) 1.42
  Max drawdown        -7.2%
  Buy-and-hold        +25.1%  (baseline)
```

> **Pending 的意思**：memory log 裡這幾筆還沒 framework 自帶的 5 日 alpha 反思（要等下一次同 ticker 跑才會結算）。但 backtester 不依賴那些 — 它**自己**重新跑 yfinance 算每筆持有期報酬，所以 pending 也會被算進 P&L。

### 換持有天數測敏感度

```powershell
python scripts/backtester.py --ticker NVDA --holding-days 1
python scripts/backtester.py --ticker NVDA --holding-days 5
python scripts/backtester.py --ticker NVDA --holding-days 10
python scripts/backtester.py --ticker NVDA --holding-days 20
```

訊號穩健的策略，5 天和 10 天的 Sharpe 不會差太多；如果只在 1 天賺錢，那是過度依賴 day-1 漂移，警訊。

### 匯出 trades 到 CSV 自己分析

```powershell
python scripts/backtester.py --ticker NVDA --csv nvda_trades.csv
```

CSV 欄位：`date, ticker, rating, position, log_raw_return, log_alpha_return, raw_return, alpha_return, actual_holding_days, trade_pnl, pending`

### 用 Python 進階分析

```python
from scripts.backtester import Backtester
import matplotlib.pyplot as plt

# 預設 Buy=+1, Overweight=+0.5, Hold=0, Underweight=-0.5, Sell=-1
bt = Backtester(ticker="NVDA", holding_days=5)
out = bt.run()

print(out["metrics"])
out["equity_curve"].plot(label="TradingAgents")
out["baseline"].plot(label="Buy & hold")
plt.legend()
plt.show()
```

換成 long-only 策略（Sell 不放空）：

```python
bt = Backtester(
    ticker="NVDA",
    holding_days=5,
    position_map={"Buy": 1.0, "Overweight": 0.5, "Hold": 0.0,
                  "Underweight": 0.0, "Sell": 0.0},   # ← 全卡 0
)
print(bt.run()["metrics"])
```

只交易最強訊號（Buy / Sell 才動，其他全 hold）：

```python
bt = Backtester(
    ticker="NVDA",
    position_map={"Buy": 1.0, "Overweight": 0.0, "Hold": 0.0,
                  "Underweight": 0.0, "Sell": -1.0},
)
```

這就是 backtester 跟 run_backtest 解耦的價值：上面三組都不用再呼叫 LLM。

---

## 預估成本

每次 propagate 的 LLM 呼叫量（粗估）：

| 配置 | 呼叫數 |
|------|--------|
| 1 analyst (market) + 0 rounds | ~10 |
| 4 analysts + 0 rounds | ~30 |
| 4 analysts + debate=1 + risk=1 | ~80 |

換算到 backtest 規模：

| 範圍 | 大概呼叫數 | Claude Max 5x 跑得完嗎 |
|------|-----------|----------------------|
| 1 ticker × 半年 weekly × market only | ~260 | 容易 |
| 1 ticker × 1 年 weekly × 4 analysts × debate=1 | ~4000 | 慢但可以 |
| 5 ticker × 1 年 weekly × full | ~20000 | 會撞 rate limit，要慢慢來 |
| 5 ticker × 5 年 monthly × market only | ~3000 | 可以 |

> Claude Max 5x 訂閱大概每 5 小時可發 200-400 次 Sonnet 4.5 / Haiku 4.5 請求（依模型而定，rate limit 有時會突發限流）。

---

## 推薦工作流

### 第一階段：訊號可用性檢查（一天）

```powershell
# 1. 採樣
python scripts/run_backtest.py --ticker NVDA --start 2024-01-01 --end 2024-06-30

# 2. 看分佈
python scripts/backtester.py --ticker NVDA
```

**檢查重點**：
- Rating 分佈是不是平衡（不要 90% Buy 或 80% Hold）
- Win rate 是不是合理（>50% 才有意義）
- Sharpe 是不是顯著大於 0
- 跟 buy-and-hold 比，多頭年（2024 H1）TradingAgents 的 Sharpe 應該贏過 buy-and-hold，總報酬可能輸（因為有 cash drag）

### 第二階段：換配置敏感度測試（不花錢）

```powershell
python scripts/backtester.py --ticker NVDA --holding-days 1
python scripts/backtester.py --ticker NVDA --holding-days 10
python scripts/backtester.py --ticker NVDA --holding-days 20
```

訊號穩 → 不同 holding days 結果接近；訊號弱 → 散得很開。

### 第三階段：擴大範圍（看訊號跨週期穩定性）

```powershell
python scripts/run_backtest.py --ticker NVDA --start 2022-01-01 --end 2024-12-31 --frequency monthly
python scripts/backtester.py --ticker NVDA
```

跨 3 年（含一個熊市）能維持正 Sharpe，才算有真實 alpha。

### 第四階段：多 ticker 跨資產（最後做）

```powershell
python scripts/run_backtest.py --tickers NVDA,AAPL,MSFT,GOOGL,AMZN,META,TSLA `
  --start 2023-01-01 --end 2024-12-31 --frequency monthly
```

然後對每個 ticker 跑 backtester，看是不是都正 Sharpe，還是只有特定 ticker 有效。

---

## 故障排除

| 症狀 | 解法 |
|------|------|
| `No trades found in memory log` | 還沒採樣，先跑 `run_backtest.py` |
| 採樣到一半 rate limit | 等 5-10 分鐘，相同指令再跑（idempotent） |
| 採樣很慢 | 把 `--debug` 拿掉、`--analysts market` 減少 analyst |
| Sharpe 很低但 total return 高 | 檢查是不是訊號全往一邊（看 rating distribution） |
| Pending 數量不歸零 | 那是 framework 自己的反思 — 不影響 backtester；`run_backtest.py` 多跑一次同 ticker 就會結算 |
| 想清掉 memory log 重來 | `rm ~/.tradingagents/memory/trading_memory.md` |

---

## 已知限制

1. **沒有手續費 / slippage** — 純 close-to-close 報酬。實盤要扣 1-3 bps
2. **持有期假設固定** — 不會根據新訊號動態調倉，每筆 trade 獨立持有 N 天
3. **不重疊處理** — 如果週頻 + 5 天持有 = trade 之間其實有 overlap，但目前每筆獨立 compound（保守估計）
4. **沒有 portfolio 級別約束** — 多 ticker 時等權重，沒做 vol target / risk parity / 槓桿管理
5. **單向 alpha 計算** — alpha 跟 SPY 比；非美股需要改 benchmark

要做更嚴謹的 backtest（考慮 overlap、手續費、停損等），把 trades CSV 餵進 `backtrader` 或 `vectorbt`。

---

## 出問題時要看的檔

- [scripts/run_backtest.py](../scripts/run_backtest.py) — 採樣 driver
- [scripts/backtester.py](../scripts/backtester.py) — 評估 lib + CLI
- [tradingagents/agents/utils/memory.py](../tradingagents/agents/utils/memory.py) — memory log 格式與 idempotency
- [tradingagents/graph/trading_graph.py](../tradingagents/graph/trading_graph.py#L190) — `_fetch_returns()` 是 backtester 的 yfinance 邏輯來源

---

## 一頁速覽

```powershell
# 1. 採樣（要錢，跑一次）
python scripts/run_backtest.py --ticker NVDA --start 2024-01-01 --end 2024-06-30

# 2. 評估（免費，可重複跑）
python scripts/backtester.py --ticker NVDA
python scripts/backtester.py --ticker NVDA --holding-days 10
python scripts/backtester.py --ticker NVDA --csv trades.csv
```
