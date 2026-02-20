"""Initial tables: league_entries, player_crawls, matches

Revision ID: 0001
Revises: 
Create Date: 2026-02-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # league_entries
    # Stores player data from league endpoint — LP, tier, wins, losses
    # -------------------------------------------------------------------------
    op.create_table(
        "league_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("puuid", sa.String(), nullable=False),
        sa.Column("tier", sa.String(), nullable=False),
        sa.Column("rank", sa.String(), nullable=True),
        sa.Column("league_points", sa.Integer(), nullable=False),
        sa.Column("wins", sa.Integer(), nullable=False),
        sa.Column("losses", sa.Integer(), nullable=False),
        sa.Column("veteran", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("inactive", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("fresh_blood", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("hot_streak", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("fetched_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("raw_response", JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_league_entries_puuid", "league_entries", ["puuid"])

    # -------------------------------------------------------------------------
    # player_crawls
    # Tracks when each player was last crawled for match history
    # -------------------------------------------------------------------------
    op.create_table(
        "player_crawls",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("puuid", sa.String(), nullable=False),
        sa.Column("last_crawled_at", sa.DateTime(), nullable=False),
        sa.Column("matches_found", sa.Integer(), nullable=False, default=0),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("puuid", name="uq_player_crawls_puuid"),
    )
    op.create_index("ix_player_crawls_puuid", "player_crawls", ["puuid"])

    # -------------------------------------------------------------------------
    # matches
    # Stores raw match data — metadata columns + full raw JSONB response
    # -------------------------------------------------------------------------
    op.create_table(
        "matches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("match_id", sa.String(), nullable=False),
        sa.Column("game_datetime", sa.DateTime(), nullable=False),
        sa.Column("game_length", sa.Float(), nullable=False),
        sa.Column("game_version", sa.String(), nullable=False),
        sa.Column("tft_set_number", sa.Integer(), nullable=False),
        sa.Column("queue_id", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("raw_response", JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_id", name="uq_matches_match_id"),
    )
    op.create_index("ix_matches_match_id", "matches", ["match_id"])
    op.create_index("ix_matches_game_datetime", "matches", ["game_datetime"])
    op.create_index("ix_matches_game_version", "matches", ["game_version"])


def downgrade() -> None:
    """Drops all tables — reverses the upgrade migration."""
    op.drop_table("matches")
    op.drop_table("player_crawls")
    op.drop_table("league_entries")
