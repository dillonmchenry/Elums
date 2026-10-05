"""songs_artist

Revision ID: 47eb34cfffc1
Revises: 5a7a503e7300
Create Date: 2026-10-05 01:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '47eb34cfffc1'
down_revision: Union[str, None] = '5a7a503e7300'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('songs', sa.Column('artist', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('songs', 'artist')
