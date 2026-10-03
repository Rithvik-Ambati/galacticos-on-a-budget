"""`make train-rating-v2`: trains `engine/rating_v2.py::RatingV2`'s XGBoost
margin regressor on real historical matches, calibrates it, computes SHAP
feature importances, backtests it against v1, and writes the comparison --
either way (docs/DESIGN.md: "swap in through the RatingModel interface only if
it beats v1; otherwise keep v1 and write comparison to evals/reports/"). The
trained model is never persisted to disk; re-running this script is how you
reproduce it (same real data, same `SEED` -> the same model).
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
from dataclasses import asdict, dataclass

import numpy as np
from sklearn.linear_model import LogisticRegression
from sqlalchemy.ext.asyncio import async_sessionmaker
from xgboost import XGBRegressor

from config.game import RATING_WEIGHTS
from db.session import get_engine
from engine.rating_v2 import ZONES, Calibration
from pipeline.rating_v2_dataset import build_training_examples

SEED = 42
TEST_FRACTION = 0.2
MIN_USABLE_EXAMPLES = 50
REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "evals", "reports", "rating_v2_backtest.json")

# v1's own weighted-sub-rating formula (engine/rating.py::RatingV1), restricted
# to the 3 sub-ratings computable from zone-average data alone -- matchup,
# cohesion and balance all need live-lineup context (opponent threat map,
# role_fit) that historical match results don't carry -- re-normalized so the
# 3 remaining weights sum to 1, keeping the proxy on the same 0-100 scale.
_V1_PROXY_WEIGHTS = {
    "attack": RATING_WEIGHTS["attack"],
    "midfield_control": RATING_WEIGHTS["midfield_control"],
    "defence": RATING_WEIGHTS["defence"],
}
_V1_PROXY_TOTAL = sum(_V1_PROXY_WEIGHTS.values())

FEATURE_NAMES = [f"home_{v}_{h}" for v, h in ZONES] + [f"away_{v}_{h}" for v, h in ZONES]


def _v1_proxy_overall(features: tuple[float, ...]) -> float:
    """features: (def-left, def-center, def-right, mid-left, mid-center,
    mid-right, att-left, att-center, att-right) -- pipeline/rating_v2_dataset.py's
    ZONES order."""
    defence = sum(features[0:3]) / 3
    midfield = sum(features[3:6]) / 3
    attack = sum(features[6:9]) / 3
    weighted = (
        attack * _V1_PROXY_WEIGHTS["attack"]
        + midfield * _V1_PROXY_WEIGHTS["midfield_control"]
        + defence * _V1_PROXY_WEIGHTS["defence"]
    )
    return weighted / _V1_PROXY_TOTAL


@dataclass
class BacktestMetrics:
    correlation_with_goal_margin: float
    brier_score: float


@dataclass
class BacktestReport:
    n_train: int
    n_test: int
    v1: BacktestMetrics
    v2: BacktestMetrics
    v2_beats_v1: bool
    top_shap_features: list[tuple[str, float]]


def _fit_calibration(margins: list[float], results: list[int]) -> Calibration:
    won = [1 if r == 1 else 0 for r in results]
    x = np.array(margins).reshape(-1, 1)
    clf = LogisticRegression()
    clf.fit(x, won)
    return Calibration(slope=float(clf.coef_[0][0]), intercept=float(clf.intercept_[0]))


def _brier_score(probs: list[float], results: list[int]) -> float:
    won = [1 if r == 1 else 0 for r in results]
    return float(np.mean([(p - w) ** 2 for p, w in zip(probs, won, strict=True)]))


async def run_backtest() -> BacktestReport | None:
    engine = get_engine()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        examples = await build_training_examples(session)

    if len(examples) < MIN_USABLE_EXAMPLES:
        print(
            f"Only {len(examples)} usable historical matches (need real data -- "
            "DATA_SOURCE=real, then python -m pipeline.run_all) -- not enough to train rating v2."
        )
        return None

    rng = random.Random(SEED)
    shuffled = examples[:]
    rng.shuffle(shuffled)
    split = int(len(shuffled) * (1 - TEST_FRACTION))
    train, test = shuffled[:split], shuffled[split:]

    x_train = np.array([[*e.home_features, *e.away_features] for e in train])
    y_train = np.array([e.goal_margin for e in train])
    x_test = np.array([[*e.home_features, *e.away_features] for e in test])
    y_test = np.array([e.goal_margin for e in test])

    model = XGBRegressor(
        n_estimators=200, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, random_state=SEED,
    )
    model.fit(x_train, y_train)

    train_preds_v2 = model.predict(x_train).tolist()
    calibration = _fit_calibration(train_preds_v2, [e.home_result for e in train])

    test_preds_v2 = model.predict(x_test).tolist()
    test_probs_v2 = [calibration.win_probability(m) for m in test_preds_v2]
    test_results = [e.home_result for e in test]

    v1_train_margins = [_v1_proxy_overall(e.home_features) - _v1_proxy_overall(e.away_features) for e in train]
    v1_calibration = _fit_calibration(v1_train_margins, [e.home_result for e in train])
    v1_test_margins = [_v1_proxy_overall(e.home_features) - _v1_proxy_overall(e.away_features) for e in test]
    v1_test_probs = [v1_calibration.win_probability(m) for m in v1_test_margins]

    v1_corr = float(np.corrcoef(v1_test_margins, y_test)[0, 1])
    v2_corr = float(np.corrcoef(test_preds_v2, y_test)[0, 1])
    v1_corr = 0.0 if math.isnan(v1_corr) else v1_corr
    v2_corr = 0.0 if math.isnan(v2_corr) else v2_corr

    import shap

    explainer = shap.TreeExplainer(model)
    shap_values = np.asarray(explainer.shap_values(x_test))
    mean_abs_shap = np.abs(shap_values).mean(axis=0)
    top_features = sorted(zip(FEATURE_NAMES, mean_abs_shap.tolist(), strict=True), key=lambda t: -t[1])[:5]

    v1_metrics = BacktestMetrics(
        correlation_with_goal_margin=round(v1_corr, 4),
        brier_score=round(_brier_score(v1_test_probs, test_results), 4),
    )
    v2_metrics = BacktestMetrics(
        correlation_with_goal_margin=round(v2_corr, 4),
        brier_score=round(_brier_score(test_probs_v2, test_results), 4),
    )
    # "Beats" requires v2 to improve correlation with the actual goal margin (the
    # primary, documented problem this exists to fix) *without* making
    # calibration worse -- an improvement on one metric and a regression on the
    # other is a trade-off, not a win, and doesn't meet the bar for swapping the
    # live default (docs/DECISIONS.md "Rating v2").
    v2_beats_v1 = (
        v2_metrics.correlation_with_goal_margin > v1_metrics.correlation_with_goal_margin
        and v2_metrics.brier_score <= v1_metrics.brier_score
    )

    return BacktestReport(
        n_train=len(train),
        n_test=len(test),
        v1=v1_metrics,
        v2=v2_metrics,
        v2_beats_v1=v2_beats_v1,
        top_shap_features=top_features,
    )


async def main() -> None:
    report = await run_backtest()
    if report is None:
        return

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2)

    print(json.dumps(asdict(report), indent=2))
    verdict = "BEATS" if report.v2_beats_v1 else "does NOT beat"
    print(
        f"\nRating v2 {verdict} v1 (needs better correlation with the actual goal "
        f"margin *and* no worse a Brier score). Report: {REPORT_PATH}"
    )


if __name__ == "__main__":
    asyncio.run(main())
