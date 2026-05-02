import os
from typing import Any, Optional

from langchain_anthropic import ChatAnthropic

from .base_client import BaseLLMClient, normalize_content
from .claude_oauth import (
    ANTHROPIC_OAUTH_BETA_HEADER,
    ClaudeAuthError,
    get_access_token,
    is_available as oauth_is_available,
)
from .validators import validate_model

_PASSTHROUGH_KWARGS = (
    "timeout", "max_retries", "api_key", "max_tokens",
    "callbacks", "http_client", "http_async_client", "effort",
)


class NormalizedChatAnthropic(ChatAnthropic):
    """ChatAnthropic with normalized content output.

    Claude models with extended thinking or tool use return content as a
    list of typed blocks. This normalizes to string for consistent
    downstream handling.
    """

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(input, config, **kwargs))


def _should_use_oauth(user_kwargs: dict) -> bool:
    """OAuth wins when:
    - the user did not pass an explicit api_key,
    - ANTHROPIC_API_KEY env var is empty,
    - and a Claude Code OAuth token is available locally.

    Set TRADINGAGENTS_ANTHROPIC_AUTH=api_key to force the legacy path.
    """
    forced = os.getenv("TRADINGAGENTS_ANTHROPIC_AUTH", "").strip().lower()
    if forced == "api_key":
        return False
    if forced == "oauth":
        return True
    if "api_key" in user_kwargs and user_kwargs["api_key"]:
        return False
    if os.getenv("ANTHROPIC_API_KEY"):
        return False
    return oauth_is_available()


class AnthropicClient(BaseLLMClient):
    """Client for Anthropic Claude models.

    Supports two auth paths:
    1. **OAuth (Claude Pro / Max subscription)** — when a Claude Code login
       exists at ``~/.claude/.credentials.json`` (or ``CLAUDE_CODE_OAUTH_TOKEN``
       is set), drives ``api.anthropic.com`` with the user's subscription
       quota. Triggered automatically when no API key is configured.
    2. **API key** — the existing path; uses ``ANTHROPIC_API_KEY`` and bills
       to the API account.
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

        if _should_use_oauth(llm_kwargs):
            try:
                oauth_token = get_access_token()
            except ClaudeAuthError as exc:
                hint = (
                    "Run `claude login` (or set ANTHROPIC_API_KEY)."
                    if exc.relogin_required else ""
                )
                raise RuntimeError(f"Claude OAuth not ready: {exc} {hint}".strip()) from exc

            # The anthropic SDK accepts ``auth_token`` for OAuth Bearer auth;
            # langchain-anthropic exposes it via the ``api_key`` slot when the
            # ``anthropic-beta: oauth-2025-04-20`` header is also set, because
            # the API checks Authorization: Bearer first when that beta header
            # is present.
            llm_kwargs["api_key"] = oauth_token
            existing_headers = llm_kwargs.get("default_headers") or {}
            llm_kwargs["default_headers"] = {
                **existing_headers,
                "Authorization": f"Bearer {oauth_token}",
                "anthropic-beta": ANTHROPIC_OAUTH_BETA_HEADER,
            }

        return NormalizedChatAnthropic(**llm_kwargs)

    def validate_model(self) -> bool:
        """Validate model for Anthropic."""
        return validate_model("anthropic", self.model)
