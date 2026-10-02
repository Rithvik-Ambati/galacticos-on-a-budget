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
from evals.numeric_eval import run_numeric_eval
from evals.retrieval_eval import load_golden, run_retrieval_eval

BASELINE_PATH = os.path.join(os.path.dirname(__file__), "reports", "baseline.json")

# docs/DESIGN.md section 12's CI gate thresholds.
NUMERIC_PASS_THRESHOLD = 1.0  # 100% after the validator's own regenerate+fallback
RECALL_DROP_THRESHOLD = 0.02  # fail if Recall@10 drops > 2 points vs the repo baseline


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
        print(f"Retrieval eval ({len(golden)} queries): {retrieval_report}")
    else:
        print(f"No golden set at evals/golden/retrieval.jsonl ({len(golden)} queries) -- skipping retrieval eval.")

    passed = numeric_report.coach_report_pass_rate >= NUMERIC_PASS_THRESHOLD and (
        numeric_report.match_report_pass_rate >= NUMERIC_PASS_THRESHOLD
    )

    metrics: dict[str, object] = {"numeric": asdict(numeric_report)}
    if retrieval_report is not None:
        metrics["retrieval"] = {
            method: asdict(m) for method, m in retrieval_report.by_method.items()
        }
        metrics["retrieval_best_method"] = retrieval_report.best_method

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
