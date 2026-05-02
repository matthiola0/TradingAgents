# 從零開始：建一個乾淨的 conda env 跑 TradingAgents（含 Claude OAuth）

從零安裝到看到第一個 `pong` 的完整步驟。為什麼要新環境：避免跟你現有的 `quant` / `cryptoquant` 等 env 套件衝突，特別是 `langchain-*` 系列版本要求嚴格。

> **目標時間**：15 分鐘安裝 + 5 分鐘測試。

---

## 0. 你需要的東西

- ✅ Anaconda（你機器上已裝在 `C:\Users\Pan\anaconda3`）
- ✅ Claude Code 已登入 Pro / Max（`~/.claude/.credentials.json` 存在）
- ✅ Git（cloning the repo），你已有 repo 在 `C:\Users\Pan\Desktop\code\TradingAgents`

---

## 1. 建立新 conda 環境

開 **PowerShell** 或 **Anaconda Prompt**：

```powershell
conda create -n tradingagents python=3.13 -y
conda activate tradingagents
```

確認啟用成功：

```powershell
python --version
# 期望: Python 3.13.x

where python
# 期望: C:\Users\Pan\anaconda3\envs\tradingagents\python.exe
```

> 為什麼用 3.13：repo 的 README 範例用 3.13，`pyproject.toml` 要求 `>=3.10`。3.10 / 3.11 / 3.12 也行，選你慣用的。

---

## 2. 安裝 TradingAgents（editable mode）

```powershell
cd C:\Users\Pan\Desktop\code\TradingAgents
pip install -e .
```

這會把 repo 本體 + 所有依賴（langchain-anthropic, langgraph, yfinance, ...）裝起來，大概 2-3 分鐘。

> `-e` 是 editable：你之後改 `tradingagents/` 底下的 code，不用重裝就立刻生效。

安裝完驗證：

```powershell
pip show tradingagents
# 期望看到 Version: 0.2.4 + Location 指到你的 repo
```

```powershell
python -c "from tradingagents.llm_clients import create_llm_client; print('import ok')"
# 期望: import ok
```

---

## 3. 確認 Claude Code 已登入

```powershell
dir $env:USERPROFILE\.claude\.credentials.json
```

如果不存在：

```powershell
claude login
```

---

## 4. Claude OAuth 整合測試（5 層由小到大）

### Test 1 — TradingAgents 認得 Claude Code login

```powershell
tradingagents claude-auth status
```

期望：

```
Claude Code: logged in
  Path: C:/Users/Pan/.claude/.credentials.json
  Subscription: max
  Inference scope: yes
  Token expires (UTC): 2026-05-02T07:46:40+00:00
```

關鍵看：
- `Subscription` 是 `pro` / `max` / `team`
- `Inference scope: yes`

❌ 如果 `tradingagents` 指令找不到：你應該還在舊 env，重做步驟 1 + 2。

---

### Test 2 — OAuth 模組單元測試

```powershell
python -c "from tradingagents.llm_clients.claude_oauth import is_available, get_subscription_info; print('available:', is_available()); print('info:', get_subscription_info())"
```

期望：

```
available: True
info: {'subscriptionType': 'max', 'scopes': ['user:file_upload', 'user:inference', ...], ...}
```

---

### Test 3 — 直接打 Anthropic API（不經 LangChain）

```powershell
python scripts\test_claude_oauth_poc.py claude-haiku-4-5-20251001
```

期望：

```
Using OAuth token: sk-ant-oat01-... model=claude-haiku-4-5-20251001
HTTP 200
---
pong
---
```

❌ HTTP 401 → token 過期，跑 `tradingagents claude-auth refresh` 或 `claude login`
❌ HTTP 403 → scope 沒 `user:inference`，需要 `claude logout` + `claude login`

---

### Test 4 — 經過 LangChain `ChatAnthropic`

```powershell
python -c "from tradingagents.llm_clients import create_llm_client; client = create_llm_client(provider='anthropic', model='claude-haiku-4-5-20251001'); llm = client.get_llm(); resp = llm.invoke('Reply with exactly the word: pong'); print('content:', getattr(resp, 'content', resp))"
```

期望：

```
content: pong
```

這一步驗證 OAuth + LangChain + structured output 的橋接全部通了。

---

### Test 5 — 完整 TradingAgents pipeline

建立 `test_claude_full.py` 在 repo root（**不要 commit**）：

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

執行（會跑幾分鐘）：

```powershell
python test_claude_full.py
```

期望：
- 終端機刷出多個 agent 訊息
- 最後印出 `Buy / Overweight / Hold / Underweight / Sell` 之一
- 多了 `~/.tradingagents/logs/NVDA/...` 的 JSON 檔
- 多了 `~/.tradingagents/memory/trading_memory.md` 一筆 entry

> **Pro 訂閱省錢配置**（避免一輪打爆 rate limit）：
>
> ```python
> ta = TradingAgentsGraph(
>     selected_analysts=["market"],   # 只跑一個 analyst
>     debug=True,
>     config=config,
> )
> config["max_debate_rounds"] = 0
> config["max_risk_discuss_rounds"] = 0
> ```

---

## 5. 常用後續指令（記住這些就夠）

```powershell
# 切到這個環境
conda activate tradingagents

# 跑互動式 CLI（內建的 wizard 介面）
tradingagents analyze

# 跑 Python 腳本
python main.py
python test_claude_full.py

# 看 token 狀態
tradingagents claude-auth status

# 強制 refresh token
tradingagents claude-auth refresh

# 跑單元測試（OAuth 不需要 API key 就能跑）
python -m pytest tests -q
```

---

## 6. 移除這個 env（萬一要清掉重來）

```powershell
conda deactivate
conda env remove -n tradingagents
```

不會影響你其他 env。

---

## 故障排除快速對照

| 症狀 | 解法 |
|------|------|
| `ModuleNotFoundError: No module named 'tradingagents'` | 沒裝 / 沒進 env：`conda activate tradingagents` + `pip install -e .` |
| `tradingagents` 指令找不到 | 沒進 env，或 pip install 失敗 |
| `tradingagents claude-auth status` 印 `not logged in` | 跑 `claude login` |
| `Inference scope: NO` | `claude logout` + `claude login`，更新 scope |
| Test 3 HTTP 401 | token 過期：`tradingagents claude-auth refresh` |
| Test 4 拋 `RuntimeError: Claude OAuth not ready` | 確認 Test 1 + Test 2 都通 |
| Test 5 跑到一半 rate limit | 把 `max_debate_rounds` / analyst 數量降到最小 |
| 想暫時切回 API key | `$env:ANTHROPIC_API_KEY = "sk-ant-xxx"`，OAuth 自動讓位 |

---

## 完整流程一頁速覽

```powershell
# === 一次性安裝 ===
conda create -n tradingagents python=3.13 -y
conda activate tradingagents
cd C:\Users\Pan\Desktop\code\TradingAgents
pip install -e .

# === 確認 Claude 登入 ===
claude login                                           # 已登入可跳過
tradingagents claude-auth status                       # Inference scope: yes

# === 由小到大跑測試 ===
python scripts\test_claude_oauth_poc.py claude-haiku-4-5-20251001
python -c "from tradingagents.llm_clients import create_llm_client; print(create_llm_client(provider='anthropic', model='claude-haiku-4-5-20251001').get_llm().invoke('Reply pong').content)"
python test_claude_full.py                             # 自己建的完整 pipeline 腳本
```

跑通最後那行就代表你的 Claude Max 訂閱已經在驅動 TradingAgents 了。
