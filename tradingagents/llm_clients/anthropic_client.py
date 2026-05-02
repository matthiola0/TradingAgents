import os
from typing import Any, Optional, Tuple

import anthropic
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

_SETUP_TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"


class NormalizedChatAnthropic(ChatAnthropic):
    """ChatAnthropic with normalized content output.

    Claude models with extended thinking or tool use return content as a
    list of typed blocks. This normalizes to string for consistent
    downstream handling.
    """

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(input, config, **kwargs))


def _build_oauth_sdk_clients(
    token: str, base_url: Optional[str] = None
) -> Tuple[anthropic.Anthropic, anthropic.AsyncAnthropic]:
    """Build anthropic SDK clients that authenticate via OAuth Bearer.

    ``auth_token=`` makes the SDK send ``Authorization: Bearer <token>``
    instead of ``x-api-key``. The ``anthropic-beta: oauth-2025-04-20``
    header in default_headers is required to enable subscription-quota
    billing on every request, including those made through wrappers like
    ``ChatAnthropic.with_structured_output`` that rebuild bindings around
    the same underlying SDK client.
    """
    kwargs: dict = {
        "auth_token": token,
        "default_headers": {"anthropic-beta": ANTHROPIC_OAUTH_BETA_HEADER},
    }
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs), anthropic.AsyncAnthropic(**kwargs)


def _attach_oauth_clients(
    chat: ChatAnthropic, token: str, base_url: Optional[str] = None
) -> None:
    """Replace the SDK clients on a ChatAnthropic so all calls use Bearer auth.

    This is the single point where OAuth auth is anchored. Because every
    ``ChatAnthropic`` call (including ones routed through
    ``with_structured_output`` / ``bind_tools`` / streaming) ultimately
    delegates to ``self._client`` / ``self._async_client``, replacing
    those SDK instances guarantees the OAuth header survives every wrapper
    langchain might build on top.
    """
    sync_client, async_client = _build_oauth_sdk_clients(token, base_url)
    # Use object.__setattr__ to bypass any pydantic validation that may
    # disallow direct assignment to private attrs on Pydantic v2 models.
    object.__setattr__(chat, "_client", sync_client)
    object.__setattr__(chat, "_async_client", async_client)


class _OAuthRefreshingChatAnthropic(NormalizedChatAnthropic):
    """ChatAnthropic that refreshes its OAuth Bearer token before each call.

    The short-lived access token from ``~/.claude/.credentials.json`` expires
    after about 6 hours. Before each ``invoke`` we re-call
    ``get_access_token()``, which refreshes via the stored ``refresh_token``
    if expiry is within the skew window, and rebuilds the underlying
    anthropic SDK clients with the new token.

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
        _attach_oauth_clients(self, new_token, getattr(self, "anthropic_api_url", None))

    def invoke(self, input, config=None, **kwargs):
        self._refresh_oauth_token()
        return super().invoke(input, config, **kwargs)

    async def ainvoke(self, input, config=None, **kwargs):
        self._refresh_oauth_token()
        return await super().ainvoke(input, config, **kwargs)


def _setup_token_from_env() -> Optional[str]:
    token = (os.getenv(_SETUP_TOKEN_ENV) or "").strip()
    return token or None


def _resolve_anthropic_auth(user_kwargs: dict) -> Tuple[str, Optional[str]]:
    """Pick the auth source. Returns (path_name, oauth_token_or_None).

    For OAuth paths (``setup_token`` and ``credentials_oauth``) the token is
    returned so the caller can install Bearer-auth SDK clients post-init.
    For API-key paths the token is None — the standard ChatAnthropic
    construction handles auth.

    Precedence (highest first):
        1. Explicit ``api_key=...`` passed by the caller (per-call override).
        2. ``ANTHROPIC_API_KEY`` env var (legacy API-key path).
        3. ``CLAUDE_CODE_OAUTH_TOKEN`` env var — long-lived setup token from
           ``claude setup-token``. Bearer auth, no refresh.
        4. ``~/.claude/.credentials.json`` — short-lived access token from
           ``claude login``. Bearer auth, auto-refreshed before each call.

    Override via ``TRADINGAGENTS_ANTHROPIC_AUTH``: ``api_key`` /
    ``setup_token`` / ``credentials`` / ``oauth`` (= setup_token then credentials).
    """
    forced = os.getenv("TRADINGAGENTS_ANTHROPIC_AUTH", "").strip().lower()

    if forced not in {"setup_token", "credentials", "oauth"}:
        if user_kwargs.get("api_key"):
            return "explicit_api_key", None
        if forced != "credentials" and os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic_api_key_env", None
    if forced == "api_key":
        return "anthropic_api_key_env", None

    if forced in {"", "setup_token", "oauth"}:
        setup = _setup_token_from_env()
        if setup:
            return "setup_token", setup

    if forced in {"", "credentials", "oauth"} and credentials_login_available():
        try:
            token = get_access_token()
        except ClaudeAuthError as exc:
            hint = (
                " — run `claude login` or `claude setup-token`, "
                "or set ANTHROPIC_API_KEY"
            )
            raise RuntimeError(f"Claude OAuth not ready: {exc}{hint}") from exc
        return "credentials_oauth", token

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
       Standard Anthropic SDK behaviour (x-api-key header).
    2. **Setup token** — ``CLAUDE_CODE_OAUTH_TOKEN`` env var, populated from
       ``claude setup-token``. OAuth Bearer auth, no refresh, bills against
       the user's Claude Pro / Max / Team subscription quota.
    3. **Claude Code OAuth credentials** — ``~/.claude/.credentials.json``
       written by ``claude login``. Short-lived access token, auto-refreshed
       before each call. Same Bearer auth as path 2.

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

        path, oauth_token = _resolve_anthropic_auth(llm_kwargs)

        if oauth_token is not None:
            # The api_key field is required for ChatAnthropic validation but
            # is never used on the wire — _attach_oauth_clients overrides
            # the SDK clients to use auth_token (Bearer) instead.
            llm_kwargs.setdefault("api_key", "oauth-bearer-managed-by-tradingagents")
            cls = (
                _OAuthRefreshingChatAnthropic
                if path == "credentials_oauth"
                else NormalizedChatAnthropic
            )
            chat = cls(**llm_kwargs)
            _attach_oauth_clients(chat, oauth_token, self.base_url)
            return chat

        return NormalizedChatAnthropic(**llm_kwargs)

    def validate_model(self) -> bool:
        """Validate model for Anthropic."""
        return validate_model("anthropic", self.model)
