"""Drive Anthropic API with the Claude Code OAuth token.

Anthropic officially supports OAuth Bearer auth on ``/v1/messages`` when the
``anthropic-beta: oauth-2025-04-20`` header is present, so users with a paid
Claude Pro / Max subscription can drive TradingAgents through their own
Claude Code login — no API key required, no API credit consumed.

Token source: ``~/.claude/.credentials.json`` (written by Claude Code on
``claude login``). Token refresh: handled by Claude Code itself; if the
access token has expired, this module attempts a refresh via the same
endpoint Claude Code uses, and falls back to a clear error telling the user
to run ``claude`` once to re-authenticate.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib import error, request

# Public OAuth client ID used by Claude Code itself.
CLAUDE_CODE_OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
CLAUDE_OAUTH_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
ANTHROPIC_OAUTH_BETA_HEADER = "oauth-2025-04-20"

ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120


class ClaudeAuthError(RuntimeError):
    """Raised when Claude Code OAuth token cannot be loaded or refreshed."""

    def __init__(self, message: str, *, code: str = "", relogin_required: bool = False):
        super().__init__(message)
        self.code = code
        self.relogin_required = relogin_required


def _credentials_path() -> Path:
    override = os.getenv("CLAUDE_CREDENTIALS_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / ".credentials.json"


def _load_full_state() -> Dict[str, Any]:
    """Read the full credentials.json (preserves non-OAuth keys on save)."""
    path = _credentials_path()
    if not path.exists():
        # Allow env var override for headless / CI use.
        env_token = os.getenv("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
        if env_token:
            return {"claudeAiOauth": {"accessToken": env_token}}
        raise ClaudeAuthError(
            f"No Claude credentials at {path}. Run `claude login` first, "
            "or set CLAUDE_CODE_OAUTH_TOKEN.",
            code="claude_auth_missing",
            relogin_required=True,
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ClaudeAuthError(
            f"Failed to parse {path}: {exc}",
            code="claude_auth_read_failed",
            relogin_required=True,
        ) from exc


def _save_full_state(state: Dict[str, Any]) -> None:
    """Atomically write back to credentials.json."""
    path = _credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _is_expiring(expires_at_ms: Any, skew_seconds: int) -> bool:
    if not isinstance(expires_at_ms, (int, float)):
        return False
    return float(expires_at_ms) / 1000.0 <= (time.time() + max(0, int(skew_seconds)))


def _refresh(refresh_token: str, *, timeout: float = 20.0) -> Dict[str, Any]:
    """Exchange a refresh_token for a new access_token via Anthropic's OAuth endpoint."""
    if not refresh_token:
        raise ClaudeAuthError(
            "No refresh_token stored. Run `claude login` to re-authenticate.",
            code="claude_refresh_missing_token",
            relogin_required=True,
        )

    body = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLAUDE_CODE_OAUTH_CLIENT_ID,
    }).encode("utf-8")

    req = request.Request(
        CLAUDE_OAUTH_TOKEN_URL,
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        relogin = exc.code in (400, 401, 403)
        raise ClaudeAuthError(
            f"Claude token refresh failed (HTTP {exc.code}): {detail}",
            code="claude_refresh_http_error",
            relogin_required=relogin,
        ) from exc
    except Exception as exc:
        raise ClaudeAuthError(
            f"Claude token refresh failed: {exc}",
            code="claude_refresh_failed",
            relogin_required=False,
        ) from exc

    new_access = payload.get("access_token")
    if not new_access:
        raise ClaudeAuthError(
            "Refresh response missing access_token.",
            code="claude_refresh_no_access_token",
            relogin_required=True,
        )
    return {
        "accessToken": new_access,
        "refreshToken": payload.get("refresh_token") or refresh_token,
        "expiresAt": int(time.time() * 1000) + int(payload.get("expires_in", 3600)) * 1000,
    }


def get_access_token(*, force_refresh: bool = False) -> str:
    """Return a usable Claude Code access token, refreshing if needed."""
    state = _load_full_state()
    oauth = state.get("claudeAiOauth") or {}
    access_token = (oauth.get("accessToken") or "").strip()
    refresh_token = (oauth.get("refreshToken") or "").strip()
    expires_at = oauth.get("expiresAt")

    needs_refresh = bool(force_refresh) or _is_expiring(
        expires_at, ACCESS_TOKEN_REFRESH_SKEW_SECONDS
    )

    if not access_token and not refresh_token:
        raise ClaudeAuthError(
            "Credentials file has no accessToken or refreshToken. Run `claude login`.",
            code="claude_auth_empty",
            relogin_required=True,
        )

    if needs_refresh and refresh_token:
        try:
            refreshed = _refresh(refresh_token)
        except ClaudeAuthError:
            # If refresh fails but we still have a non-empty access token,
            # try it anyway — Anthropic sometimes accepts tokens slightly
            # past their advertised exp.
            if access_token and not force_refresh:
                return access_token
            raise

        oauth.update(refreshed)
        state["claudeAiOauth"] = oauth
        try:
            _save_full_state(state)
        except Exception:
            pass  # Read-only filesystems shouldn't block auth.
        return refreshed["accessToken"]

    if not access_token:
        raise ClaudeAuthError(
            "No accessToken available. Run `claude login`.",
            code="claude_auth_no_access_token",
            relogin_required=True,
        )
    return access_token


def get_subscription_info() -> Dict[str, Any]:
    """Best-effort metadata: subscription type, scopes, expiry."""
    try:
        state = _load_full_state()
    except ClaudeAuthError:
        return {}
    oauth = state.get("claudeAiOauth") or {}
    return {
        "subscriptionType": oauth.get("subscriptionType"),
        "scopes": oauth.get("scopes"),
        "expiresAt": oauth.get("expiresAt"),
        "rateLimitTier": oauth.get("rateLimitTier"),
    }


def is_available() -> bool:
    """True if ~/.claude/.credentials.json has a usable access token.

    Note: the long-lived ``CLAUDE_CODE_OAUTH_TOKEN`` setup token is checked
    separately by ``anthropic_client._setup_token_from_env`` because it
    follows the standard API-key code path, not this OAuth Bearer path.
    """
    try:
        state = _load_full_state()
    except ClaudeAuthError:
        return False
    oauth = state.get("claudeAiOauth") or {}
    return bool(oauth.get("accessToken"))


def _cli(argv: Optional[list] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    cmd = (argv[0] if argv else "status").lower()

    if cmd == "status":
        # Setup-token (claude setup-token) takes precedence — it's the
        # Anthropic-supported third-party path with no refresh needed.
        env_token = (os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or "").strip()
        if env_token:
            print("Claude auth source: CLAUDE_CODE_OAUTH_TOKEN (setup token)")
            print(f"  Token starts: {env_token[:25]}...")
            print("  Lifetime: long-lived (no refresh needed)")
            print("  Sent as: x-api-key (standard API-key path)")
            return 0

        info = get_subscription_info()
        if not info:
            print("Claude auth: not configured.")
            print("Options:")
            print("  - run `claude setup-token` and export CLAUDE_CODE_OAUTH_TOKEN, or")
            print("  - run `claude login` to populate ~/.claude/.credentials.json, or")
            print("  - export ANTHROPIC_API_KEY for a regular API key.")
            return 1
        exp = info.get("expiresAt")
        exp_str = (
            datetime.fromtimestamp(float(exp) / 1000, tz=timezone.utc).isoformat()
            if isinstance(exp, (int, float))
            else "unknown"
        )
        scopes = info.get("scopes") or []
        has_inference = "user:inference" in scopes
        print("Claude auth source: ~/.claude/.credentials.json (claude login)")
        print(f"  Path: {_credentials_path()}")
        print(f"  Subscription: {info.get('subscriptionType')}")
        print(f"  Inference scope: {'yes' if has_inference else 'NO (cannot drive API)'}")
        print(f"  Token expires (UTC): {exp_str}")
        return 0 if has_inference else 1

    if cmd == "refresh":
        try:
            token = get_access_token(force_refresh=True)
        except ClaudeAuthError as exc:
            print(f"Refresh failed: {exc}", file=sys.stderr)
            return 1
        print(f"Refreshed. New token starts: {token[:25]}...")
        return 0

    print("Usage: python -m tradingagents.llm_clients.claude_oauth [status|refresh]")
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_cli())
