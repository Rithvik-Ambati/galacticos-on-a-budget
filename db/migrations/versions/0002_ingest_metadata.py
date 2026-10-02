"""Add ingest_metadata — docs/DECISIONS.md "Synthetic data is no longer the silent
default": api/main.py's startup now refuses to boot without a row here.

Revision ID: 0002_ingest_metadata
Revises: 0001_initial_schema
Create Date: 2026-10-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from db.models import Base

revision = "0002_ingest_metadata"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # checkfirst=True: only the tables that don't already exist (ingest_metadata, on
    # a database that already ran 0001) get created -- same idempotent pattern 0001
    # itself uses, so model and migration can never drift apart silently.
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["ingest_metadata"].drop(bind=bind, checkfirst=True)


_ = sa
