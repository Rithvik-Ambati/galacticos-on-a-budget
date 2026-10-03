"""pipeline/train_rating_v2.py's pure helper functions -- _v1_proxy_overall,
_fit_calibration, _brier_score -- and run_backtest()'s "not enough real data"
skip path. The actual XGBoost training + SHAP + full backtest needs real
historical match data (~8600 usable examples measured against data_raw/ in this
session, docs/PROGRESS.md Part 6) and is not run in CI.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine

from db.models import Base
from pipeline.train_rating_v2 import _brier_score, _fit_calibration, _v1_proxy_overall, run_backtest


def test_v1_proxy_overall_averages_each_zone_line() -> None:
    # (def-left, def-center, def-right, mid-left, mid-center, mid-right,
    # att-left, att-center, att-right) -- all defence=60, all midfield=70, all attack=80
    features = (60.0, 60.0, 60.0, 70.0, 70.0, 70.0, 80.0, 80.0, 80.0)
    overall = _v1_proxy_overall(features)
    # weights renormalized but all 3 lines are uniform here, so this is just
    # a weighted average of 60/70/80 -- strictly between the min and max.
    assert 60.0 < overall < 80.0


def test_fit_calibration_separates_winners_from_losers() -> None:
    # Large positive margins paired with wins, large negative margins with
    # losses -- a logistic fit should give positive margins a high win
    # probability and negative margins a low one.
    margins = [5.0, 4.0, 3.0, -3.0, -4.0, -5.0]
    results = [1, 1, 1, -1, -1, -1]
    calibration = _fit_calibration(margins, results)
    assert calibration.win_probability(5.0) > 0.7
    assert calibration.win_probability(-5.0) < 0.3


def test_brier_score_is_zero_for_perfect_predictions() -> None:
    assert _brier_score([1.0, 0.0], [1, -1]) == 0.0


def test_brier_score_is_one_for_perfectly_wrong_predictions() -> None:
    assert _brier_score([0.0, 1.0], [1, -1]) == 1.0


async def test_run_backtest_returns_none_without_enough_real_data(tmp_path, monkeypatch) -> None:
    import pipeline.train_rating_v2 as train_mod

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ratingv2.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(train_mod, "get_engine", lambda: engine)

    report = await run_backtest()
    assert report is None
    await engine.dispose()
