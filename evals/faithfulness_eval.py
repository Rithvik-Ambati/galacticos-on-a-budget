"""RAGAS faithfulness eval. docs/DESIGN.md section 12: does the LLM-restyled coach/
match report prose stay faithful to the exact engine-grounded facts it was given to
restyle? `evals/numeric_eval.py` already pins down the numbers mechanically
(`llm/validator.py`); this checks the broader claim -- no invented context, no
dropped caveat -- via RAGAS's `Faithfulness` metric, which itself uses an LLM judge.

Runnable with either provider (docs/DESIGN.md section 12 / CLAUDE.md: CI uses
StubProvider; live LLM runs never execute in CI):

- `StubProvider` (llm/provider.py): `.complete()` is the identity function, so the
  "restyled" text IS the engine-grounded template verbatim -- faithful by
  construction. This reports 1.0 without calling RAGAS or any LLM at all: no
  network, no cost, and nothing for CI to accidentally run live.
- a live provider (`LLM_PROVIDER=anthropic`): actually runs RAGAS's `Faithfulness`
  metric, judged by the same Anthropic provider the report itself was generated
  with (`_build_ragas_llm` below wraps `llm.provider.AnthropicProvider` in RAGAS's
  `BaseRagasLLM` interface -- no `langchain-anthropic` dependency needed for that
  one wrapper).

`ragas` is an optional dependency (`pyproject.toml`'s `eval` extra). One of its own
transitive dependencies (`scikit-network`) ships no prebuilt wheel and needs a C++
toolchain to build from source -- if it isn't installed, this reports that clearly
and returns `None` rather than crashing, the same "skip cleanly" contract every
other eval runner here follows for an empty golden set.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from evals._report_samples import generate_report_samples
from llm.provider import AnthropicProvider, Provider, StubProvider, get_provider

if TYPE_CHECKING:
    from ragas.llms import BaseRagasLLM

LIVE_BASELINE_PATH = os.path.join(os.path.dirname(__file__), "baselines", "live_faithfulness_baseline.json")


@dataclass
class FaithfulnessEvalReport:
    n_samples: int
    coach_faithfulness: float
    match_faithfulness: float
    judge: str  # "stub-by-construction" | "ragas+anthropic"


def _build_ragas_llm(provider: AnthropicProvider) -> BaseRagasLLM:
    """Minimal `ragas.llms.BaseRagasLLM` wrapping the project's own Anthropic
    provider directly -- avoids pulling in `langchain-anthropic` just for this one
    judge call. Imports RAGAS/langchain lazily so this module stays importable
    (and every other eval script keeps working) when `ragas` isn't installed."""
    from langchain_core.outputs import Generation, LLMResult
    from ragas.llms import BaseRagasLLM as _BaseRagasLLM

    class _AnthropicRagasLLM(_BaseRagasLLM):
        def generate_text(
            self, prompt: Any, n: int = 1, temperature: float = 0.01, stop: Any = None, callbacks: Any = None
        ) -> LLMResult:
            text = provider.complete(prompt.to_string())
            return LLMResult(generations=[[Generation(text=text)] for _ in range(n)])

        async def agenerate_text(
            self, prompt: Any, n: int = 1, temperature: float | None = 0.01, stop: Any = None, callbacks: Any = None
        ) -> LLMResult:
            return self.generate_text(prompt, n, temperature or 0.01, stop, callbacks)

        def is_finished(self, response: LLMResult) -> bool:
            return True

    return _AnthropicRagasLLM()


async def run_faithfulness_eval(
    session: AsyncSession, *, n_samples: int = 5, seed: int = 42, provider: Provider | None = None
) -> FaithfulnessEvalReport | None:
    provider = provider or get_provider()
    samples = await generate_report_samples(session, n_samples=n_samples, seed=seed, provider=provider)
    if not samples:
        return None

    if isinstance(provider, StubProvider):
        return FaithfulnessEvalReport(
            n_samples=len(samples), coach_faithfulness=1.0, match_faithfulness=1.0, judge="stub-by-construction"
        )

    try:
        from ragas.dataset_schema import SingleTurnSample
        from ragas.metrics import Faithfulness
    except ImportError as exc:
        print(f"ragas not installed ({exc}) -- `pip install -e .[eval]`. Skipping faithfulness eval.")
        return None

    if not isinstance(provider, AnthropicProvider):
        print(f"No RAGAS judge wired up for provider {type(provider).__name__}. Skipping faithfulness eval.")
        return None

    metric = Faithfulness(llm=_build_ragas_llm(provider))
    coach_scores: list[float] = []
    match_scores: list[float] = []
    for s in samples:
        coach_scores.append(
            await metric.single_turn_ascore(
                SingleTurnSample(
                    user_input=f"Give a tactical debrief vs {s.opponent_name}.",
                    response=s.coach_result.text,
                    retrieved_contexts=[s.coach_template],
                )
            )
        )
        match_scores.append(
            await metric.single_turn_ascore(
                SingleTurnSample(
                    user_input=f"Give a match report vs {s.opponent_name}.",
                    response=s.match_result.text,
                    retrieved_contexts=[s.match_template],
                )
            )
        )

    return FaithfulnessEvalReport(
        n_samples=len(samples),
        coach_faithfulness=round(sum(coach_scores) / len(coach_scores), 3),
        match_faithfulness=round(sum(match_scores) / len(match_scores), 3),
        judge="ragas+anthropic",
    )


if __name__ == "__main__":
    import asyncio
    import json

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from db.session import get_engine

    async def _main() -> None:
        session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
        async with session_factory() as session:
            report = await run_faithfulness_eval(session)

        if report is None:
            print("No samples (empty DB) -- skipping.")
            return

        print(report)
        if report.judge == "ragas+anthropic":
            # Nightly CI has no secret to call a live LLM with, so its faithfulness
            # gate (.github/workflows/nightly-eval.yml) checks this committed,
            # human-produced record instead of running RAGAS itself -- "activates
            # only when a live-run baseline exists" (docs/PROGRESS.md Part 4).
            # Commit this file deliberately (it's git-tracked, unlike evals/reports/)
            # once you're satisfied with the score it records.
            os.makedirs(os.path.dirname(LIVE_BASELINE_PATH), exist_ok=True)
            with open(LIVE_BASELINE_PATH, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "coach_faithfulness": report.coach_faithfulness,
                        "match_faithfulness": report.match_faithfulness,
                        "n_samples": report.n_samples,
                    },
                    f,
                    indent=2,
                )
            print(f"Live faithfulness baseline written to {LIVE_BASELINE_PATH} -- commit it by hand if you want it.")

    asyncio.run(_main())
