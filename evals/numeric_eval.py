"""Numeric-correctness eval. docs/DESIGN.md section 12: validator pass rate on
generated reports. Unlike retrieval_eval.py, this needs no human-written golden set
-- "correct" here means "every number in the narrated text matches an engine value",
which `llm/validator.py` already checks mechanically against the engine's own output.

Wrapped as a DeepEval custom metric (`NumericFaithfulnessMetric`) so this check is
usable with DeepEval's own `assert_test`/`evaluate` tooling, not just this script --
deterministic and LLM-free (it calls `llm/validator.py::validate_numbers` directly),
so it scores identically under the stub or a live provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase
from sqlalchemy.ext.asyncio import AsyncSession

from evals._report_samples import generate_report_samples
from llm.provider import Provider
from llm.validator import validate_numbers
from observability import attach_score


class NumericFaithfulnessMetric(BaseMetric):  # type: ignore[no-untyped-call]
    """Does `test_case.actual_output` contain only numbers that appear in
    `test_case.metadata["allowed_values"]` (within `llm/validator.py`'s tolerance)?
    No LLM judge -- a mechanical re-check of the exact guarantee
    `llm/narrator.py::validate_and_fix`'s regenerate-then-fallback already enforces,
    expressed as a reusable DeepEval metric instead of a one-off assertion."""

    def __init__(self, threshold: float = 1.0) -> None:
        self.threshold = threshold
        self.async_mode = False
        self.score: float | None = None
        self.reason: str | None = None
        self.success: bool | None = None

    @property
    def __name__(self) -> str:
        return "Numeric Faithfulness"

    def measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        allowed = set((test_case.metadata or {}).get("allowed_values", []))
        outcome = validate_numbers(test_case.actual_output or "", allowed)
        self.score = 1.0 if outcome.passed else 0.0
        self.reason = (
            "every number matched an engine value" if outcome.passed else f"unmatched numbers: {outcome.bad_numbers}"
        )
        self.success = self.is_successful()
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        return self.measure(test_case, *args, **kwargs)


@dataclass
class NumericEvalReport:
    n_samples: int
    coach_report_pass_rate: float
    match_report_pass_rate: float
    fallback_count: int
    deepeval_coach_score: float = 0.0
    deepeval_match_score: float = 0.0


async def run_numeric_eval(
    session: AsyncSession, *, n_samples: int = 10, seed: int = 42, provider: Provider | None = None
) -> NumericEvalReport:
    samples = await generate_report_samples(session, n_samples=n_samples, seed=seed, provider=provider)
    if not samples:
        return NumericEvalReport(n_samples=0, coach_report_pass_rate=0.0, match_report_pass_rate=0.0, fallback_count=0)

    numeric_metric = NumericFaithfulnessMetric()
    coach_passes = match_passes = fallback_count = 0
    deepeval_coach_scores: list[float] = []
    deepeval_match_scores: list[float] = []

    for s in samples:
        coach_passes += int(s.coach_result.passed)
        match_passes += int(s.match_result.passed)
        fallback_count += int(s.coach_result.used_fallback) + int(s.match_result.used_fallback)

        # Independent DeepEval re-check of the FINAL shown text (post regenerate/
        # fallback) -- expected to always be 1.0, proving the fallback safety net
        # holds even on the (rare) attempts narrate_*_report itself had to discard.
        coach_case = LLMTestCase(
            input=f"coach report vs {s.opponent_name}", actual_output=s.coach_result.text,
            metadata={"allowed_values": list(s.coach_allowed_values)},
        )
        match_case = LLMTestCase(
            input=f"match report vs {s.opponent_name}", actual_output=s.match_result.text,
            metadata={"allowed_values": list(s.match_allowed_values)},
        )
        coach_score = numeric_metric.measure(coach_case)
        match_score = numeric_metric.measure(match_case)
        deepeval_coach_scores.append(coach_score)
        deepeval_match_scores.append(match_score)

        # Part 5 (docs/DESIGN.md section 14): "attach eval scores to traces when
        # evals run" -- a no-op unless Langfuse is configured (observability.py).
        attach_score(s.trace_id, "numeric_faithfulness_coach", coach_score)
        attach_score(s.trace_id, "numeric_faithfulness_match", match_score)

    n = len(samples)
    return NumericEvalReport(
        n_samples=n,
        coach_report_pass_rate=round(coach_passes / n, 3),
        match_report_pass_rate=round(match_passes / n, 3),
        fallback_count=fallback_count,
        deepeval_coach_score=round(sum(deepeval_coach_scores) / n, 3),
        deepeval_match_score=round(sum(deepeval_match_scores) / n, 3),
    )


if __name__ == "__main__":
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from db.session import get_engine

    async def _main() -> None:
        session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
        async with session_factory() as session:
            report = await run_numeric_eval(session)
        print(report)

    asyncio.run(_main())
