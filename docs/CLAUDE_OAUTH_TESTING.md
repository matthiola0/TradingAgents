# Claude OAuth 測試手冊

把 **Claude Pro / Max 訂閱**當成 LLM provider 跑 TradingAgents 的端到端測試流程。

> ✅ **這條路是 Anthropic 官方支援的**——`anthropic-beta: oauth-2025-04-20` 是公開 beta header，`/v1/messages` 接受 OAuth Bearer auth 是 Anthropic 自己鋪的路（同樣的 mechanism Claude Code、Hermes 等工具都在用）。比起 Codex OAuth 的逆向工程，這條路風險低很多。但仍然非主流公開 API 用法，建議自己測試使用即可，不要對外大規模部署。

---

## 0. 前置條件

| 項目 | 要求 |
|------|------|
| Python | 3.10+ |
| Claude 訂閱 | Pro / Max（Free 不行） |
| Claude Code | 已安裝且至少登入過一次（`claude login`） |
| 套件 | 已 `pip install .` 安裝 TradingAgents |

確認 Claude Code 已登入：

```bash
ls ~/.claude/.credentials.json
# 或 Windows
dir %USERPROFILE%\.claude\.credentials.json
```

如果沒有這個檔，先：

```bash
claude login
```

---

## 1. 確認 token 狀態

```bash
tradingagents claude-auth status
```

期望輸出：

```
Claude Code: logged in
  Path: C:/Users/Pan/.claude/.credentials.json
  Subscription: max
  Inference scope: yes
  Token expires (UTC): 2026-05-02T07:46:40+00:00
```

關鍵看：
- `Subscription` 是 `pro` / `max` / `team`（不是 `free`）
- `Inference scope: yes`（`user:inference` 在 scopes 裡）

如果 `Inference scope: NO`，代表你的 token 沒有推論權限，需要重新登入更新 scope。

---

## 2. 三層測試（從最小到完整）

### Test 1 — OAuth 模組自身（離線可跑）

```bash
python -c "
from tradingagents.llm_clients.claude_oauth import (
    is_available, get_subscription_info, get_access_token,
)
print('available:', is_available())
print('info:', get_subscription_info())
print('access_token starts:', get_access_token()[:25], '...')
"
```

期望：
```
available: True
info: {'subscriptionType': 'max', 'scopes': [...], ...}
access_token starts: sk-ant-oat01-... ...
```

**注意**：`get_access_token()` 會在 token 過期前 120 秒自動 refresh。如果 token 還新，是直接回傳；如果 refresh 失敗會丟 `ClaudeAuthError` 並提示你跑 `claude login`。

---

### Test 2 — 直接打 Anthropic API（不經過 LangChain）

驗證 OAuth + endpoint 整條鏈路通：

```bash
python scripts/test_claude_oauth_poc.py claude-haiku-4-5-20251001
```

期望：
```
Using OAuth token: sk-ant-oat01-... model=claude-haiku-4-5-20251001
HTTP 200
---
pong
---
```

#### 常見錯誤

| 訊息 | 意思 | 解法 |
|------|------|------|
| HTTP 401 | OAuth token 無效或過期 | `tradingagents claude-auth refresh`，或 `claude login` 重登 |
| HTTP 403 | scope 不含 `user:inference` | `claude logout` 後 `claude login` 取得新 scope |
| HTTP 404 | endpoint 改了 | beta header 失效；查 Anthropic 最新 OAuth 公告 |
| HTTP 429 | 訂閱 rate limit | 等一下再跑 |
| `model_not_found` | 模型名打錯 | 換 `claude-opus-4-7` 或 `claude-haiku-4-5-20251001` |

---

### Test 3 — 經過 LangChain `ChatAnthropic`

驗證 TradingAgents 的 `AnthropicClient` 自動偵測 OAuth 並走對的 path：

```bash
python -c "
from tradingagents.llm_clients import create_llm_client
client = create_llm_client(provider='anthropic', model='claude-haiku-4-5-20251001')
llm = client.get_llm()
resp = llm.invoke('Reply with exactly the word: pong')
print('content:', getattr(resp, 'content', resp))
"
```

期望：
```
content: pong
```

幕後做的事：
1. `AnthropicClient.get_llm()` 偵測到 `ANTHROPIC_API_KEY` 沒設、`~/.claude/.credentials.json` 存在
2. 自動切到 OAuth path：`get_access_token()` 拿 token
3. 把 token 同時設給 `api_key` 跟 `default_headers["Authorization"]`，加上 `anthropic-beta: oauth-2025-04-20`
4. `ChatAnthropic.invoke()` 透過 LangChain 包裝送出請求

**強制走 API key 路徑**（如果需要 debug）：

```bash
TRADINGAGENTS_ANTHROPIC_AUTH=api_key python -c "..."
```

**強制走 OAuth 路徑**（即使設了 ANTHROPIC_API_KEY）：

```bash
TRADINGAGENTS_ANTHROPIC_AUTH=oauth python -c "..."
```

---

### Test 4 — 完整 TradingAgents pipeline

最終驗收：用 Claude 訂閱跑一支股票分析。

建立 `test_claude_full.py`（**不要 commit 進 git**）：

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from dotenv import load_dotenv

load_dotenv()

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "anthropic"
config["deep_think_llm"] = "claude-opus-4-7"
config["quick_think_llm"] = "claude-haiku-4-5-20251001"
config["max_debate_rounds"] = 1
config["max_risk_discuss_rounds"] = 1
config["data_vendors"] = {
    "core_stock_apis": "yfinance",
    "technical_indicators": "yfinance",
    "fundamental_data": "yfinance",
    "news_data": "yfinance",
}

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("NVDA", "2024-05-10")
print("=" * 60)
print("DECISION:", decision)
```

執行：

```bash
python test_claude_full.py
```

跑完應該看到：
- 多個 agent 的中間 stream 訊息
- 最後印出 `Buy / Overweight / Hold / Underweight / Sell` 之一
- `~/.tradingagents/logs/NVDA/TradingAgentsStrategy_logs/full_states_log_2024-05-10.json` 出現
- `~/.tradingagents/memory/trading_memory.md` 多一筆 pending entry

> **rate limit 提醒**：完整 pipeline 一輪會打 100+ 次 LLM 請求（4 個 analyst × 工具迭代 × bull/bear 辯論 × 3 risk 角色辯論）。Claude Max 5x 訂閱足夠跑單支 ticker；Pro 訂閱建議：
> - `max_debate_rounds = 0`、`max_risk_discuss_rounds = 0` 把辯論關到最少
> - `selected_analysts = ["market"]` 只跑一個 analyst
> - 用 `claude-haiku-4-5-20251001` 當主力，`claude-opus-4-7` 只給 deep_think

---

## 3. 驗證 token 自動 refresh

### 3a. 強制 refresh

```bash
tradingagents claude-auth refresh
```

期望：
```
Refreshed. New token starts: sk-ant-oat01-... ...
```

跑完之後 `~/.claude/.credentials.json` 的 `accessToken` 與 `expiresAt` 會更新。

### 3b. 過期自動 refresh

放著 token 過期（`expiresAt` 在過去），再跑 Test 2。`AnthropicClient` 會：
1. 偵測 `expiresAt` 已過或在 120 秒內過期
2. 用 `refreshToken` 跟 Anthropic 換新 token
3. 寫回 `credentials.json`
4. 繼續送請求，使用者看不到中間過程

如果 refresh 失敗（例如 refresh_token 也過期），會丟錯誤訊息要你重 `claude login`。

---

## 4. Auth 路徑優先順序

`AnthropicClient` 自動選擇：

```
有設 TRADINGAGENTS_ANTHROPIC_AUTH=api_key  →  強制走 API key
有設 TRADINGAGENTS_ANTHROPIC_AUTH=oauth    →  強制走 OAuth
傳了 api_key kwarg                          →  走 API key
ANTHROPIC_API_KEY 環境變數有值              →  走 API key
~/.claude/.credentials.json 存在 + 可解析   →  走 OAuth
都沒有                                       →  raise RuntimeError
```

意思是：**只要你設了 `ANTHROPIC_API_KEY`，OAuth 自動讓位**——既有使用者升級不會被影響。

---

## 5. 完整檢查清單

跑完以下都過 = Claude OAuth 整合可用：

- [ ] `claude login` 已完成（或 `~/.claude/.credentials.json` 已存在）
- [ ] `tradingagents claude-auth status` 顯示 `Inference scope: yes`
- [ ] Test 1 印出 `available: True` + 訂閱資訊
- [ ] Test 2 (`scripts/test_claude_oauth_poc.py`) 印出 `pong`
- [ ] Test 3 (`create_llm_client(provider='anthropic')`) 印出 `pong`
- [ ] Test 4 (完整 pipeline) 跑出 5 級評等
- [ ] `tradingagents claude-auth refresh` 能更新 token
- [ ] 過期測試（或手動把 expiresAt 改成過去）後再跑能自動 refresh

---

## 6. 退場 / 清理

不想再用了：

```bash
# 把 TradingAgents 切回 API key（不影響 Claude Code 本身）
unset TRADINGAGENTS_ANTHROPIC_AUTH
export ANTHROPIC_API_KEY=sk-ant-xxx

# 或完全登出 Claude Code（會影響 Claude Code）
claude logout
```

---

## 附錄：環境變數覆寫

| 變數 | 預設 | 說明 |
|------|------|------|
| `CLAUDE_CREDENTIALS_PATH` | `~/.claude/.credentials.json` | 自訂 credentials 路徑 |
| `CLAUDE_CODE_OAUTH_TOKEN` | (未設) | headless / CI 用，直接帶一個 access token，跳過讀檔 |
| `TRADINGAGENTS_ANTHROPIC_AUTH` | (自動) | `api_key` 或 `oauth` 強制路徑 |
| `ANTHROPIC_API_KEY` | (未設) | 設了就走 API key 路徑 |

---

## 出問題時要看的檔

- [tradingagents/llm_clients/claude_oauth.py](../tradingagents/llm_clients/claude_oauth.py) — token 讀寫 + refresh
- [tradingagents/llm_clients/anthropic_client.py](../tradingagents/llm_clients/anthropic_client.py) — auth path 選擇邏輯
- [scripts/test_claude_oauth_poc.py](../scripts/test_claude_oauth_poc.py) — stdlib-only PoC
- [docs/CODEX_OAUTH_TESTING.md](CODEX_OAUTH_TESTING.md) — Codex OAuth 對照（架構幾乎一樣）

---

## Codex OAuth vs Claude OAuth 對照

| 維度 | Codex OAuth | Claude OAuth |
|------|-------------|--------------|
| 合法性 | 灰色（逆向 client_id） | 較白（Anthropic 自家 beta header） |
| 是否需要 device-code flow | 是（自己跑） | 不需要（Claude Code 已登入過） |
| Token 來源 | `~/.tradingagents/auth/codex.json` | `~/.claude/.credentials.json`（共用 Claude Code） |
| Endpoint | `chatgpt.com/backend-api/codex` (內部) | `api.anthropic.com/v1/messages` (公開) |
| Auth header | `Authorization: Bearer ...` | `Authorization: Bearer ...` + `anthropic-beta: oauth-2025-04-20` |
| Refresh | 自家 token store | 寫回 Claude Code 的 credentials.json |
| structured output | 強制 `function_calling` | 完全相容 LangChain |

兩者在 TradingAgents 內共存——`config["llm_provider"]` 決定走哪邊：
- `"codex"` → Codex OAuth + ChatGPT subscription
- `"anthropic"` → 自動偵測 OAuth or API key
- `"openai"` / 其他 → 原本路徑不變
