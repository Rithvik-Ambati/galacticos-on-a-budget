"""LLM provider interface. docs/DESIGN.md section 9 + CLAUDE.md rule 1: the LLM only
ever polishes prose that already has every number filled in by code -- it is never
asked to produce a number itself, on any provider.
"""

from __future__ import annotations

from typing import Protocol

from config.settings import get_settings


class Provider(Protocol):
    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 600) -> str: ...


class StubProvider:
    """Deterministic, no network, no API key. The prompt it receives from llm/narrator.py
    is already complete, numbers-filled prose (a template rendered with engine output) --
    this provider's "generation" is the identity function, which is a legitimate,
    testable implementation of "narrate this", not a placeholder standing in for one
    (docs/DECISIONS.md). Swapping LLM_PROVIDER=anthropic in .env is what makes a real
    model restyle the same prose instead.
    """

    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 600) -> str:
        return prompt


class AnthropicProvider:
    """Real provider. Only constructed when LLM_PROVIDER=anthropic and an API key is
    set; never imports/initialises the SDK otherwise."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-5") -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 600) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text")


def get_provider() -> Provider:
    settings = get_settings()
    if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
        return AnthropicProvider(settings.anthropic_api_key)
    return StubProvider()
