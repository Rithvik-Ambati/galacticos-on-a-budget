"""Add team_lineup_frequency — docs/DECISIONS.md "Real opponent lineups from real
match frequency" (Part 2c).

Revision ID: 0003_team_lineup_frequency
Revises: 0002_ingest_metadata
Create Date: 2026-10-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from db.models import Base

revision = "0003_team_lineup_frequency"
down_revision = "0002_ingest_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["team_lineup_frequency"].drop(bind=bind, checkfirst=True)


_ = sa
