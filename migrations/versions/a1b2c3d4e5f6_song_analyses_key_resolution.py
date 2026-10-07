"""song_analyses_key_resolution

Wed Oct 7, 2026 (W0 of IMPLEMENTATION_PLAN_2026-10-07.md): stores the
note-histogram cross-check's mode/confidence alongside the already-present
key_tonic_from_notes, plus the resolved winner and its low-confidence flag.

Revision ID: a1b2c3d4e5f6
Revises: a3e5f7c9b1d2
Create Date: 2026-10-07 09:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'a3e5f7c9b1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('song_analyses', sa.Column('key_mode_from_notes', sa.String(length=5), nullable=True))
    op.add_column('song_analyses', sa.Column('key_confidence_from_notes', sa.Float(), nullable=True))
    op.add_column('song_analyses', sa.Column('key_tonic_resolved', sa.String(length=2), nullable=True))
    op.add_column('song_analyses', sa.Column('key_mode_resolved', sa.String(length=5), nullable=True))
    op.add_column(
        'song_analyses', sa.Column('key_confidence_low', sa.Boolean(), nullable=False, server_default='false')
    )


def downgrade() -> None:
    op.drop_column('song_analyses', 'key_confidence_low')
    op.drop_column('song_analyses', 'key_mode_resolved')
    op.drop_column('song_analyses', 'key_tonic_resolved')
    op.drop_column('song_analyses', 'key_confidence_from_notes')
    op.drop_column('song_analyses', 'key_mode_from_notes')
