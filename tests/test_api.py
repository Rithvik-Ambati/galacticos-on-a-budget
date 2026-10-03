"""End-to-end API test. Implements the Phase 6 acceptance check: "make api + make web
gives a fully playable game" -- this drives the API half of that through a complete
session over real HTTP semantics (httpx's ASGI transport, no sockets needed).

DATABASE_URL must be set before `api.main` (and anything importing `config.settings`)
is first imported, since `get_settings`/`get_engine` are process-wide singletons --
hence this happens at module import time, before the rest of the imports below.
"""

from __future__ import annotations

import os
import tempfile

_TEST_DB_PATH = os.path.join(tempfile.mkdtemp(prefix="gaffer_api_test_"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB_PATH}"
os.environ["LLM_PROVIDER"] = "stub"
# DATA_SOURCE now defaults to "real" (docs/DECISIONS.md "Synthetic data is no longer
# the silent default") -- tests must opt into synthetic explicitly, never rely on
# the default, so they don't require data_raw/ to exist in CI.
os.environ["DATA_SOURCE"] = "synthetic"

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from api.main import app  # noqa: E402
from db.session import get_engine  # noqa: E402
from engine.optimizer import find_optimal_lineup  # noqa: E402
from pipeline.features import compute_features  # noqa: E402
from pipeline.ingest import run_ingest  # noqa: E402
from pipeline.pricing import compute_prices  # noqa: E402
from pipeline.team_profiles import compute_team_profiles  # noqa: E402
from pipeline.to_engine import load_candidate_pool, load_squad_player_ids  # noqa: E402

SEED = 42
_seeded = False


async def _ensure_seeded() -> None:
    global _seeded
    if _seeded:
        return
    engine = get_engine()
    await run_ingest(engine, seed=SEED, output_dir=os.path.dirname(_TEST_DB_PATH))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await compute_features(session)
    async with session_factory() as session:
        await compute_prices(session, seed=SEED)
    async with session_factory() as session:
        await compute_team_profiles(session)
    _seeded = True


@pytest.fixture
async def client():
    await _ensure_seeded()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _build_optimal_assignments(opponent_team_id: str) -> dict[str, str]:
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with session_factory() as session:
        opp_ids = await load_squad_player_ids(session, opponent_team_id)
        pool = await load_candidate_pool(session, exclude_ids=opp_ids, limit=400)
    best = find_optimal_lineup("4-3-3", pool, opp_ids, time_limit_seconds=8.0)
    assert best is not None
    return {slot: c.player_id for slot, c in best.assignments.items()}


async def test_health(client: httpx.AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # httpx's ASGITransport doesn't drive FastAPI's lifespan (see
    # test_lifespan.py for a direct test of the startup guard/data_source fields
    # themselves) -- this just confirms the shape /health promises to the frontend.
    assert "data_source" in body
    assert "dataset_snapshot_date" in body
    assert "pipeline_run_at" in body


async def test_unknown_session_is_404(client: httpx.AsyncClient) -> None:
    r = await client.get("/sessions/does-not-exist")
    assert r.status_code == 404


async def test_full_session_over_http(client: httpx.AsyncClient) -> None:
    r = await client.post("/sessions", json={"mode": "wc"})
    assert r.status_code == 200
    session_id = r.json()["session_id"]

    r = await client.post(f"/sessions/{session_id}/draw")
    assert r.status_code == 200
    opponent_team_id = r.json()["opponent_team_id"]
    assert opponent_team_id.startswith("nt_")
    assert r.json()["awaiting"] == "lineup"

    r = await client.get(f"/sessions/{session_id}/scout")
    assert r.status_code == 200
    assert r.json()["opponent_team_id"] == opponent_team_id
    assert len(r.json()["danger_players"]) > 0

    r = await client.get(f"/sessions/{session_id}/players/search", params={"q": "a", "limit": 5})
    assert r.status_code == 200
    assert len(r.json()["results"]) <= 5
    for result in r.json()["results"]:
        assert "eligible" in result["eligibility"]

    assignments = await _build_optimal_assignments(opponent_team_id)

    r = await client.post(
        f"/sessions/{session_id}/lineup/validate", json={"formation": "4-3-3", "assignments": assignments}
    )
    assert r.status_code == 200
    assert r.json()["valid"]

    r = await client.post(
        f"/sessions/{session_id}/lineup/analyse", json={"formation": "4-3-3", "assignments": assignments}
    )
    assert r.status_code == 200
    body = r.json()
    assert 0.0 <= body["analysis"]["rating"]["overall"] <= 100.0
    assert body["coach_report_text"]
    assert body["awaiting"] == "decision"

    r = await client.post(f"/sessions/{session_id}/decision", json={"decision": "lock_in"})
    assert r.status_code == 200
    body = r.json()
    assert body["simulation"] is not None
    assert body["match_report_text"]
    assert body["awaiting"] == "question"

    async with client.stream(
        "POST", f"/sessions/{session_id}/chat", json={"question": "what are the odds?"}
    ) as resp:
        assert resp.status_code == 200
        chunks = [line async for line in resp.aiter_lines() if line]
    assert any("done" in c for c in chunks)
    assert any("%" in c for c in chunks)

    r = await client.post(f"/sessions/{session_id}/chat/end")
    assert r.status_code == 200

    r = await client.get(f"/sessions/{session_id}")
    assert r.status_code == 200
    final = r.json()
    assert final["opponent_team_id"] == opponent_team_id
    assert len(final["messages"]) == 2


async def test_invalid_lineup_returns_422(client: httpx.AsyncClient) -> None:
    r = await client.post("/sessions", json={"mode": "wc"})
    session_id = r.json()["session_id"]
    r = await client.post(f"/sessions/{session_id}/draw")
    opponent_team_id = r.json()["opponent_team_id"]

    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with session_factory() as session:
        opp_ids = await load_squad_player_ids(session, opponent_team_id)
        pool = await load_candidate_pool(session, exclude_ids=opp_ids, limit=400)
    by_group: dict[str, list] = {}
    for c in pool:
        by_group.setdefault(c.position_group, []).append(c)
    slots = {
        "GK": "GK", "LB": "DF", "CB1": "DF", "CB2": "DF", "RB": "DF", "DM": "MF",
        "LCM": "MF", "RCM": "MF", "LW": "FW", "ST": "FW", "RW": "FW",
    }
    too_expensive = {slot: max(by_group[grp], key=lambda c: c.price_eur).player_id for slot, grp in slots.items()}

    r = await client.post(
        f"/sessions/{session_id}/lineup/analyse", json={"formation": "4-3-3", "assignments": too_expensive}
    )
    assert r.status_code == 422


async def test_simulate_before_lock_in_is_409(client: httpx.AsyncClient) -> None:
    r = await client.post("/sessions", json={"mode": "wc"})
    session_id = r.json()["session_id"]
    await client.post(f"/sessions/{session_id}/draw")
    r = await client.post(f"/sessions/{session_id}/simulate")
    assert r.status_code == 409


async def test_rematch_pins_the_same_opponent_and_carries_the_lineup(client: httpx.AsyncClient) -> None:
    r = await client.post("/sessions", json={"mode": "wc"})
    session_id = r.json()["session_id"]
    r = await client.post(f"/sessions/{session_id}/draw")
    opponent_team_id = r.json()["opponent_team_id"]
    assignments = await _build_optimal_assignments(opponent_team_id)
    await client.post(f"/sessions/{session_id}/lineup/analyse", json={"formation": "4-3-3", "assignments": assignments})
    await client.post(f"/sessions/{session_id}/decision", json={"decision": "lock_in"})

    r = await client.post(f"/sessions/{session_id}/rematch")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] != session_id
    assert body["opponent_team_id"] == opponent_team_id
    assert body["formation"] == "4-3-3"
    assert body["assignments"] == assignments
    assert body["valid"]
    assert set(body["players"]) == set(assignments.values())

    # the new session is independently playable from where it was left off
    r = await client.get(f"/sessions/{body['session_id']}")
    assert r.status_code == 200
    assert r.json()["opponent_team_id"] == opponent_team_id


async def test_scouting_lineup_matches_the_graph_states_own_opponent_lineup(client: httpx.AsyncClient) -> None:
    """B1: the opponent XI shown on the scouting screen must be the exact same one
    rating/counter/simulation use (graph/nodes.py's draw()/opponent_counter() are the
    only writers of opponent_lineup_assignments/opponent_formation; scout() must read
    that state, never recompute a second, possibly-divergent lineup). Proven by
    driving a real counter round and confirming scout()'s lineup changes to match
    exactly what that round reported changing -- not just that scout() is stable."""
    r = await client.post("/sessions", json={"mode": "wc"})
    session_id = r.json()["session_id"]
    r = await client.post(f"/sessions/{session_id}/draw")
    opponent_team_id = r.json()["opponent_team_id"]

    r = await client.get(f"/sessions/{session_id}/scout")
    assert r.status_code == 200
    before = r.json()
    assert before["lineup_source"] == "estimated"
    assert len(before["opponent_lineup"]) > 0
    squad_ids = await _squad_player_ids(opponent_team_id)
    assert all(p["player_id"] in squad_ids for p in before["opponent_lineup"].values())

    assignments = await _build_optimal_assignments(opponent_team_id)
    await client.post(f"/sessions/{session_id}/lineup/analyse", json={"formation": "4-3-3", "assignments": assignments})
    r = await client.post(f"/sessions/{session_id}/decision", json={"decision": "counter"})
    counter_round = r.json()["last_counter_round"]

    r = await client.get(f"/sessions/{session_id}/scout")
    after = r.json()
    assert after["opponent_formation"] == counter_round["opponent_formation"]
    if any(m["move_type"] == "substitute" for m in counter_round["moves"]):
        assert after["opponent_lineup"] != before["opponent_lineup"]
        sub = next(m for m in counter_round["moves"] if m["move_type"] == "substitute")
        after_ids = {p["player_id"] for p in after["opponent_lineup"].values()}
        assert sub["player_in_id"] in after_ids


async def _squad_player_ids(team_id: str) -> set[str]:
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with session_factory() as session:
        return await load_squad_player_ids(session, team_id)


async def test_rematch_before_any_draw_is_409(client: httpx.AsyncClient) -> None:
    r = await client.post("/sessions", json={"mode": "wc"})
    session_id = r.json()["session_id"]
    r = await client.post(f"/sessions/{session_id}/rematch")
    assert r.status_code == 409
