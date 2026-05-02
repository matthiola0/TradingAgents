"""Quick smoke test for the Codex OAuth client.

Run AFTER `tradingagents auth login` (or
`python -m tradingagents.llm_clients.codex_oauth login`).

Sends a tiny chat completion through the ChatGPT (Codex) backend so you can
confirm token resolution + endpoint compatibility without spinning up the
full TradingAgents pipeline.
"""

from __future__ import annotations

import sys

from tradingagents.llm_clients import create_llm_client


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else "gpt-5.4-mini"
    print(f"Creating Codex OAuth client for model={model} ...")
    client = create_llm_client(provider="codex", model=model)
    llm = client.get_llm()
    print("Calling chat.completions ...")
    resp = llm.invoke("Reply with exactly the word: pong")
    text = getattr(resp, "content", resp)
    print("---")
    print(text)
    print("---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
