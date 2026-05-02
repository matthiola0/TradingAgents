"""Minimal PoC: drive Anthropic API with the Claude Code OAuth token.

Reads ~/.claude/.credentials.json (where Claude Code stores its OAuth access
token after login), then sends one tiny chat message directly to the
Anthropic /v1/messages endpoint using:

    Authorization: Bearer <oauth_access_token>
    anthropic-beta: oauth-2025-04-20

If this prints "pong" without 401/403, your Claude Pro/Max subscription is
already wired up and we can plug the same auth into TradingAgents'
AnthropicClient next.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib import request, error


def load_oauth_token() -> str:
    path = Path.home() / ".claude" / ".credentials.json"
    if not path.exists():
        sys.exit(f"No Claude credentials at {path}. Run `claude login` first.")
    data = json.loads(path.read_text(encoding="utf-8"))
    token = (data.get("claudeAiOauth") or {}).get("accessToken")
    if not token:
        sys.exit("Credentials file missing claudeAiOauth.accessToken.")
    return token


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else "claude-haiku-4-5-20251001"
    token = load_oauth_token()
    print(f"Using OAuth token: {token[:25]}... model={model}")

    body_bytes = json.dumps({
        "model": model,
        "max_tokens": 32,
        "messages": [{"role": "user", "content": "Reply with exactly the word: pong"}],
    }).encode("utf-8")

    req = request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body_bytes,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=30) as resp:
            status = resp.status
            payload = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        print(f"HTTP {exc.code}")
        print(exc.read().decode("utf-8", errors="replace"))
        return 1

    print(f"HTTP {status}")
    body = json.loads(payload)
    text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
    print("---")
    print(text.strip() or body)
    print("---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
