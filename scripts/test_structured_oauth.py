"""Verify with_structured_output survives the OAuth Bearer auth path.

Reproduces the failure mode seen during the 26-week NVDA backtest where
the Portfolio Manager's structured-output call hit "invalid x-api-key"
even though plain invoke() worked. After the SDK-client-level Bearer
fix, this script should print a parsed Pydantic instance.

Run from the repo root inside the tradingagents conda env:

    python scripts/test_structured_oauth.py
"""

from __future__ import annotations

from pydantic import BaseModel

from tradingagents.llm_clients import create_llm_client


class Out(BaseModel):
    answer: str
    score: int


def main() -> None:
    client = create_llm_client(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
    )
    base = client.get_llm()

    print("Test 1: plain invoke")
    r1 = base.invoke("Reply with exactly the word: pong")
    print(f"  content: {getattr(r1, 'content', r1)!r}")

    print("Test 2: with_structured_output")
    structured = base.with_structured_output(Out)
    r2 = structured.invoke("Reply with answer='pong' and score=42")
    print(f"  result: {r2!r}")
    assert isinstance(r2, Out), f"expected Out, got {type(r2)}"
    print("OK — both auth paths went out as Bearer.")


if __name__ == "__main__":
    main()
