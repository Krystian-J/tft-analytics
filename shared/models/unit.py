from datetime import datetime

from pydantic import BaseModel


class UnitRowModel(BaseModel):
    """
    Represents a single flat row written to ClickHouse tft.unit_stats table.
    One row per unit per participant per game.
    A single 8-player game produces approximately 72 rows.

    LP and tier are denormalized from the most recent league_entries row
    for the participant's puuid at save time.
    """

    # -------------------------------------------------------------------------
    # Match level
    # -------------------------------------------------------------------------
    match_id: str
    game_datetime: datetime
    game_version: str
    tft_set_number: int
    queue_id: int

    # -------------------------------------------------------------------------
    # Participant level
    # -------------------------------------------------------------------------
    puuid: str
    placement: int
    level: int
    last_round: int
    gold_left: int
    players_eliminated: int
    total_damage_to_players: int

    # Denormalized from league_entries at save time
    tier: str
    rank: str
    lp: int

    # -------------------------------------------------------------------------
    # Unit level
    # -------------------------------------------------------------------------
    character_id: str
    unit_name: str        # may be empty string, kept for future use
    unit_tier: int        # star level (1, 2, 3)
    unit_rarity: int      # 0=1cost, 1=2cost, 2=3cost, 4=4cost, 6=5cost

    # Items — empty string if slot is empty
    item_1: str = ""
    item_2: str = ""
    item_3: str = ""
