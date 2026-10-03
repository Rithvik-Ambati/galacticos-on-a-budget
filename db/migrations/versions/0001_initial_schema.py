"""Initial schema — all tables from docs/DESIGN.md section 6.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from db.models import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


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
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_documents_metadata_gin ON documents USING gin (metadata_json)"
        )
        op.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'gaffer_ro') THEN
                    CREATE ROLE gaffer_ro LOGIN PASSWORD 'gaffer_ro';
                END IF;
            END
            $$
            """
        )
        op.execute("GRANT CONNECT ON DATABASE gaffer TO gaffer_ro")
        op.execute("GRANT USAGE ON SCHEMA public TO gaffer_ro")
        op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO gaffer_ro")
        op.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO gaffer_ro"
        )
        op.execute("ALTER ROLE gaffer_ro SET statement_timeout = '2s'")


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
    if bind.dialect.name == "postgresql":
        op.execute("DROP ROLE IF EXISTS gaffer_ro")


# Keep the import used (ruff) and document intent: table shapes come straight
# from db.models.Base, not duplicated here, so model and migration can never
# drift apart silently.
_ = sa
