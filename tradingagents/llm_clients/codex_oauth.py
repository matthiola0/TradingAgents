"""ChatGPT (Codex) OAuth device-code authentication for TradingAgents.

This module replicates the OAuth flow used by the official OpenAI Codex CLI
so that users with a paid ChatGPT account (Plus / Pro / Team) can drive
TradingAgents through their ChatGPT subscription instead of paying for
OpenAI API credit.

Flow summary (device code, no browser redirect):

  1. POST  /api/accounts/deviceauth/usercode   -> user_code + device_auth_id
  2. User opens https://auth.openai.com/codex/device and enters user_code
  3. Poll /api/accounts/deviceauth/token until 200 -> authorization_code
  4. POST /oauth/token (grant_type=authorization_code) -> access + refresh

The resulting access_token is sent as Bearer auth to
``https://chatgpt.com/backend-api/codex`` (the same endpoint Codex CLI hits),
which is OpenAI Chat Completions compatible.

NOTE on Terms of Service: OpenAI does not officially expose ChatGPT
subscription quota to third-party apps. Using this client is at your own
risk; OpenAI may change client_id / endpoints / detection at any time.

Adapted from Hermes Agent (https://github.com/NousResearch/hermes-agent),
Apache 2.0 licensed.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 15.0


# ---------------------------------------------------------------------------
# Constants — match Codex CLI exactly so OpenAI accepts the request
# ---------------------------------------------------------------------------

CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_ISSUER = "https://auth.openai.com"
CODEX_OAUTH_TOKEN_URL = f"{CODEX_OAUTH_ISSUER}/oauth/token"
DEFAULT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120

DEVICE_CODE_MAX_WAIT_SECONDS = 15 * 60  # 15 minutes


def _auth_path() -> Path:
    """Where TradingAgents stores its own Codex OAuth tokens."""
    home = os.getenv("TRADINGAGENTS_HOME", "").strip()
    base = Path(home) if home else Path.home() / ".tradingagents"
    return base / "auth" / "codex.json"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class CodexAuthError(RuntimeError):
    """Raised when Codex OAuth authentication or refresh fails."""

    def __init__(self, message: str, *, code: str = "", relogin_required: bool = False):
        super().__init__(message)
        self.code = code
        self.relogin_required = relogin_required


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _decode_jwt_claims(token: Any) -> Dict[str, Any]:
    if not isinstance(token, str) or token.count(".") != 2:
        return {}
    payload = token.split(".")[1]
    payload += "=" * ((4 - len(payload) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload.encode("utf-8"))
        claims = json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    return claims if isinstance(claims, dict) else {}


def _access_token_is_expiring(access_token: Any, skew_seconds: int) -> bool:
    """True if the JWT exp falls within `skew_seconds` of now (or has passed)."""
    claims = _decode_jwt_claims(access_token)
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return False
    return float(exp) <= (time.time() + max(0, int(skew_seconds)))


# ---------------------------------------------------------------------------
# Token store I/O
# ---------------------------------------------------------------------------

def _load_tokens() -> Dict[str, Any]:
    path = _auth_path()
    if not path.exists():
        raise CodexAuthError(
            "No Codex credentials stored. Run `python -m tradingagents.llm_clients.codex_oauth login` first.",
            code="codex_auth_missing",
            relogin_required=True,
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CodexAuthError(
            f"Failed to read {path}: {exc}",
            code="codex_auth_read_failed",
            relogin_required=True,
        )


def _save_tokens(state: Dict[str, Any]) -> None:
    path = _auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass
    tmp.replace(path)


def _import_codex_cli_tokens() -> Optional[Dict[str, str]]:
    """If the official Codex CLI is logged in on this machine, reuse its tokens."""
    codex_home = os.getenv("CODEX_HOME", "").strip()
    auth_path = Path(codex_home).expanduser() / "auth.json" if codex_home else Path.home() / ".codex" / "auth.json"
    if not auth_path.is_file():
        return None
    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        return None
    if not tokens.get("access_token") or not tokens.get("refresh_token"):
        return None
    if _access_token_is_expiring(tokens["access_token"], 0):
        return None
    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
    }


# ---------------------------------------------------------------------------
# Device-code login
# ---------------------------------------------------------------------------

def device_code_login() -> Dict[str, Any]:
    """Run the OpenAI device-code flow interactively. Saves tokens on success."""

    # Step 1 — request device code
    resp = requests.post(
        f"{CODEX_OAUTH_ISSUER}/api/accounts/deviceauth/usercode",
        json={"client_id": CODEX_OAUTH_CLIENT_ID},
        headers={"Content-Type": "application/json"},
        timeout=_REQUEST_TIMEOUT,
    )
    if resp.status_code != 200:
        raise CodexAuthError(
            f"Device code request returned status {resp.status_code}: {resp.text[:200]}",
            code="device_code_request_error",
        )
    device = resp.json()
    user_code = device.get("user_code", "")
    device_auth_id = device.get("device_auth_id", "")
    poll_interval = max(3, int(device.get("interval", "5")))
    if not user_code or not device_auth_id:
        raise CodexAuthError(
            "Device code response missing user_code or device_auth_id.",
            code="device_code_incomplete",
        )

    # Step 2 — show the user the code
    print()
    print("To sign in to ChatGPT (Codex), do these two things:")
    print()
    print(f"  1. Open this URL in any browser:  {CODEX_OAUTH_ISSUER}/codex/device")
    print(f"  2. Enter this code:               {user_code}")
    print()
    print("Waiting for sign-in (Ctrl+C to cancel)...")

    # Step 3 — poll
    code_resp = None
    deadline = time.monotonic() + DEVICE_CODE_MAX_WAIT_SECONDS
    try:
        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            poll = requests.post(
                f"{CODEX_OAUTH_ISSUER}/api/accounts/deviceauth/token",
                json={"device_auth_id": device_auth_id, "user_code": user_code},
                headers={"Content-Type": "application/json"},
                timeout=_REQUEST_TIMEOUT,
            )
            if poll.status_code == 200:
                code_resp = poll.json()
                break
            if poll.status_code in (403, 404):
                continue  # user has not finished yet
            raise CodexAuthError(
                f"Polling returned status {poll.status_code}: {poll.text[:200]}",
                code="device_code_poll_error",
            )
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)

    if code_resp is None:
        raise CodexAuthError("Login timed out after 15 minutes.", code="device_code_timeout")

    authorization_code = code_resp.get("authorization_code", "")
    code_verifier = code_resp.get("code_verifier", "")
    if not authorization_code or not code_verifier:
        raise CodexAuthError(
            "Device-auth response missing authorization_code / code_verifier.",
            code="device_code_incomplete_exchange",
        )

    # Step 4 — exchange for tokens
    redirect_uri = f"{CODEX_OAUTH_ISSUER}/deviceauth/callback"
    token_resp = requests.post(
        CODEX_OAUTH_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": redirect_uri,
            "client_id": CODEX_OAUTH_CLIENT_ID,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=_REQUEST_TIMEOUT,
    )
    if token_resp.status_code != 200:
        raise CodexAuthError(
            f"Token exchange failed ({token_resp.status_code}): {token_resp.text[:200]}",
            code="token_exchange_error",
        )
    tokens = token_resp.json()
    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    if not access_token or not refresh_token:
        raise CodexAuthError(
            "Token exchange did not return access_token + refresh_token.",
            code="token_exchange_incomplete",
        )

    state = {
        "tokens": {"access_token": access_token, "refresh_token": refresh_token},
        "last_refresh": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "auth_mode": "chatgpt",
        "source": "device-code",
    }
    _save_tokens(state)
    print()
    print(f"Saved Codex credentials to {_auth_path()}")
    return state


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------

def _refresh_tokens(refresh_token: str, *, timeout_seconds: float = 20.0) -> Dict[str, str]:
    if not refresh_token.strip():
        raise CodexAuthError(
            "Codex auth is missing refresh_token; please re-login.",
            code="codex_auth_missing_refresh_token",
            relogin_required=True,
        )

    resp = requests.post(
        CODEX_OAUTH_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CODEX_OAUTH_CLIENT_ID,
        },
        timeout=max(5.0, timeout_seconds),
    )

    if resp.status_code != 200:
        # Try to surface a useful error
        relogin = resp.status_code in (401, 403)
        body_code = ""
        body_msg = f"status {resp.status_code}"
        try:
            err = resp.json()
        except Exception:
            err = {}
        if isinstance(err, dict):
            obj = err.get("error")
            if isinstance(obj, dict):
                body_code = str(obj.get("code") or obj.get("type") or "").strip()
                body_msg = str(obj.get("message") or body_msg)
            elif isinstance(obj, str):
                body_code = obj.strip()
                body_msg = str(err.get("error_description") or err.get("message") or body_msg)
        if body_code in {"invalid_grant", "invalid_token", "invalid_request", "refresh_token_reused"}:
            relogin = True
        raise CodexAuthError(
            f"Codex token refresh failed: {body_msg}",
            code=body_code or "codex_refresh_failed",
            relogin_required=relogin,
        )

    payload = resp.json()
    new_access = payload.get("access_token", "").strip()
    if not new_access:
        raise CodexAuthError(
            "Refresh response missing access_token.",
            code="codex_refresh_missing_access_token",
            relogin_required=True,
        )
    new_refresh = payload.get("refresh_token") or refresh_token
    return {"access_token": new_access, "refresh_token": new_refresh}


# ---------------------------------------------------------------------------
# Public: resolve a usable access token
# ---------------------------------------------------------------------------

def get_access_token(*, force_refresh: bool = False) -> str:
    """Return a current Codex access token, refreshing automatically if needed."""

    # First call: try to import from Codex CLI if our own store is empty.
    path = _auth_path()
    if not path.exists():
        cli_tokens = _import_codex_cli_tokens()
        if cli_tokens:
            _save_tokens({
                "tokens": cli_tokens,
                "last_refresh": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "auth_mode": "chatgpt",
                "source": "codex-cli-import",
            })

    state = _load_tokens()
    tokens = dict(state.get("tokens") or {})
    access_token = str(tokens.get("access_token", "") or "").strip()
    refresh_token = str(tokens.get("refresh_token", "") or "").strip()

    needs_refresh = force_refresh or _access_token_is_expiring(
        access_token, ACCESS_TOKEN_REFRESH_SKEW_SECONDS
    )
    if needs_refresh:
        timeout = float(os.getenv("TRADINGAGENTS_CODEX_REFRESH_TIMEOUT", "20"))
        refreshed = _refresh_tokens(refresh_token, timeout_seconds=timeout)
        state["tokens"] = refreshed
        state["last_refresh"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _save_tokens(state)
        access_token = refreshed["access_token"]

    return access_token


def get_base_url() -> str:
    return os.getenv("TRADINGAGENTS_CODEX_BASE_URL", "").strip().rstrip("/") or DEFAULT_CODEX_BASE_URL


def logout() -> bool:
    """Delete stored Codex tokens. Returns True if anything was removed."""
    path = _auth_path()
    if path.exists():
        path.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# CLI: `python -m tradingagents.llm_clients.codex_oauth login|logout|status`
# ---------------------------------------------------------------------------

def _cli(argv: Optional[list] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    cmd = (argv[0] if argv else "login").lower()
    if cmd == "login":
        try:
            device_code_login()
        except CodexAuthError as exc:
            print(f"Login failed: {exc}", file=sys.stderr)
            return 1
        return 0
    if cmd == "logout":
        if logout():
            print(f"Removed {_auth_path()}")
        else:
            print("No Codex credentials stored.")
        return 0
    if cmd == "status":
        try:
            state = _load_tokens()
        except CodexAuthError as exc:
            print(str(exc))
            return 1
        access = (state.get("tokens") or {}).get("access_token", "")
        claims = _decode_jwt_claims(access)
        exp = claims.get("exp")
        if isinstance(exp, (int, float)):
            remaining = int(float(exp) - time.time())
            print(f"Codex auth: ok (access token expires in {remaining}s)")
        else:
            print("Codex auth: ok (no JWT exp claim)")
        print(f"  Path: {_auth_path()}")
        print(f"  Source: {state.get('source')}  Last refresh: {state.get('last_refresh')}")
        return 0
    print("Usage: python -m tradingagents.llm_clients.codex_oauth [login|logout|status]")
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_cli())
