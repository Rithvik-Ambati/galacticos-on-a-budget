"""Guarded text-to-SQL. CLAUDE.md rule 5: the `readonly` DB role, a table allowlist,
a SELECT-only parser check, a statement timeout, and a row limit.

In production this runs against DATABASE_URL_READONLY (the Postgres `lineuplab_ro`
role the Phase 1 migration creates, which itself has `statement_timeout = '2s'` set at
the role level -- see db/migrations/versions/0001_initial_schema.py). There is no
per-role privilege system in SQLite, so in this dev/test environment the guardrails
below are the only enforcement; docs/DECISIONS.md notes this is one more place the
Postgres path was written but never exercised live.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ALLOWED_TABLES = {
    "players", "player_features", "player_stats_season", "prices", "squads",
    "clubs", "national_teams", "team_profiles",
}
FORBIDDEN_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "create", "attach", "detach",
    "pragma", "replace", "truncate", "grant", "revoke", "vacuum", "reindex",
)
ROW_LIMIT = 200
STATEMENT_TIMEOUT_SECONDS = 2.0

_TABLE_RE = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\blimit\s+\d+\b", re.IGNORECASE)


@dataclass
class GuardResult:
    ok: bool
    sql: str | None
    reason: str | None


def guard_sql(sql: str) -> GuardResult:
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        return GuardResult(False, None, "empty query")

    if ";" in cleaned:
        return GuardResult(False, None, "multiple statements are not allowed")

    first_word = cleaned.split(None, 1)[0].lower() if cleaned.split() else ""
    if first_word != "select":
        return GuardResult(False, None, "only SELECT statements are allowed")

    lowered = cleaned.lower()
    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", lowered):
            return GuardResult(False, None, f"forbidden keyword: {kw}")

    tables = {t.lower() for t in _TABLE_RE.findall(cleaned)}
    disallowed = tables - ALLOWED_TABLES
    if disallowed:
        return GuardResult(False, None, f"table(s) not in allowlist: {', '.join(sorted(disallowed))}")
    if not tables:
        return GuardResult(False, None, "no recognisable table reference")

    if not _LIMIT_RE.search(cleaned):
        cleaned = f"{cleaned} LIMIT {ROW_LIMIT}"

    return GuardResult(True, cleaned, None)


@dataclass
class SqlToolResult:
    ok: bool
    rows: list[dict[str, object]]
    reason: str | None


async def execute_guarded_sql(
    session: AsyncSession, sql: str, *, timeout_seconds: float = STATEMENT_TIMEOUT_SECONDS
) -> SqlToolResult:
    guard = guard_sql(sql)
    if not guard.ok or guard.sql is None:
        return SqlToolResult(ok=False, rows=[], reason=guard.reason)

    try:
        result = await asyncio.wait_for(session.execute(text(guard.sql)), timeout=timeout_seconds)
    except TimeoutError:
        return SqlToolResult(ok=False, rows=[], reason=f"query exceeded {timeout_seconds}s timeout")
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller, never to a prompt unescaped
        return SqlToolResult(ok=False, rows=[], reason=f"query failed: {exc}")

    rows = [dict(r) for r in result.mappings().all()]
    return SqlToolResult(ok=True, rows=rows, reason=None)
