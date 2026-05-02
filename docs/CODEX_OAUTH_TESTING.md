# Codex OAuth 測試手冊

把 ChatGPT 訂閱當成 LLM provider 跑 TradingAgents 的端到端測試流程。

> ⚠️ **使用前請理解**
> 這份功能是逆向工程 OpenAI Codex CLI 的 OAuth flow，**用個人 ChatGPT Plus / Pro / Team 訂閱**驅動 TradingAgents。OpenAI 不官方支援這種用法，client_id / endpoint / 偵測規則隨時可能改變，最壞情況可能導致 ChatGPT 帳號被風控甚至停權。**僅供個人實驗，不要對外宣傳，也不要 commit 任何含有 access token 的檔案到公開 repo。**

---

## 0. 前置條件

| 項目 | 要求 |
|------|------|
| Python | 3.10+ |
| ChatGPT 帳號 | Plus / Pro / Team（免費版**不行**） |
| 網路 | 可連 `auth.openai.com` 與 `chatgpt.com` |
| 套件 | 已 `pip install .` 安裝 TradingAgents |

確認專案安裝成功：

```bash
python -c "from tradingagents.llm_clients.codex_oauth import _auth_path, get_base_url; print('auth path:', _auth_path()); print('base url:', get_base_url())"
```

期望看到：

```
auth path: C:\Users\<你>\.tradingagents\auth\codex.json
base url: https://chatgpt.com/backend-api/codex
```

---

## 1. 登入（第一次跑必做）

### 1a. 用 CLI 登入（推薦）

```bash
tradingagents auth login
```

會顯示類似：

```
To sign in to ChatGPT (Codex), do these two things:

  1. Open this URL in any browser:  https://auth.openai.com/codex/device
  2. Enter this code:               ABCD-EFGH

Waiting for sign-in (Ctrl+C to cancel)...
```

照做：
1. 用瀏覽器開那個 URL
2. 輸入終端機顯示的 code
3. 用你的 ChatGPT 帳號完成登入授權
4. 終端機會看到：

```
Saved Codex credentials to C:\Users\<你>\.tradingagents\auth\codex.json
```

### 1b. 直接呼叫模組（如果 `tradingagents` 指令還沒裝起來）

```bash
python -m tradingagents.llm_clients.codex_oauth login
```

行為一樣。

### 1c. 已經用過 Codex CLI 的話

如果你機器上 `~/.codex/auth.json` 已經有有效 token，第一次呼叫 `get_access_token()` 會自動 import 過來，**不用重複登入**。可以跳過 1a / 1b。

---

## 2. 確認 token 狀態

```bash
tradingagents auth status
```

正常輸出：

```
Codex auth: ok (access token expires in 17234s)
  Path: C:\Users\<你>\.tradingagents\auth\codex.json
  Source: device-code  Last refresh: 2026-05-02T10:23:45Z
```

如果看到 `No Codex credentials stored` → 回去做步驟 1。

---

## 3. 三層測試（從最小到完整）

### Test 1 — 純 token 解析（離線可跑）

不打網路，只驗證模組可以匯入、token 檔讀得到、JWT 解得開：

```bash
python -c "
from tradingagents.llm_clients.codex_oauth import _load_tokens, _decode_jwt_claims
state = _load_tokens()
access = state['tokens']['access_token']
claims = _decode_jwt_claims(access)
print('subject:', claims.get('sub'))
print('issuer:', claims.get('iss'))
print('exp:', claims.get('exp'))
"
```

期望：印出 OpenAI 的 issuer + 你的 subject + 過期時間（Unix timestamp）。

如果失敗：
- `CodexAuthError: No Codex credentials stored` → 步驟 1 沒做
- `subject: None` → token 檔損壞，先 `tradingagents auth logout` 再 login

---

### Test 2 — 端到端 chat completion（最關鍵）

實際打一通 LLM 請求，驗證 endpoint 和 token 都能用。執行專案附的 smoke test：

```bash
python scripts/test_codex_oauth.py gpt-5.4-mini
```

期望輸出：

```
Creating Codex OAuth client for model=gpt-5.4-mini ...
Calling chat.completions ...
---
pong
---
```

可以替換不同模型試：

```bash
python scripts/test_codex_oauth.py gpt-5.4
python scripts/test_codex_oauth.py gpt-5.4-codex
```

#### 常見錯誤

| 錯誤訊息 | 意思 | 解法 |
|---------|------|------|
| `401 Unauthorized` | access token 不被接受 | `auth logout` → `auth login` 重新登入 |
| `403 Forbidden` | 帳號權限不足（可能是 free 帳號） | 確認 ChatGPT 訂閱還有效 |
| `404 Not Found` | endpoint 已被 OpenAI 改掉 | 該功能可能短期失效，等 Hermes upstream 跟進 |
| `model_not_found` | ChatGPT backend 不認識這個 model | 換成 `gpt-5.4-mini` 等已知模型 |
| `refresh_token_reused` | 別的 client（Codex CLI / VS Code 擴充）搶走了 refresh token | 先用 `codex` 指令登入產新 token，再 `tradingagents auth login` |
| `rate_limit_exceeded` | ChatGPT 訂閱有額度上限 | 等一下再跑 |

---

### Test 3 — 跑一次完整 TradingAgents pipeline

最終驗收：用 Codex 當 LLM 跑一支股票的完整分析。

建立一個臨時測試檔（不要 commit）：

```python
# test_codex_full.py
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from dotenv import load_dotenv

load_dotenv()

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "codex"            # ← 切到 Codex
config["deep_think_llm"] = "gpt-5.4-mini"   # 先用便宜的模型試水溫
config["quick_think_llm"] = "gpt-5.4-mini"
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
python test_codex_full.py
```

跑完應該看到：
1. 終端機刷出多個 agent 的中間訊息（`debug=True` 開了 stream）
2. 最後印出 5 級評等之一：`Buy / Overweight / Hold / Underweight / Sell`
3. `~/.tradingagents/logs/NVDA/TradingAgentsStrategy_logs/full_states_log_2024-05-10.json` 出現
4. `~/.tradingagents/memory/trading_memory.md` 多一筆 pending entry

**整輪大約會耗掉幾百次 LLM 呼叫**——四個 analyst 各自跑工具迭代、bull/bear 辯論、三個 risk 角色辯論。如果你的 ChatGPT 訂閱有 rate limit，建議：
- `max_debate_rounds = 0` + `max_risk_discuss_rounds = 0` 把辯論關到最少
- `selected_analysts = ["market"]` 只跑一個 analyst
- 跑單支 ticker 而不是批次

---

## 4. 驗證 token 自動 refresh

ChatGPT 的 access token 通常 **6 小時** 過期。為了確認自動 refresh 沒爆掉，可以：

### 4a. 手動觸發 refresh（不等過期）

```python
from tradingagents.llm_clients.codex_oauth import get_access_token
old = get_access_token()                       # 取目前 token
new = get_access_token(force_refresh=True)     # 強制 refresh
print("changed:", old != new)
```

期望：`changed: True`，且後續 `tradingagents auth status` 看到 `Last refresh` 時間更新。

### 4b. 等過期後重跑

放著 6+ 小時不動，然後再跑步驟 3 的 smoke test。模組會自動偵測 JWT exp 在 120 秒內到期 → 用 refresh_token 拿新 access_token → 繼續跑，使用者不會看到任何錯誤。

如果 refresh 失敗，會看到清楚的錯誤訊息要你 `auth login` 重登。

---

## 5. 與 Codex CLI 共存的注意事項

如果你機器上同時有：
- 官方 Codex CLI (`~/.codex/auth.json`)
- TradingAgents (`~/.tradingagents/auth/codex.json`)
- VS Code Codex 擴充

**OpenAI 的 refresh token 是 single-use**：誰先用就誰拿到新 token，舊的會失效。症狀是 refresh 時拿到 `refresh_token_reused`。

兩個解法：

1. **每次只用一邊**：跑 TradingAgents 前先在 VS Code / Codex CLI 登出
2. **互相同步**：定期把 `~/.codex/auth.json` 內容同步到 `~/.tradingagents/auth/codex.json`（注意 schema 略有不同，TradingAgents 用平的 `{"tokens": {"access_token", "refresh_token"}, ...}`）

---

## 6. 完整檢查清單

跑完以下都過 = Codex OAuth 整合可用：

- [ ] `tradingagents auth login` 成功
- [ ] `tradingagents auth status` 顯示 `ok`
- [ ] Test 1（離線解析）印出 issuer / sub / exp
- [ ] Test 2（smoke test）印出 `pong`
- [ ] Test 3（完整 pipeline）跑出評等且檔案有寫到 `~/.tradingagents/`
- [ ] `force_refresh=True` 後 token 確實換了
- [ ] `tradingagents auth logout` 能清掉 token

---

## 7. 退場 / 清理

不想再用了，把所有殘留刪掉：

```bash
tradingagents auth logout

# Windows
rmdir /s /q %USERPROFILE%\.tradingagents

# macOS / Linux
rm -rf ~/.tradingagents
```

把測試用的 `test_codex_full.py` 也刪掉，避免不小心 commit 進 git。

---

## 附錄：環境變數覆寫

| 變數 | 預設 | 說明 |
|------|------|------|
| `TRADINGAGENTS_HOME` | `~/.tradingagents` | 整個 TradingAgents 資料根目錄 |
| `TRADINGAGENTS_CODEX_BASE_URL` | `https://chatgpt.com/backend-api/codex` | Codex backend endpoint，有時可改成 reverse proxy |
| `TRADINGAGENTS_CODEX_REFRESH_TIMEOUT` | `20` (秒) | refresh 請求 timeout |
| `CODEX_HOME` | `~/.codex` | 從哪裡 import Codex CLI 既有 token |

---

## 出問題時要看的檔

- [tradingagents/llm_clients/codex_oauth.py](../tradingagents/llm_clients/codex_oauth.py) — OAuth flow 與 token 管理
- [tradingagents/llm_clients/codex_client.py](../tradingagents/llm_clients/codex_client.py) — LangChain 整合
- [tradingagents/llm_clients/factory.py](../tradingagents/llm_clients/factory.py) — provider 註冊
- [scripts/test_codex_oauth.py](../scripts/test_codex_oauth.py) — smoke test 腳本

如果整套壞了，最快回到正常狀態的方式：

```bash
tradingagents auth logout
tradingagents auth login
python scripts/test_codex_oauth.py gpt-5.4-mini
```
