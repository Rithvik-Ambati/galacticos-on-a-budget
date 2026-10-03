"""Rating v2: an XGBoost regressor trained on real historical match zone features
-> goal margin (docs/DECISIONS.md "Rating v2" / docs/PROGRESS.md Part 6), swapped
in through the same `RatingModel` protocol `RatingV1` implements -- only if
`pipeline/train_rating_v2.py`'s backtest shows it actually beats v1
(`engine/rating.py::get_default_rating_model` makes that call at runtime).

Sub-ratings are intentionally UNCHANGED from v1 (the weaknesses/swaps/narration
machinery all read them, and nothing about those needed fixing) -- only `overall`
is replaced, derived from the predicted goal margin instead of the weighted
sub-rating sum. That is exactly the fix docs/DECISIONS.md's "Known limitations"
describes: v1's sub-ratings (36% of overall) don't feed expected goals at all, so
rating and simulated win% could disagree; deriving overall from a margin a model
actually learned from real match outcomes closes that gap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from engine.rating import RatingV1
from engine.schemas import Lineup, RatingResult, TeamProfile
from engine.zones import slot_defs, zone_average

# Same (vertical, horizontal) order pipeline/rating_v2_dataset.py's ZONES uses --
# the trained model's feature vector is [*home 9 zones, *away 9 zones] in this
# exact order; changing it here without retraining silently breaks predictions.
ZONES: tuple[tuple[str, str], ...] = tuple(
    (v, h) for v in ("def", "mid", "att") for h in ("left", "center", "right")
)
ZONE_FALLBACK_ABILITY = 50.0


def lineup_zone_features(lineup: Lineup) -> tuple[float, ...]:
    defs = slot_defs(lineup.formation)
    return tuple(zone_average(lineup, defs, v, h) or ZONE_FALLBACK_ABILITY for v, h in ZONES)


class MarginRegressor(Protocol):
    """What RatingV2 needs from the trained model -- just enough of XGBRegressor's
    interface to avoid importing xgboost's own type here."""

    def predict(self, X: Any) -> Any: ...  # noqa: N803 - matches sklearn/xgboost's own convention


@dataclass
class Calibration:
    """Maps a raw predicted goal margin to a 0-100 "overall" via a logistic
    win-probability fit (`pipeline/train_rating_v2.py` fits `slope`/`intercept`
    against the training set's actual results, not hand-picked): overall = 50 +
    50 * (2 * P(home win | margin) - 1), so overall=50 means a 50/50 match,
    overall=100 means the model is maximally confident of a win."""

    slope: float
    intercept: float

    def win_probability(self, margin: float) -> float:
        import math

        # Clipped before exponentiating -- an extreme margin times a steep slope
        # can push -z past ~709 and overflow math.exp (a real crash this hit on
        # its very first test), well before the probability itself would ever
        # need to distinguish values this far into certainty.
        z = max(-700.0, min(700.0, self.intercept + self.slope * margin))
        return 1.0 / (1.0 + math.exp(-z))

    def to_overall(self, margin: float) -> float:
        p_win = self.win_probability(margin)
        return max(1.0, min(99.0, 50.0 + 50.0 * (2.0 * p_win - 1.0)))


class RatingV2:
    def __init__(self, model: MarginRegressor, calibration: Calibration) -> None:
        self._model = model
        self._calibration = calibration
        self._v1 = RatingV1()

    def predict_margin(self, lineup: Lineup, opponent_lineup: Lineup | None) -> float:
        home_features = lineup_zone_features(lineup)
        away_features = (
            lineup_zone_features(opponent_lineup)
            if opponent_lineup is not None
            else tuple([ZONE_FALLBACK_ABILITY] * len(ZONES))
        )
        return float(self._model.predict([[*home_features, *away_features]])[0])

    def rate(
        self, lineup: Lineup, opponent: TeamProfile, opponent_lineup: Lineup | None = None
    ) -> RatingResult:
        v1_result = self._v1.rate(lineup, opponent, opponent_lineup)
        margin = self.predict_margin(lineup, opponent_lineup)
        overall = round(self._calibration.to_overall(margin), 1)
        return RatingResult(sub_ratings=v1_result.sub_ratings, overall=overall)
