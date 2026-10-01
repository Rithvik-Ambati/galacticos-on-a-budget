"""De-biased pricing model. Implements docs/DESIGN.md section 7.2.

log(market_value) ~ ability, age, league, club_strength, position, minutes
-> ability_value predicted with age at the population mean and club_strength
neutralised -> price = 0.7*ability_value + 0.3*market_value, rounded to EUR 1M,
floored at EUR 1M, stored per tournament snapshot.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass

import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.game import BUDGET_EUR, PRICE_FLOOR_EUR, PRICE_ROUND_EUR, PRICING_ABILITY_WEIGHT, PRICING_MARKET_WEIGHT
from db.models import Player, PlayerFeatures, PlayerStatsSeason, Price
from pipeline.features import _group
from pipeline.synthetic_source import generate as generate_synthetic_world

POSITION_GROUPS = ("GK", "DF", "MF", "FW")


@dataclass
class PricingReport:
    mae_eur: float
    mae_pct_of_mean: float
    top_50: list[tuple[str, int]]  # (name, price_eur)
    budget_sanity: dict[str, object]


@dataclass
class PricingRow:
    player_id: str
    name: str
    ability_score: float
    age: float
    league_strength: float
    club_strength: float
    minutes: int
    position_group: str
    market_value_eur: int


def _age_years(dob: dt.date) -> float:
    today = dt.date.today()
    return (today - dob).days / 365.25


def _features_matrix(rows: list[PricingRow]) -> np.ndarray:
    position_cols = [[1.0 if r.position_group == g else 0.0 for g in POSITION_GROUPS] for r in rows]
    base = np.array(
        [[r.ability_score, r.age, r.league_strength, r.club_strength, r.minutes] for r in rows], dtype=float
    )
    return np.hstack([base, np.array(position_cols)])


async def compute_prices(
    session: AsyncSession, *, snapshot: str = "2026", seed: int = 42, market_values: dict[str, int] | None = None
) -> PricingReport:
    rows_raw = (
        await session.execute(
            select(Player, PlayerFeatures, PlayerStatsSeason)
            .join(PlayerFeatures, PlayerFeatures.player_id == Player.player_id)
            .join(PlayerStatsSeason, PlayerStatsSeason.player_id == Player.player_id)
        )
    ).all()

    # The "real" market value a pricing model would train against comes from
    # Transfermarkt in production; this build's stand-in source is the synthetic
    # world's own market_value_eur (docs/DECISIONS.md), looked up by player_id.
    if market_values is None:
        world = generate_synthetic_world(seed=seed)
        market_values = {p.tm_id: p.market_value_eur for p in world.tm_players}

    club_ability: dict[str, list[float]] = {}
    for player, features, _stats in rows_raw:
        assert player.current_club_id is not None, f"{player.player_id} has no club"
        club_ability.setdefault(player.current_club_id, []).append(features.ability_score)
    club_strength = {club: float(np.mean(scores)) for club, scores in club_ability.items()}

    rows: list[PricingRow] = []
    for player, features, stats in rows_raw:
        if player.player_id not in market_values:
            continue
        assert player.dob is not None, f"{player.player_id} has no date of birth"
        assert player.current_club_id is not None, f"{player.player_id} has no club"
        rows.append(
            PricingRow(
                player_id=player.player_id,
                name=player.name,
                ability_score=features.ability_score,
                age=_age_years(player.dob),
                league_strength=stats.league_strength,
                club_strength=club_strength[player.current_club_id],
                minutes=stats.minutes,
                position_group=_group(player),
                market_value_eur=market_values[player.player_id],
            )
        )

    x = _features_matrix(rows)
    y = np.log(np.array([r.market_value_eur for r in rows], dtype=float))

    x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=0.2, random_state=seed)
    model = xgb.XGBRegressor(
        n_estimators=200, max_depth=4, learning_rate=0.08, subsample=0.9, colsample_bytree=0.9,
        random_state=seed,
    )
    model.fit(x_train, y_train)

    pred_test_log = model.predict(x_test)
    mae_eur = float(np.mean(np.abs(np.exp(pred_test_log) - np.exp(y_test))))
    mae_pct = float(mae_eur / np.mean(np.exp(y_test)) * 100)

    mean_age = float(np.mean([r.age for r in rows]))
    mean_club_strength = float(np.mean(list(club_strength.values())))

    debiased_rows = [dataclasses.replace(r, age=mean_age, club_strength=mean_club_strength) for r in rows]
    x_debiased = _features_matrix(debiased_rows)
    ability_value = np.exp(model.predict(x_debiased))

    prices: list[tuple[PricingRow, int, int]] = []  # (row, price_eur, ability_value_eur)
    for r, av in zip(rows, ability_value, strict=False):
        raw_price = PRICING_ABILITY_WEIGHT * av + PRICING_MARKET_WEIGHT * r.market_value_eur
        rounded = max(PRICE_FLOOR_EUR, round(raw_price / PRICE_ROUND_EUR) * PRICE_ROUND_EUR)
        prices.append((r, int(rounded), int(round(av))))

    for r, price, ability_value_eur in prices:
        await session.merge(
            Price(
                player_id=r.player_id,
                tournament_snapshot=snapshot,
                price_eur=price,
                market_value_eur=r.market_value_eur,
                ability_value_eur=ability_value_eur,
            )
        )
    await session.commit()

    top_50 = sorted(((r.name, p) for r, p, _av in prices), key=lambda t: -t[1])[:50]

    ability_sorted = sorted(rows, key=lambda r: -r.ability_score)
    cutoff = max(1, round(0.02 * len(ability_sorted)))
    elite_ids = {r.player_id for r in ability_sorted[:cutoff]}
    elite_prices = sorted((p for r, p, _av in prices if r.player_id in elite_ids), reverse=True)
    median_price = int(np.median([p for _r, p, _av in prices]))

    affordable_elites = 0
    spent = 0
    for p in elite_prices:
        if spent + p + 8 * median_price <= BUDGET_EUR:
            spent += p
            affordable_elites += 1
        else:
            break

    budget_sanity = {
        "elite_cutoff_ability_score": ability_sorted[cutoff - 1].ability_score,
        "elite_count": len(elite_ids),
        "median_price_eur": median_price,
        "elite_prices_sample": elite_prices[:10],
        "elites_affordable_alongside_8_median_starters": affordable_elites,
        "full_elite_xi_fits_under_budget": elite_prices[0] * 11 <= BUDGET_EUR if elite_prices else False,
    }

    return PricingReport(mae_eur=mae_eur, mae_pct_of_mean=mae_pct, top_50=top_50, budget_sanity=budget_sanity)
