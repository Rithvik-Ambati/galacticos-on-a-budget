"""Real Anthropic call, run by hand. docs/DESIGN.md section 12 / CLAUDE.md: live LLM
runs never execute in CI or by default -- `make eval`/`run_all.py` never import this
module, and this function itself refuses to do anything unless `LLM_PROVIDER=anthropic`
and `ANTHROPIC_API_KEY` are both actually set in `.env`. The key itself is never
logged or printed -- only its presence is checked.

Builds one real lineup against one real opponent and narrates both the coach report
and the match report through the live model, then re-checks both with
`llm/validator.py` exactly as production does -- so this is also the one place that
actually exercises `narrate_and_fix`'s regenerate-then-fallback path against a real
model's real failure modes, not just the deterministic StubProvider.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from evals._report_samples import generate_report_samples
from llm.provider import AnthropicProvider, get_provider


async def run_live_llm_test(session: AsyncSession) -> bool | None:
    """Returns None if skipped (no live provider configured, or nothing to sample),
    True if it ran and the narrated text passed the numeric validator outright,
    False if it ran but had to fall back (worth a human look, not a crash). Never
    raises on a missing key or wrong provider -- that's the skip path."""
    settings = get_settings()
    if settings.llm_provider != "anthropic" or not settings.anthropic_api_key:
        print(
            "LLM_PROVIDER is not 'anthropic' (or ANTHROPIC_API_KEY is unset) -- "
            "skipping the live LLM test. Set both in .env to run it for real."
        )
        return None

    provider = get_provider()
    if not isinstance(provider, AnthropicProvider):
        print(f"get_provider() returned {type(provider).__name__}, not AnthropicProvider -- skipping.")
        return None

    samples = await generate_report_samples(session, n_samples=1, provider=provider)
    if not samples:
        print("No teams available to build a sample lineup against -- skipping.")
        return None

    sample = samples[0]
    print(f"=== Live coach report vs {sample.opponent_name} ===\n{sample.coach_result.text}\n")
    print(f"=== Live match report vs {sample.opponent_name} ===\n{sample.match_result.text}\n")
    print(
        f"Numeric validator: coach {'PASS' if sample.coach_result.passed else 'FALLBACK USED'}, "
        f"match {'PASS' if sample.match_result.passed else 'FALLBACK USED'}"
    )
    return not (sample.coach_result.used_fallback or sample.match_result.used_fallback)


if __name__ == "__main__":
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from db.session import get_engine

    async def _main() -> None:
        session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
        async with session_factory() as session:
            ok = await run_live_llm_test(session)
        raise SystemExit(1 if ok is False else 0)

    asyncio.run(_main())
