import os
from typing import Any, Optional, Tuple

from langchain_anthropic import ChatAnthropic

from .base_client import BaseLLMClient, normalize_content
from .claude_oauth import (
    ANTHROPIC_OAUTH_BETA_HEADER,
    ClaudeAuthError,
    get_access_token,
    is_available as credentials_login_available,
)
from .validators import validate_model

_PASSTHROUGH_KWARGS = (
    "timeout", "max_retries", "api_key", "max_tokens",
    "callbacks", "http_client", "http_async_client", "effort",
)

# Env var Hermes Agent uses for the long-lived setup token produced by
# ``claude setup-token``. Anthropic supports this token over standard
# x-api-key auth so it slots into the API-key path with no special headers.
_SETUP_TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"


class NormalizedChatAnthropic(ChatAnthropic):
    """ChatAnthropic with normalized content output.

    Claude models with extended thinking or tool use return content as a
    list of typed blocks. This normalizes to string for consistent
    downstream handling.
    """

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(input, config, **kwargs))


class _OAuthRefreshingChatAnthropic(NormalizedChatAnthropic):
    """ChatAnthropic that refreshes its OAuth Bearer token before each call.

    The short-lived access token from ``~/.claude/.credentials.json`` expires
    after about 6 hours. ``TradingAgentsGraph`` only builds its LLM once at
    init, so a long-running batch (e.g. a backtest) would hit 401 part-way
    through. Before each ``invoke`` we re-call ``get_access_token()``, which
    refreshes via the stored ``refresh_token`` if expiry is within the skew
    window. The refreshed token is rewritten into the underlying anthropic
    SDK client and the ``default_headers`` so both auth sites stay in sync.

    The setup-token / api-key paths bypass this class entirely.
    """

    def _refresh_oauth_token(self) -> None:
        try:
            new_token = get_access_token()
        except ClaudeAuthError as exc:
            raise RuntimeError(
                f"Claude OAuth refresh failed: {exc}. "
                "Re-run `claude login` or use CLAUDE_CODE_OAUTH_TOKEN (claude setup-token)."
            ) from exc

        # Update default_headers (read by anthropic SDK on every request).
        headers = dict(self.default_headers or {})
        headers["Authorization"] = f"Bearer {new_token}"
        headers["anthropic-beta"] = ANTHROPIC_OAUTH_BETA_HEADER
        self.default_headers = headers

        # Update the SDK client's api_key fallback. The Authorization header
        # we just wrote takes precedence because the beta header tells
        # Anthropic to honour Bearer auth, but keeping api_key in sync avoids
        # any surprise if langchain ever re-builds the client.
        for attr in ("_client", "_async_client"):
            sdk = getattr(self, attr, None)
            if sdk is not None and hasattr(sdk, "api_key"):
                try:
                    sdk.api_key = new_token
                except Exception:
                    pass

    def invoke(self, input, config=None, **kwargs):
        self._refresh_oauth_token()
        return super().invoke(input, config, **kwargs)

    async def ainvoke(self, input, config=None, **kwargs):
        self._refresh_oauth_token()
        return await super().ainvoke(input, config, **kwargs)


def _setup_token_from_env() -> Optional[str]:
    token = (os.getenv(_SETUP_TOKEN_ENV) or "").strip()
    return token or None


def _resolve_anthropic_auth(user_kwargs: dict) -> Tuple[str, dict]:
    """Pick the auth source and return (path_name, kwargs_to_merge).

    Precedence (highest first):
        1. Explicit ``api_key=...`` passed by the caller (per-call override).
        2. ``ANTHROPIC_API_KEY`` env var (legacy API-key path).
        3. ``CLAUDE_CODE_OAUTH_TOKEN`` env var — the long-lived setup token
           produced by ``claude setup-token``. Anthropic-officially supported
           for headless / third-party use; bills the user's subscription
           quota; sent as a regular API key (x-api-key), no beta header.
        4. ``~/.claude/.credentials.json`` — short-lived access token from
           ``claude login``, with refresh and the
           ``anthropic-beta: oauth-2025-04-20`` Bearer header.

    Override via ``TRADINGAGENTS_ANTHROPIC_AUTH``:
        - ``api_key``      => skip OAuth paths entirely
        - ``setup_token``  => use only path 3
        - ``credentials``  => use only path 4
        - ``oauth``        => alias for "setup_token then credentials"
    """
    forced = os.getenv("TRADINGAGENTS_ANTHROPIC_AUTH", "").strip().lower()

    # 1. Explicit kwarg wins unless override forces an OAuth path.
    if forced not in {"setup_token", "credentials", "oauth"}:
        if user_kwargs.get("api_key"):
            return "explicit_api_key", {}
        if forced != "credentials" and os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic_api_key_env", {}
    if forced == "api_key":
        # The user forced api_key but didn't supply one. Fall through to the
        # SDK default which will raise its own clear error.
        return "anthropic_api_key_env", {}

    # 2. Setup token (Hermes-style). No beta header, no refresh.
    if forced in {"", "setup_token", "oauth"}:
        setup = _setup_token_from_env()
        if setup:
            return "setup_token", {"api_key": setup}

    # 3. Credentials.json access token (with auto-refresh + beta header).
    if forced in {"", "credentials", "oauth"} and credentials_login_available():
        try:
            token = get_access_token()
        except ClaudeAuthError as exc:
            hint = (
                " — run `claude login` or `claude setup-token`, "
                "or set ANTHROPIC_API_KEY"
            )
            raise RuntimeError(f"Claude OAuth not ready: {exc}{hint}") from exc
        return "credentials_oauth", {
            "api_key": token,
            "default_headers": {
                "Authorization": f"Bearer {token}",
                "anthropic-beta": ANTHROPIC_OAUTH_BETA_HEADER,
            },
        }

    raise RuntimeError(
        "No Anthropic credentials found. Either:\n"
        "  - set ANTHROPIC_API_KEY (regular API key), or\n"
        "  - set CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token` (recommended for subscription billing), or\n"
        "  - run `claude login` to populate ~/.claude/.credentials.json."
    )


class AnthropicClient(BaseLLMClient):
    """Client for Anthropic Claude models.

    Three auth paths, picked automatically:

    1. **API key** — ``ANTHROPIC_API_KEY`` env var or explicit ``api_key`` kwarg.
       Standard Anthropic SDK behaviour.
    2. **Setup token** — ``CLAUDE_CODE_OAUTH_TOKEN`` env var, populated from
       ``claude setup-token``. Anthropic-supported third-party token tied to
       a Claude Pro / Max / Team subscription; long-lived, no refresh needed.
    3. **Claude Code OAuth credentials** — ``~/.claude/.credentials.json``
       written by ``claude login``. Short-lived access token, auto-refreshed,
       sent with the ``anthropic-beta: oauth-2025-04-20`` Bearer header.

    Override the precedence with ``TRADINGAGENTS_ANTHROPIC_AUTH``
    (``api_key`` / ``setup_token`` / ``credentials`` / ``oauth``).
    """

    def __init__(self, model: str, base_url: Optional[str] = None, **kwargs):
        super().__init__(model, base_url, **kwargs)

    def get_llm(self) -> Any:
        """Return configured ChatAnthropic instance."""
        self.warn_if_unknown_model()
        llm_kwargs: dict = {"model": self.model}

        if self.base_url:
            llm_kwargs["base_url"] = self.base_url

        for key in _PASSTHROUGH_KWARGS:
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        path, additions = _resolve_anthropic_auth(llm_kwargs)
        for key, value in additions.items():
            if key == "default_headers":
                merged = dict(llm_kwargs.get("default_headers") or {})
                merged.update(value)
                llm_kwargs["default_headers"] = merged
            else:
                llm_kwargs[key] = value

        # The credentials.json path uses a 6-hour access token that needs
        # transparent refreshing for long-running batches; the other paths
        # use long-lived tokens and don't need the refreshing wrapper.
        if path == "credentials_oauth":
            return _OAuthRefreshingChatAnthropic(**llm_kwargs)
        return NormalizedChatAnthropic(**llm_kwargs)

    def validate_model(self) -> bool:
        """Validate model for Anthropic."""
        return validate_model("anthropic", self.model)
