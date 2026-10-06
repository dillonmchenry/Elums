"""song_analyses_f0_chart_peaks

Revision ID: f1a9c6b2e4d1
Revises: cd7430251da9
Create Date: 2026-10-06 09:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f1a9c6b2e4d1'
down_revision: Union[str, None] = 'cd7430251da9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('song_analyses', sa.Column('f0_blob_sha256', sa.String(length=64), nullable=True))
    op.create_foreign_key(
        'fk_song_analyses_f0_blob_sha256_blobs', 'song_analyses', 'blobs', ['f0_blob_sha256'], ['sha256']
    )
    op.add_column('song_analyses', sa.Column('frame_rate_hz', sa.Float(), nullable=True))
    op.add_column('song_analyses', sa.Column('voiced_frame_ratio', sa.Float(), nullable=True))

    op.add_column('song_analyses', sa.Column('chart_blob_sha256', sa.String(length=64), nullable=True))
    op.create_foreign_key(
        'fk_song_analyses_chart_blob_sha256_blobs', 'song_analyses', 'blobs', ['chart_blob_sha256'], ['sha256']
    )
    op.add_column('song_analyses', sa.Column('peaks_blob_sha256', sa.String(length=64), nullable=True))
    op.create_foreign_key(
        'fk_song_analyses_peaks_blob_sha256_blobs', 'song_analyses', 'blobs', ['peaks_blob_sha256'], ['sha256']
    )
    op.add_column(
        'song_analyses', sa.Column('note_count', sa.Integer(), nullable=False, server_default='0')
    )
    op.add_column('song_analyses', sa.Column('key_tonic_from_notes', sa.String(length=2), nullable=True))


def downgrade() -> None:
    op.drop_column('song_analyses', 'key_tonic_from_notes')
    op.drop_column('song_analyses', 'note_count')
    op.drop_constraint('fk_song_analyses_peaks_blob_sha256_blobs', 'song_analyses', type_='foreignkey')
    op.drop_column('song_analyses', 'peaks_blob_sha256')
    op.drop_constraint('fk_song_analyses_chart_blob_sha256_blobs', 'song_analyses', type_='foreignkey')
    op.drop_column('song_analyses', 'chart_blob_sha256')
    op.drop_column('song_analyses', 'voiced_frame_ratio')
    op.drop_column('song_analyses', 'frame_rate_hz')
    op.drop_constraint('fk_song_analyses_f0_blob_sha256_blobs', 'song_analyses', type_='foreignkey')
    op.drop_column('song_analyses', 'f0_blob_sha256')
