"""Tests for the SQL-quoting and readonly-role-derivation helpers in
db/migrations/versions/0001_initial_schema.py. These are pure functions
pulled out of the migration specifically so they're testable without a real
Postgres database.
"""

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "migration_0001",
    Path(__file__).parent.parent / "db" / "migrations" / "versions" / "0001_initial_schema.py",
)
assert _SPEC and _SPEC.loader
migration_0001 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(migration_0001)


def test_quote_ident_wraps_in_double_quotes() -> None:
    assert migration_0001._quote_ident("gaffer_ro") == '"gaffer_ro"'


def test_quote_ident_escapes_embedded_double_quotes() -> None:
    assert migration_0001._quote_ident('a"b') == '"a""b"'


def test_quote_literal_wraps_in_single_quotes() -> None:
    assert migration_0001._quote_literal("secret") == "'secret'"


def test_quote_literal_escapes_embedded_single_quotes() -> None:
    assert migration_0001._quote_literal("a'b") == "'a''b'"


def test_readonly_role_derived_from_configured_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import settings as settings_module

    settings_module.get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL_READONLY", "postgresql://ro_user:ro_pass@host:5432/db")
    user, password = migration_0001._readonly_role()
    assert user == "ro_user"
    assert password == "ro_pass"
    settings_module.get_settings.cache_clear()


def test_readonly_role_falls_back_when_no_credentials_in_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config import settings as settings_module

    settings_module.get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL_READONLY", "sqlite+aiosqlite:///./dev.db")
    user, password = migration_0001._readonly_role()
    assert user == "gaffer_ro"
    assert password == "gaffer_ro"
    settings_module.get_settings.cache_clear()
