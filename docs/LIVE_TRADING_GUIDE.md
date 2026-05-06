# Live Trading Guide — BTC + SOL on Binance

從 paper 到實單的完整步驟。配置：**60% BTC + 40% SOL，Strategy V1 (confluence + stop loss -15% + drawdown brake -25%)**。

歷史回測（4 年 2022-2025）：

```
                    4-year ret   CAGR    Max DD    Sharpe
Naive Buy&Hold      +84%         +17%    -82%      0.54
Strategy V1 60/40   +271%        +39%    -36%      0.98
```

---

## Step 1 — Binance 帳戶 + API key

1. **開戶**：[binance.com](https://www.binance.com) 或 [binance.us](https://www.binance.us)（依你所在地）
2. **完成 KYC**（身份驗證）
3. **入金 USDT**（從信用卡 / 銀行轉帳）
4. **建 API key**：
   - 進 `Account` → `API Management` → `Create API`
   - **權限只勾「Enable Spot & Margin Trading」**
   - **絕對不要勾「Enable Withdrawals」** —— 即使 key 被偷也只能交易不能提款
   - 開啟 IP 白名單（限制只能從你機器 IP 連，最強保護）
5. **儲存 API key + secret**：用密碼管理員存，貼進 `.env`：

```bash
BINANCE_API_KEY=<your_key>
BINANCE_API_SECRET=<your_secret>
```

## Step 2 — 安裝 python-binance

```powershell
conda activate tradingagents
pip install python-binance
```

驗證能讀帳戶：

```powershell
$env:BINANCE_API_KEY = "<your_key>"
$env:BINANCE_API_SECRET = "<your_secret>"
python -c "from binance.client import Client; import os; c = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET')); print(c.get_account()['balances'][:3])"
```

如果印出 USDT 等餘額就 OK。如果報 `APIError(code=-2015): Invalid API-key`，檢查 key / IP 白名單 / 權限設定。

## Step 3 — Dry run 驗證

確認 framework 訊號跟 Binance 連線都通：

```powershell
# Generate signals (latest BTC + SOL ratings)
python scripts\run_backtest.py --ticker BTC-USD --start (Get-Date -Format "yyyy-MM-dd") --end (Get-Date -Format "yyyy-MM-dd") --frequency monthly
python scripts\run_backtest.py --ticker SOL-USD --start (Get-Date -Format "yyyy-MM-dd") --end (Get-Date -Format "yyyy-MM-dd") --frequency monthly

# Dry run trader (no real orders)
python scripts\live_trader.py --portfolio-usd 1000
```

期望輸出：

```
2026-05-06 ... [INFO] DRY RUN  paper NAV $1000.00
2026-05-06 ... [INFO] Planned 2 order(s):
2026-05-06 ... [INFO]   BUY BTCUSDT  qty 0.005000  $+300.00  (single-month Buy)
2026-05-06 ... [INFO]     market order: DRY_RUN
2026-05-06 ... [INFO]     stop-limit @ $51000.00: DRY_RUN_STOP
2026-05-06 ... [INFO]   BUY SOLUSDT  qty 1.500000  $+200.00  (Overweight)
...
```

如果 dry run 看起來合理，繼續 step 4。

## Step 4 — Paper 模式跑 4 週

**先用 Binance Testnet 跑真 API 但假錢**：

1. 註冊 [testnet.binance.vision](https://testnet.binance.vision/)
2. 拿 testnet API key + secret
3. 設環境變數時用 testnet keys
4. 改 `live_trader.py` 加 testnet base URL（可選）

或者**直接 dry run 跑 4 週**收集 signal，月底比較預期 vs 實際 Binance 公開行情，看 paper P&L 跟實際對得上。

每週執行（Sunday 23:00 UTC）：

```powershell
# Cron / Task Scheduler 排程
python scripts\run_backtest.py --ticker BTC-USD --start (Get-Date -Format "yyyy-MM-dd") --end (Get-Date -Format "yyyy-MM-dd") --frequency monthly
python scripts\run_backtest.py --ticker SOL-USD --start (Get-Date -Format "yyyy-MM-dd") --end (Get-Date -Format "yyyy-MM-dd") --frequency monthly
python scripts\live_trader.py
```

記下每週 dry-run 預期的 portfolio NAV，跟你**手動算**「拿真 Binance 收盤價套同樣訊號」的結果比。差距應 < 1%（main source: bid-ask spread + slippage）。

## Step 5 — Live 上線

確認 paper 4 週 P&L 符合預期之後：

1. **入金小額** — 我建議 **$500-1000 USDT** 起步，不要 commit 大錢
2. **跑 live**：

```powershell
python scripts\live_trader.py --live
```

3. **監控**：
   - 每次 run 後檢查 `~/.tradingagents/live_state.json`
   - 跟 Binance 帳戶 balance 對得上嗎？
   - Stop-limit orders 有出現在 `Open Orders`？
4. **設預警**：
   - Binance app 的 price alert
   - 你自己的 daily check 看 `live_state.json` 有沒有奇怪變化

## Step 6 — 排程

### Windows Task Scheduler

1. 開 Task Scheduler → Create Task
2. **Triggers**：每週日 23:00 UTC（你的時區換算）
3. **Action**: Start a program
   - Program: `powershell.exe`
   - Arguments: `-Command "& 'C:\Users\Pan\anaconda3\envs\tradingagents\python.exe' 'C:\Users\Pan\Desktop\code\TradingAgents\scripts\weekly_run.ps1'"`

建立 `weekly_run.ps1`：

```powershell
$today = Get-Date -Format "yyyy-MM-dd"
& 'C:\Users\Pan\anaconda3\envs\tradingagents\python.exe' 'scripts\run_backtest.py' --ticker BTC-USD --start $today --end $today --frequency monthly
& 'C:\Users\Pan\anaconda3\envs\tradingagents\python.exe' 'scripts\run_backtest.py' --ticker SOL-USD --start $today --end $today --frequency monthly
& 'C:\Users\Pan\anaconda3\envs\tradingagents\python.exe' 'scripts\live_trader.py' --live | Tee-Object -Append "$env:USERPROFILE\.tradingagents\trade_log.txt"
```

### Linux / macOS cron

```bash
# /etc/crontab
0 23 * * 0 panuser cd /path/to/TradingAgents && \
  python scripts/run_backtest.py --ticker BTC-USD --start $(date +%Y-%m-%d) --end $(date +%Y-%m-%d) --frequency monthly && \
  python scripts/run_backtest.py --ticker SOL-USD --start $(date +%Y-%m-%d) --end $(date +%Y-%m-%d) --frequency monthly && \
  python scripts/live_trader.py --live >> ~/.tradingagents/trade_log.txt 2>&1
```

## 風險限制（強烈建議）

不論你多有信心，**這些 cap 一定要設**：

| Cap | 建議值 | 為什麼 |
|------|------|------|
| 起始本金 | $500-2000 USDT | 不要一上線就 all-in |
| 整體 framework 占淨值上限 | 25-50% | 留半倉以上不參與，黑天鵝才有救 |
| 每筆 order 上限 | 50% NAV | 已內建 `MAX_SINGLE_ORDER_FRAC = 0.50` |
| Daily kill switch | -10% | 自己加 logic：state file 看到當日 P&L < -10% 就 sell all 不再執行訊號 |
| Per-ticker stop loss | -15% | 已內建 V1 `STOP_LOSS = -0.15`，下 stop-limit 自動執行 |
| Drawdown brake | peak -25% | 已內建 V1，brake 後 1 個月不交易該 leg |

## 常見問題

**Q: 訊號當天才產生，Binance 卻 24/7 — 什麼時間執行？**

A: BTC/SOL 24/7 沒收盤，但 framework 訊號用 daily candle。建議：
- **Sunday 23:00 UTC** 跑訊號（用 Sunday 收盤資料）
- **Monday 00:01 UTC** 立刻執行（Sunday close 的下一秒）

**Q: 我的 USDT 不在 Binance，怎麼辦？**

A: 從你的銀行 / 信用卡 / OTC 入金 USDT 到 Binance 才能交易。也可以用 Binance Pay / TWD（如果有開 Binance TR / Binance JEX 等地區版）。

**Q: 賺到錢要繳稅嗎？**

A: 看你居住地。台灣目前加密交易暫時沒有明確稅法，但實質課稅原則下大金額流動可能被審查。記錄每筆交易（live_state.json + Binance trade history）保留至少 5 年。

**Q: Anthropic LLM 額度會爆嗎？**

A: BTC + SOL weekly = 2 propagations / week ≈ 100 / year。Claude Max 訂閱絕對夠。Setup token 不過期。

**Q: 訊號失靈怎麼辦？**

A: 三種情況：

1. **Anthropic API 掛掉** → `live_trader.py` 沒有新訊號 → 不下單，繼續持倉
2. **Token 失效** → 拿不到訊號 → 同上
3. **訊號質量退化**（模型 prompt regression）→ 你會在 paper 對照中先發現

最壞情況：手動清倉 — `python scripts/live_trader.py --emergency-close`（這個我還沒寫，但可以 trivially 加）。

## 出問題時的緊急操作

```powershell
# 立刻清所有部位（直接操作 Binance app 比 script 快）
# 1. 登入 Binance app
# 2. Spot trading
# 3. Sell all BTC -> USDT (market order)
# 4. Sell all SOL -> USDT (market order)
# 5. 取消所有 Open Orders（包含 stop-limit）

# 然後改 live_state.json: 把 positions 設 0，否則下次 trader run 會嘗試買回
```

## 心理建設

**這個策略 4 年 max DD 是 -36%**。意思是你 $1000 起步，**有可能某段時間看到帳戶剩 $640**。

- 那是策略設計的一部分（不是 bug）
- 歷史上之後都恢復並超越前高
- 但你要事先想好：看到 -30% 帳戶餘額會不會手動清倉？如果會，就**少投入**

**永遠不要把超過你能損失的錢丟進來**。

---

## 部署後 ongoing 維護

每週：
- [ ] 檢查 trade_log.txt 有沒有錯誤
- [ ] 比對 live_state.json 跟 Binance 實際餘額
- [ ] 確認 stop-limit orders 還在

每月：
- [ ] 比對 paper_backtest.py 預期 vs 實際 P&L deviation
- [ ] 如果 deviation > 5%，找原因（slippage？訊號問題？）

每季：
- [ ] 重跑 strategy_v1.py 看新月份結果
- [ ] 評估是否要調 universe（換掉表現不佳的標的）

## 完整 commit 路徑

實作整個 trading stack 用到的檔案：

```
scripts/
  run_backtest.py        — 產生訊號（從 Anthropic API）
  live_trader.py         — 主 runner（這份 guide 教你的）
  btc_sol_portfolio.py   — 歷史回測（驗證選擇）
  paper_backtest.py      — 全 stack orchestrator 回測
  paper_trader.py        — Multi-asset 5-leg 版（如果你要加 NVDA / AVAX）
  strategy_v1.py         — V1 邏輯參考
docs/
  STRATEGY_V1.md         — V1 完整 spec
  LIVE_TRADING_GUIDE.md  — 這份 guide
  RESEARCH_2022.md       — 全研究 25 cohorts 紀錄
```

開始 paper 4 週，然後 $500 真錢上線測試 1 個月。**不順利就停，再看**。
