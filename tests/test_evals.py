from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# DATA_SOURCE now defaults to "real" (docs/DECISIONS.md "Synthetic data is no longer
# the silent default") -- tests opt into synthetic explicitly so they don't need
# data_raw/ in CI.
os.environ["DATA_SOURCE"] = "synthetic"

from evals.faithfulness_eval import run_faithfulness_eval
from evals.live_llm_test import run_live_llm_test
from evals.numeric_eval import NumericFaithfulnessMetric, run_numeric_eval
from evals.retrieval_eval import GoldenQuery, load_golden, render_ablation_table, run_retrieval_eval
from llm.provider import StubProvider
from pipeline.features import compute_features
from pipeline.ingest import run_ingest
from pipeline.pricing import compute_prices
from pipeline.team_profiles import compute_team_profiles

SEED = 42


async def _seeded_engine(tmp_path):
    db_path = tmp_path / "evals_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    await run_ingest(engine, seed=SEED, output_dir=str(tmp_path))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await compute_features(session)
    async with session_factory() as session:
        await compute_prices(session, seed=SEED)
    async with session_factory() as session:
        await compute_team_profiles(session)
    return engine


def test_load_golden_returns_empty_list_for_missing_file() -> None:
    assert load_golden("does/not/exist.jsonl") == []


def test_load_golden_skips_is_example_rows(tmp_path) -> None:
    path = tmp_path / "retrieval_queries.jsonl"
    path.write_text(
        '{"is_example": true, "query": "demo", "relevant_doc_ids": ["x"]}\n'
        '{"query": "real one", "relevant_doc_ids": ["y"]}\n',
        encoding="utf-8",
    )
    golden = load_golden(str(path))
    assert len(golden) == 1
    assert golden[0].query == "real one"


def test_numeric_faithfulness_metric_passes_when_numbers_match() -> None:
    from deepeval.test_case import LLMTestCase

    metric = NumericFaithfulnessMetric()
    case = LLMTestCase(input="x", actual_output="Rated 91.2 overall.", metadata={"allowed_values": [91.2]})
    assert metric.measure(case) == 1.0
    assert metric.success is True


def test_numeric_faithfulness_metric_fails_on_an_unmatched_number() -> None:
    from deepeval.test_case import LLMTestCase

    metric = NumericFaithfulnessMetric()
    case = LLMTestCase(input="x", actual_output="Rated 77.0 overall.", metadata={"allowed_values": [91.2]})
    assert metric.measure(case) == 0.0
    assert metric.success is False


async def test_numeric_eval_runs_and_passes_with_stub_provider(tmp_path) -> None:
    engine = await _seeded_engine(tmp_path)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        report = await run_numeric_eval(session, n_samples=3, seed=SEED, provider=StubProvider())

    assert report.n_samples > 0
    assert report.coach_report_pass_rate == 1.0
    assert report.match_report_pass_rate == 1.0
    assert report.fallback_count == 0
    assert report.deepeval_coach_score == 1.0
    assert report.deepeval_match_score == 1.0
    await engine.dispose()


async def test_retrieval_eval_bm25_only_without_embedder(tmp_path) -> None:
    engine = await _seeded_engine(tmp_path)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    from pipeline.documents import build_opponent_documents, build_player_documents

    async with session_factory() as session:
        await build_player_documents(session, "none", None)
    async with session_factory() as session:
        await build_opponent_documents(session, "none", None)

    from sqlalchemy import select

    from db.models import Document

    async with session_factory() as session:
        some_doc = (await session.execute(select(Document).limit(1))).scalar_one()

    golden = [GoldenQuery(query=some_doc.text[:30], relevant_doc_ids={some_doc.doc_id})]

    async with session_factory() as session:
        report = await run_retrieval_eval(session, golden, embedder=None, reranker=None)

    assert "bm25" in report.by_method
    assert "dense" not in report.by_method  # no embedder given
    assert report.by_method["bm25"].n_queries == 1
    await engine.dispose()


def test_render_ablation_table_marks_the_best_method_bold() -> None:
    from evals.retrieval_eval import MethodMetrics, RetrievalEvalReport

    report = RetrievalEvalReport(
        by_method={
            "bm25": MethodMetrics(recall_at_10=0.5, mrr=0.5, ndcg_at_10=0.5, n_queries=3),
            "hybrid_rerank": MethodMetrics(recall_at_10=0.9, mrr=0.9, ndcg_at_10=0.9, n_queries=3),
        },
        best_method="hybrid_rerank",
    )
    table = render_ablation_table(report)
    assert "**0.9000**" in table
    assert "0.5000" in table


def test_render_ablation_table_handles_no_methods() -> None:
    from evals.retrieval_eval import RetrievalEvalReport

    assert "No retrieval methods" in render_ablation_table(RetrievalEvalReport())


async def test_faithfulness_eval_is_1_by_construction_under_stub(tmp_path) -> None:
    engine = await _seeded_engine(tmp_path)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        report = await run_faithfulness_eval(session, n_samples=2, seed=SEED, provider=StubProvider())

    assert report is not None
    assert report.judge == "stub-by-construction"
    assert report.coach_faithfulness == 1.0
    assert report.match_faithfulness == 1.0
    await engine.dispose()


async def test_live_llm_test_skips_cleanly_without_a_live_provider(tmp_path) -> None:
    engine = await _seeded_engine(tmp_path)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await run_live_llm_test(session)

    assert result is None  # default settings: llm_provider="stub", no API key
    await engine.dispose()


async def test_embedding_benchmark_skips_cleanly_with_empty_golden_set(tmp_path) -> None:
    # No network/model download needed for this path -- same "empty golden set"
    # skip contract every other eval runner follows (evals/golden/README.md).
    from evals.embedding_benchmark import run_embedding_benchmark

    engine = await _seeded_engine(tmp_path)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        report = await run_embedding_benchmark(session, golden=[])

    assert report.by_model == {}
    assert report.best_model is None
    await engine.dispose()


def test_embedding_benchmark_tables_render_without_models() -> None:
    from evals.embedding_benchmark import EmbeddingBenchmarkReport, render_accuracy_table, render_latency_table

    empty = EmbeddingBenchmarkReport()
    assert "No embedding models" in render_accuracy_table(empty)
    assert "No embedding models" in render_latency_table(empty)


def test_load_previous_recall_returns_none_without_a_committed_baseline(tmp_path, monkeypatch) -> None:
    import evals.run_all as run_all

    monkeypatch.setattr(run_all, "BASELINE_PATH", str(tmp_path / "does_not_exist.json"))
    assert run_all._load_previous_recall("hybrid_rerank") is None
    assert run_all._load_previous_recall(None) is None


def test_load_previous_recall_reads_the_committed_baseline(tmp_path, monkeypatch) -> None:
    import json

    import evals.run_all as run_all

    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps({"retrieval": {"hybrid_rerank": {"recall_at_10": 0.73}}, "retrieval_best_method": "hybrid_rerank"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(run_all, "BASELINE_PATH", str(path))
    assert run_all._load_previous_recall("hybrid_rerank") == 0.73
    assert run_all._load_previous_recall("bm25") is None  # not the method that was baselined
