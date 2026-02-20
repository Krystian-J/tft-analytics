from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LeagueEntry(Base):
    """
    Stores raw player data returned by the league endpoint.
    One row per player per crawl cycle — tracks LP, tier, wins, losses.
    This is the source of LP and tier data used for ClickHouse analytics filtering.
    """
    __tablename__ = "league_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    puuid: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tier: Mapped[str] = mapped_column(String, nullable=False)        # CHALLENGER, GRANDMASTER, MASTER, DIAMOND etc.
    rank: Mapped[str] = mapped_column(String, nullable=True)         # I, II, III, IV (null for Challenger/GM)
    league_points: Mapped[int] = mapped_column(Integer, nullable=False)
    wins: Mapped[int] = mapped_column(Integer, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, nullable=False)
    veteran: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    inactive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fresh_blood: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hot_streak: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    raw_response: Mapped[dict] = mapped_column(JSONB, nullable=False)


class PlayerCrawl(Base):
    """
    Tracks when each player was last crawled for match history.
    Used by the crawler to avoid re-crawling the same player within a cycle
    and to know which players are fully up to date.
    """
    __tablename__ = "player_crawls"
    __table_args__ = (
        UniqueConstraint("puuid", name="uq_player_crawls_puuid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    puuid: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    last_crawled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    matches_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # how many new matches were found


class Match(Base):
    """
    Stores raw match data returned by the match detail endpoint.
    One row per match — metadata columns for indexing alongside full raw JSONB.
    Raw JSONB enables re-parsing later if ClickHouse schema changes.
    """
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("match_id", name="uq_matches_match_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    game_datetime: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    game_length: Mapped[float] = mapped_column(Float, nullable=False)
    game_version: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tft_set_number: Mapped[int] = mapped_column(Integer, nullable=False)
    queue_id: Mapped[int] = mapped_column(Integer, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    raw_response: Mapped[dict] = mapped_column(JSONB, nullable=False)  # full raw Riot API response
