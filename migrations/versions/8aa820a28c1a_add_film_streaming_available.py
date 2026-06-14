"""add film.streaming_available

Revision ID: 8aa820a28c1a
Revises: 
Create Date: 2026-06-13 14:20:38.175593

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8aa820a28c1a'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add film.streaming_available and backfill a sample of titles to TRUE."""
    op.add_column(
        "film",
        sa.Column(
            "streaming_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Backfill a realistic sample so the catalog has a mix of streamable titles.
    # Includes every "Alien" title (titles are uppercase in Pagila: ALIEN CENTER,
    # DESIRE ALIEN, HOBBIT ALIEN) so the "Is Alien available for streaming?" eval
    # returns a streamable hit, plus the first 50 films for variety.
    op.execute(
        """
        UPDATE film
        SET streaming_available = TRUE
        WHERE title ILIKE '%alien%'
           OR film_id <= 50
        """
    )


def downgrade() -> None:
    """Drop film.streaming_available."""
    op.drop_column("film", "streaming_available")
