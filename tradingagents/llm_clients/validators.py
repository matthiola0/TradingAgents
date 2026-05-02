"""Model name validators for each provider."""

import re

from .model_catalog import get_known_models


VALID_MODELS = {
    provider: models
    for provider, models in get_known_models().items()
    if provider not in ("ollama", "openrouter")
}

# Anthropic publishes both unpinned (claude-haiku-4-5) and snapshot-pinned
# (claude-haiku-4-5-20251001) variants of the same model. Strip the trailing
# YYYYMMDD before validating so dated names match the catalog.
_ANTHROPIC_DATE_SUFFIX = re.compile(r"-\d{8}$")


def validate_model(provider: str, model: str) -> bool:
    """Check if model name is valid for the given provider.

    For ollama, openrouter - any model is accepted.
    """
    provider_lower = provider.lower()

    if provider_lower in ("ollama", "openrouter"):
        return True

    if provider_lower not in VALID_MODELS:
        return True

    if model in VALID_MODELS[provider_lower]:
        return True

    if provider_lower == "anthropic":
        unpinned = _ANTHROPIC_DATE_SUFFIX.sub("", model)
        if unpinned != model and unpinned in VALID_MODELS[provider_lower]:
            return True

    return False
