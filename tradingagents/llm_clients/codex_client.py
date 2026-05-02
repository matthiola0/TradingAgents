"""LangChain client backed by ChatGPT (Codex) OAuth.

Hits ``https://chatgpt.com/backend-api/codex`` with a ChatGPT-account
access token instead of an OpenAI API key, so users with a paid ChatGPT
subscription can drive TradingAgents without API credit.

The endpoint is OpenAI Chat Completions compatible at the wire level, so we
reuse ``ChatOpenAI`` and just supply the OAuth access token in place of the
API key. Tokens are refreshed transparently before each ``get_llm()`` call.
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_openai import ChatOpenAI

from .base_client import BaseLLMClient, normalize_content
from .codex_oauth import CodexAuthError, get_access_token, get_base_url


class _CodexChatOpenAI(ChatOpenAI):
    """ChatOpenAI variant that normalises content output for downstream agents."""

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(input, config, **kwargs))

    def with_structured_output(self, schema, *, method=None, **kwargs):
        # function_calling is the most portable path; the Responses API
        # parse path is OpenAI-specific and may not be available behind
        # the ChatGPT backend.
        if method is None:
            method = "function_calling"
        return super().with_structured_output(schema, method=method, **kwargs)


_PASSTHROUGH_KWARGS = (
    "timeout", "max_retries", "reasoning_effort",
    "callbacks", "http_client", "http_async_client",
)


class CodexOAuthClient(BaseLLMClient):
    """LLM client that authenticates with a ChatGPT (Codex) OAuth token.

    Login once with::

        python -m tradingagents.llm_clients.codex_oauth login

    Then use::

        config["llm_provider"] = "codex"
        config["deep_think_llm"] = "gpt-5.4"
        config["quick_think_llm"] = "gpt-5.4-mini"
    """

    def __init__(self, model: str, base_url: Optional[str] = None, **kwargs):
        super().__init__(model, base_url, **kwargs)
        self.provider = "codex"

    def get_llm(self) -> Any:
        try:
            access_token = get_access_token()
        except CodexAuthError as exc:
            hint = "" if not exc.relogin_required else (
                "\nRun: python -m tradingagents.llm_clients.codex_oauth login"
            )
            raise RuntimeError(f"Codex OAuth not ready: {exc}{hint}") from exc

        llm_kwargs: dict = {
            "model": self.model,
            "api_key": access_token,
            "base_url": self.base_url or get_base_url(),
        }
        for key in _PASSTHROUGH_KWARGS:
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        return _CodexChatOpenAI(**llm_kwargs)

    def validate_model(self) -> bool:
        # We don't maintain an authoritative list of models reachable through
        # the ChatGPT Codex backend (it shifts as OpenAI ships releases), so
        # just accept whatever the user configured.
        return True
