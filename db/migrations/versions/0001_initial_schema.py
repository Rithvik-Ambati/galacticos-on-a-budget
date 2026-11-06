"""Initial schema — all tables from docs/DESIGN.md section 6.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import make_url

from config.settings import get_settings
from db.models import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def _quote_ident(name: str) -> str:
    """Safely quote a SQL identifier (role/table/db name)."""
    return '"' + name.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    """Safely quote a SQL string literal."""
    return "'" + value.replace("'", "''") + "'"


def _readonly_role() -> tuple[str, str]:
    """The (username, password) the readonly role should have.

    Derived from DATABASE_URL_READONLY rather than hardcoded, so the role
    alembic creates/syncs always matches what llm/sql_tool.py actually
    connects with -- and so no password lives in this file (CLAUDE.md rule
    6). Falls back to the historical dev-only gaffer_ro/gaffer_ro pair when
    no readonly URL is configured (e.g. sqlite-only local dev).
    """
    url = make_url(get_settings().database_url_readonly)
    return url.username or "gaffer_ro", url.password or "gaffer_ro"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    Base.metadata.create_all(bind=bind, checkfirst=True)

    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_documents_embedding_hnsw
            ON documents USING hnsw (embedding vector_cosine_ops)
            """
        )
        op.execute("CREATE INDEX IF NOT EXISTS ix_documents_metadata_gin ON documents USING gin (metadata_json)")

        ro_user, ro_password = _readonly_role()
        current_user: str = bind.execute(sa.text("SELECT current_user")).scalar_one()
        if ro_user == current_user:
            raise RuntimeError(
                "DATABASE_URL_READONLY's role must differ from the migrating "
                f"connection's own role ({current_user!r}) -- applying a 2s "
                "statement_timeout and read-only grants to the admin role "
                "would break the whole app. Fix the readonly connection "
                "string to use a distinct, restricted role."
            )
        user_ident = _quote_ident(ro_user)
        user_literal = _quote_literal(ro_user)
        password_literal = _quote_literal(ro_password)
        db_name: str = bind.execute(sa.text("SELECT current_database()")).scalar_one()
        db_ident = _quote_ident(db_name)

        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = {user_literal}) THEN
                    CREATE ROLE {user_ident} LOGIN;
                END IF;
            END
            $$
            """
        )
        # Always re-sync the password (not only on first creation), so a role
        # left over from an earlier partial/failed migration run still ends
        # up matching the currently configured readonly credential.
        op.execute(f"ALTER ROLE {user_ident} WITH PASSWORD {password_literal}")
        op.execute(f"GRANT CONNECT ON DATABASE {db_ident} TO {user_ident}")
        op.execute(f"GRANT USAGE ON SCHEMA public TO {user_ident}")
        op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {user_ident}")
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {user_ident}")
        op.execute(f"ALTER ROLE {user_ident} SET statement_timeout = '2s'")


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
    if bind.dialect.name == "postgresql":
        ro_user, _ = _readonly_role()
        op.execute(f"DROP ROLE IF EXISTS {_quote_ident(ro_user)}")


# Keep the import used (ruff) and document intent: table shapes come straight
# from db.models.Base, not duplicated here, so model and migration can never
# drift apart silently.
_ = sa
