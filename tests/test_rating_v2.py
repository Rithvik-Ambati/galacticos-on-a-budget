"""engine/rating_v2.py: zone-feature extraction, calibration math, and RatingV2.rate()
against a fake (untrained) model -- no real XGBoost model is trained in this test
suite (that needs real historical data; pipeline/train_rating_v2.py, docs/PROGRESS.md
Part 6, exercises the real training+backtest path and isn't run in CI).
"""

from __future__ import annotations

from engine.demo_fixtures import BRAZIL_OPPONENT_LINEUP, BRAZIL_PROFILE, build_demo_lineup
from engine.rating import RatingV1
from engine.rating_v2 import ZONE_FALLBACK_ABILITY, ZONES, Calibration, RatingV2, lineup_zone_features


class _FakeModel:
    def __init__(self, margin: float) -> None:
        self.margin = margin
        self.last_input = None

    def predict(self, x):
        self.last_input = x
        return [self.margin]


def test_lineup_zone_features_has_nine_zones_in_order() -> None:
    lineup = build_demo_lineup("strong")
    features = lineup_zone_features(lineup)
    assert len(features) == len(ZONES) == 9
    assert all(0.0 <= f <= 100.0 for f in features)


def test_calibration_at_zero_margin_is_fifty_fifty() -> None:
    calibration = Calibration(slope=0.5, intercept=0.0)
    assert calibration.win_probability(0.0) == 0.5
    assert calibration.to_overall(0.0) == 50.0


def test_calibration_clips_to_1_99() -> None:
    calibration = Calibration(slope=10.0, intercept=0.0)
    assert calibration.to_overall(100.0) == 99.0
    assert calibration.to_overall(-100.0) == 1.0


def test_calibration_positive_margin_is_above_fifty() -> None:
    calibration = Calibration(slope=0.3, intercept=0.0)
    assert calibration.to_overall(2.0) > 50.0
    assert calibration.to_overall(-2.0) < 50.0


def test_rating_v2_keeps_v1_sub_ratings_and_uses_calibrated_overall() -> None:
    lineup = build_demo_lineup("strong")
    v1_result = RatingV1().rate(lineup, BRAZIL_PROFILE, BRAZIL_OPPONENT_LINEUP)

    model = _FakeModel(margin=3.0)
    calibration = Calibration(slope=0.4, intercept=0.0)
    v2 = RatingV2(model, calibration)
    v2_result = v2.rate(lineup, BRAZIL_PROFILE, BRAZIL_OPPONENT_LINEUP)

    assert v2_result.sub_ratings == v1_result.sub_ratings
    assert v2_result.overall == round(calibration.to_overall(3.0), 1)
    # the model's own input is [*home 9 features, *away 9 features] -- 18 total
    assert len(model.last_input[0]) == 18


def test_rating_v2_falls_back_to_league_average_without_an_opponent_lineup() -> None:
    lineup = build_demo_lineup("strong")
    model = _FakeModel(margin=0.0)
    calibration = Calibration(slope=0.4, intercept=0.0)
    v2 = RatingV2(model, calibration)

    v2.predict_margin(lineup, opponent_lineup=None)
    away_half = model.last_input[0][9:]
    assert away_half == [ZONE_FALLBACK_ABILITY] * 9
