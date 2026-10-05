"""song_analyses_lyrics

Revision ID: cd7430251da9
Revises: 47eb34cfffc1
Create Date: 2026-10-05 01:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'cd7430251da9'
down_revision: Union[str, None] = '47eb34cfffc1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('song_analyses', sa.Column('lyrics_source', sa.String(length=16), nullable=True))
    op.add_column(
        'song_analyses', sa.Column('word_count', sa.Integer(), nullable=False, server_default='0')
    )
    op.add_column(
        'song_analyses', sa.Column('syllable_count', sa.Integer(), nullable=False, server_default='0')
    )
    op.add_column(
        'song_analyses',
        sa.Column('vocable_event_count', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('song_analyses', 'vocable_event_count')
    op.drop_column('song_analyses', 'syllable_count')
    op.drop_column('song_analyses', 'word_count')
    op.drop_column('song_analyses', 'lyrics_source')
