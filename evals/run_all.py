"""`make eval`. docs/DESIGN.md section 12: run the eval subset, store results in
eval_runs and a baseline JSON in the repo; nightly-eval.yml runs the full suite.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from dataclasses import asdict

from sqlalchemy.ext.asyncio import async_sessionmaker

from db.models import EvalRun
from db.session import get_engine
from evals.faithfulness_eval import run_faithfulness_eval
from evals.numeric_eval import run_numeric_eval
from evals.retrieval_eval import load_golden, render_ablation_table, run_retrieval_eval

BASELINE_PATH = os.path.join(os.path.dirname(__file__), "baselines", "baseline.json")

# docs/DESIGN.md section 12's CI gate thresholds.
NUMERIC_PASS_THRESHOLD = 1.0  # 100% after the validator's own regenerate+fallback
RECALL_DROP_THRESHOLD = 0.02  # fail if Recall@10 drops > 2 points vs the repo baseline


def _load_previous_recall(best_method: str | None) -> float | None:
    """The committed baseline's Recall@10 for `best_method`, or None if there is
    no committed baseline yet or it never ran a retrieval eval (e.g. the golden
    set was empty then too) -- either way, nothing to regress against."""
    if best_method is None or not os.path.exists(BASELINE_PATH):
        return None
    with open(BASELINE_PATH, encoding="utf-8") as f:
        previous = json.load(f)
    method_metrics = previous.get("retrieval", {}).get(best_method)
    return method_metrics.get("recall_at_10") if method_metrics else None


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=os.path.dirname(__file__)).decode().strip()
    except Exception:
        return "unknown"


async def main() -> None:
    engine = get_engine()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        numeric_report = await run_numeric_eval(session, n_samples=10)
    print(f"Numeric eval: {numeric_report}")

    golden = load_golden()
    retrieval_report = None
    if golden:
        try:
            from rag.embeddings import get_embedder
            from rag.rerank import get_reranker

            embedder = get_embedder()
            reranker = get_reranker()
        except Exception as exc:  # pragma: no cover - environment-dependent
            print(f"Embedding/reranker models unavailable ({exc}); running BM25-only ablation.")
            embedder, reranker = None, None
        async with session_factory() as session:
            retrieval_report = await run_retrieval_eval(session, golden, embedder=embedder, reranker=reranker)
        print(f"Retrieval eval ({len(golden)} queries):\n{render_ablation_table(retrieval_report)}")
    else:
        print(
            f"No golden set at evals/golden/retrieval_queries.jsonl ({len(golden)} queries) -- "
            "skipping retrieval eval."
        )

    async with session_factory() as session:
        faithfulness_report = await run_faithfulness_eval(session)
    print(f"Faithfulness eval: {faithfulness_report if faithfulness_report is not None else 'skipped (see above)'}")

    passed = numeric_report.coach_report_pass_rate >= NUMERIC_PASS_THRESHOLD and (
        numeric_report.match_report_pass_rate >= NUMERIC_PASS_THRESHOLD
    )

    metrics: dict[str, object] = {"numeric": asdict(numeric_report)}
    if retrieval_report is not None:
        metrics["retrieval"] = {
            method: asdict(m) for method, m in retrieval_report.by_method.items()
        }
        best_method = retrieval_report.best_method
        metrics["retrieval_best_method"] = best_method

        previous_recall = _load_previous_recall(best_method)
        new_recall = retrieval_report.by_method[best_method].recall_at_10 if best_method else None
        if previous_recall is not None and new_recall is not None and new_recall < previous_recall - RECALL_DROP_THRESHOLD:
            print(
                f"Recall@10 regression: {previous_recall:.4f} -> {new_recall:.4f} "
                f"(method {retrieval_report.best_method!r}, threshold {RECALL_DROP_THRESHOLD})."
            )
            passed = False
    if faithfulness_report is not None:
        metrics["faithfulness"] = asdict(faithfulness_report)

    os.makedirs(os.path.dirname(BASELINE_PATH), exist_ok=True)
    with open(BASELINE_PATH, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    async with session_factory() as session:
        session.add(EvalRun(git_sha=_git_sha(), metrics=metrics, passed=passed))
        await session.commit()

    print(f"\nOverall: {'PASS' if passed else 'FAIL'}. Baseline written to {BASELINE_PATH}.")
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
